"""A second look at a Houdini step whose parameter label Houdini does not have on that node: the clip of the step, the node's REAL parameter list, and one question, "which of these did the instructor
change?". It corrects a label like "Target Pattern" (which APEX Configure Controls does not have) to the one Houdini shows ("Control Group") instead of only flagging it.

Rules, because a confident wrong correction is worse than an honest flag:
  * when the step gives a value ("Set Target Pattern to point*"), the clip's value for the label it names must be that value: otherwise it named another parameter changed in the same clip;
  * the answer must be a label from the node's own list (knowledge/app_vocab/houdini.json, Houdini 22.0.466), matched exactly; anything else is ignored;
  * the model must say it SAW the label in the clip, with a short description of what it saw; "cannot tell" is an accepted answer and keeps the flag;
  * only the label words are replaced in the step (how-to lines, action names, goal); values, names and patterns the step already has are kept;
  * the flag is replaced by a note that says what was corrected and where to check it, so the reviewer sees every correction;
  * one call per flagged step, on the step's own clip (a few seconds either side), through the same cost guard as extraction; a failed call leaves the step as it was.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from shared.step_record import Step, StepList

from . import houdini_parms as hp

PAD_S = 3.0
MAX_LABELS = 160

SYSTEM = """You look at ONE short clip of a Houdini tutorial and answer ONE question about the parameter pane. Use only what is SHOWN on screen in the clip.
You are given the parameters a node really has in Houdini. Say which of them the instructor changes in this clip, using a label from the list EXACTLY as written there.
If the clip does not let you see which parameter it is, set seen to false and label to an empty string: never pick a label because it sounds right.
Return JSON only."""

SCHEMA = {
    "type": "object",
    "properties": {
        "seen": {"type": "boolean", "description": "true only if the clip shows the parameter pane with the parameter the instructor changes"},
        "label": {"type": "string", "description": "the label from the list, exactly as written in the list; an empty string when not seen"},
        "value": {"type": "string", "description": "what the instructor types or chooses in that parameter in the clip, exactly; an empty string when not seen"},
        "evidence": {"type": "string", "description": "what is visible in the clip that shows it: the label text and where it is"},
    },
    "required": ["seen", "label", "value", "evidence"],
}


@dataclass(frozen=True)
class Repair:
    step_id: str
    wrong: str
    node: str                  # the network editor's name for the node ("APEX Configure Controls")
    label: str | None          # the label the clip shows, from the node's list; None when not seen or not accepted
    evidence: str = ""
    reason: str = ""           # why an answer was not accepted


def _choices(nodes: list[str]) -> list[str]:
    """The labels a learner can see in the parameter pane of these nodes, as Houdini writes them (icon markers and blank labels left out)."""
    import json
    raw = json.loads(hp.VOCAB.read_text(encoding="utf-8")).get("sop_parm_labels", {})
    out: list[str] = []
    for key in nodes:
        for lab in raw.get(hp.label_of(key), []):
            lab = lab.strip()
            if lab and not lab.startswith("!") and len(lab) <= 40 and lab not in out:
                out.append(lab)
    return out[:MAX_LABELS]


def question(step: Step, wrong: str, node_label: str, choices: list[str]) -> str:
    line = next((h.text for h in step.how_to if wrong.lower() in h.text.lower()), step.goal)
    return (f'In this clip the instructor works on the node "{node_label}". The written step says: "{line}". But "{wrong}" is not a parameter of {node_label} in Houdini.\n'
            f"The parameters {node_label} has are:\n" + "\n".join(f"- {c}" for c in choices) +
            f'\nWhich ONE of these does the instructor change in this clip where the step says "{wrong}"? Answer with the label exactly as it is written in the list, or seen=false if the clip does not show it.')


def value_in(step: Step, wrong: str) -> str:
    """The value the step says goes into the wrong label ("Set Target Controls to 'point.*'" -> "point.*"), or "" when the step gives none."""
    for text in [*(h.text for h in step.how_to), *(f"{a.ui_element} to {a.value}" for a in step.actions if a.ui_element and a.value)]:
        m = re.search(re.escape(wrong) + r"\s*(?:parameters?|fields?)?\s*(?:to|into|=|:)\s*(?:'([^']+)'|\"([^\"]+)\"|(\S+))", text, re.I)      # quoted, or one word
        if m:
            return next(g for g in m.groups() if g).strip().rstrip(".,;")
    return ""


def _norm(v: str) -> str:
    return re.sub(r"[\s'\"`.]", "", v.lower())


def same_value(said: str, got: str) -> bool:
    """The clip's value is the step's value (ignoring quotes, spaces, dots and case; "point*" and "point.*" are the same pattern as far as a learner reading the label is concerned): the corrected
    label is the parameter that got THIS value, not another one changed in the same clip (the first real run corrected "Target Controls = point.*" to Shape Override, which was set to box)."""
    a, b = _norm(said), _norm(got)
    return bool(a and b) and (a in b or b in a)


def _replace(text: str, wrong: str, right: str) -> str:
    return re.sub(re.escape(wrong), right, text, flags=re.I)


def repair_step(provider, step: Step, video_url: str, duration_s: float | None = None) -> list[Repair]:
    """Ask about each unknown label of one step. Returns what was decided; the step is changed in place for the accepted answers."""
    out: list[Repair] = []
    if step.video_start_s is None or step.video_end_s is None:
        return out
    a = max(0.0, step.video_start_s - PAD_S)
    b = step.video_end_s + PAD_S if duration_s is None else min(float(duration_s), step.video_end_s + PAD_S)
    for wrong, nodes in hp.unknown_labels(step):
        node_label = hp.label_of(nodes[0])
        choices = _choices(nodes)
        if not choices:
            continue
        if hasattr(provider, "video_seconds"):
            provider.video_seconds = b - a
        try:
            res = provider.generate_json(system=SYSTEM, prompt=question(step, wrong, node_label, choices), schema=SCHEMA, video_url=f"{video_url}#t={int(a)},{int(b)}")
        except Exception as e:                                       # quota, network, budget: the step stays flagged
            out.append(Repair(step.id, wrong, node_label, None, reason=f"the second look could not be made ({type(e).__name__})"))
            continue
        label = (res or {}).get("label")
        seen = bool((res or {}).get("seen"))
        evidence = str((res or {}).get("evidence") or "").strip()
        exact = next((c for c in choices if label and c.lower() == str(label).strip().lower()), None)
        said = value_in(step, wrong)
        got = str((res or {}).get("value") or "")
        if not seen or exact is None or not evidence or (said and not same_value(said, got)):
            why = ("the clip did not show which parameter it is" if not seen else "the answer was not a label of that node" if exact is None else "no evidence was given" if not evidence
                   else f"the parameter it named was given '{got}' in the clip, not '{said}' as the step says")
            out.append(Repair(step.id, wrong, node_label, None, evidence, why))
            continue
        for h in step.how_to:
            h.text = _replace(h.text, wrong, exact)
        for act in step.actions:
            if act.ui_element:
                act.ui_element = _replace(act.ui_element, wrong, exact)
        step.goal = _replace(step.goal, wrong, exact)
        out.append(Repair(step.id, wrong, node_label, exact, evidence))
    _note(step, out, a, b)
    return out


def _note(step: Step, repairs: list[Repair], a: float, b: float) -> None:
    """Replace the "is not a parameter" flag of each repaired label by a note that says what changed; keep it, with the reason, for the others."""
    from .extract import _mmss
    for r in repairs:
        old = [f for f in step.flags if f.startswith(f"'{r.wrong}' is not a parameter of")]
        if r.label:
            step.flags = [f for f in step.flags if f not in old]
            step.flags.append(f"label corrected by a second look at {_mmss(a)} to {_mmss(b)}: '{r.wrong}' is '{r.label}' on {r.node} (seen: {r.evidence[:80]}); check it in the video")
        else:
            step.flags.append(f"a second look at {_mmss(a)} to {_mmss(b)} could not correct '{r.wrong}': {r.reason}")


def repair_labels(provider, sl: StepList, video_id: str, duration_s: float | None = None) -> list[Repair]:
    """The second look for every Houdini step with an unknown parameter label. Changes `sl` in place; returns every decision (corrected or not) for the report."""
    if sl.app != "houdini":
        return []
    from .youtube.metadata import canonical_url
    url = canonical_url(video_id)
    out: list[Repair] = []
    for st in sl.steps:
        out.extend(repair_step(provider, st, url, duration_s or sl.video_duration_s))
    return out
