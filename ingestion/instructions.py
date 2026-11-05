"""Turn what a step already knows into lines a learner can act on: menu paths to open, settings to enter, what to look for afterwards.

The first live Maya run showed the problem: the model had put "Constrain > Parent", "Maintain offset", "Attribute Name: FK_IK_Switch", "Minimum: 0" into the
short `evidence` fragments and `visual_evidence`, left `actions` empty, and the learner-facing text was only the goal ("Parent constrain skin leg joints ...").
Nothing was invented; it was never put anywhere a person would read it.

`compose_instructions` is deterministic and conservative:
  * a menu path, a "Setting: value" pair or a "set X to Y" phrase is turned into an Action AND a how_to line only when those exact words are in the step's own evidence;
  * the sentences of `visual_evidence` are kept, word for word, as "shown" lines (they are what the model says it saw, not a human check);
  * `check` lines come from the step's expected state and from the feature catalog's acceptance criteria and are labelled `catalog`: guidance, not something the video showed;
  * a step that already has how_to lines (the model wrote them, prompt v5) is left alone;
  * nothing is added when there is nothing to add.
"""
from __future__ import annotations

import re

from shared.step_record import Action, HowTo, Step, StepList

from .features import LEARNER_CHECKS

_MENU = re.compile(r"^\s*([A-Za-z][\w ]*?(?:\s*(?:>|->|→)\s*[A-Za-z][\w .]*?)+)\s*(?:\.\.\.|…)?\s*$")
_PAIR = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 /_-]{1,40}?)\s*:\s*(\S.{0,60}?)\s*$")
_SET_VERB = re.compile(r"\b(?:setting|set|sets|changing|change)\b")
_NAME_TO_VALUE = re.compile(r"([A-Z][A-Za-z0-9 ]{1,30}?)\s+to\s+([\w.\-]+)")
_ENABLED = re.compile(r"\bwith\s+([A-Za-z][A-Za-z0-9 ]{1,30}?)\s+(enabled|checked|on|turned on|ticked)\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _menu_path(fragment: str) -> str | None:
    m = _MENU.match(fragment)
    if not m:
        return None
    return " > ".join(p.strip(" .") for p in re.split(r"\s*(?:>|->|→)\s*", m.group(1)) if p.strip(" ."))


def _derive(step: Step) -> tuple[list[Action], list[HowTo]]:
    actions: list[Action] = []
    lines: list[HowTo] = []
    seen: set[str] = set()

    def add(action: Action, text: str, evidence: str) -> None:
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        actions.append(action)
        lines.append(HowTo(text=text, support="shown", evidence=evidence))

    for frag in step.evidence:
        path = _menu_path(frag)
        if path:
            add(Action(verb="open_menu", ui_element=path), f"Open {path}.", frag)
            continue
        m = _PAIR.match(frag)
        if m:
            add(Action(verb="set_value", ui_element=m.group(1).strip(), value=m.group(2).strip()), f"Set {m.group(1).strip()} to {m.group(2).strip()}.", frag)
    vis = step.visual_evidence or ""
    for sent in _SENTENCE.split(vis.strip()):
        verb = _SET_VERB.search(sent)
        for m in (_NAME_TO_VALUE.finditer(sent, verb.end()) if verb else []):          # "setting Primary Axis to X, Secondary Axis to Y": only after a setting verb
            name, value = m.group(1).strip(), m.group(2).rstrip(".,")
            add(Action(verb="set_value", ui_element=name, value=value), f"Set {name} to {value}.", m.group(0).strip(" ,"))
    for m in _ENABLED.finditer(vis):
        add(Action(verb="set_value", ui_element=m.group(1).strip(), value="on"), f"Turn {m.group(1).strip()} on.", m.group(0))
    for sent in _SENTENCE.split(vis.strip()):
        if len(sent) >= 12:
            lines.append(HowTo(text=f"In the video: {sent.strip()}", support="shown", evidence=sent.strip()))
    return actions, lines


def _cite(kb, st) -> str:
    """'official: Maya: Orient Joint Options | community: ...' : the tier and title of every source behind a statement, so a learner can see how far to trust it."""
    return " | ".join(f"{st.tier}: {kb.sources[s]['title']}" for s in st.sources) or f"{st.tier}: no source"


def _checks(step: Step, app: str) -> list[HowTo]:
    from .rigging_knowledge import load as knowledge
    kb = knowledge()
    out: list[HowTo] = []
    for p in step.expected_state:
        if p.kind == "node_exists":
            out.append(HowTo(text=f"Check that a {p.target} now exists (Outliner or Node Editor).", support="catalog", evidence=f"expected state: node_exists={p.target}"))
        elif p.kind == "mode":
            out.append(HowTo(text=f"Check that you are in {p.target.replace('_', ' ').title()} mode.", support="catalog", evidence=f"expected state: mode={p.target}"))
    researched = [(e, v) for e in kb.for_feature(step.feature_id, app) for v in e.verify] if step.feature_id else []
    for e, v in researched[:2]:                                          # app-specific and sourced (knowledge/rigging_knowledge.json) beats the generic line
        out.append(HowTo(text=v.text, support="catalog", evidence=_cite(kb, v)))
    if not researched and step.feature_id in LEARNER_CHECKS:
        out.append(HowTo(text=f"Check that {LEARNER_CHECKS[step.feature_id]}.", support="catalog", evidence=f"catalog guidance for {step.feature_id}; the video did not necessarily show this"))
    return out


def _from_knowledge(step: Step, app: str) -> None:
    """Common mistakes (with their tier and source), what to have done first, and a note where sources disagree, for the feature this step teaches."""
    from .rigging_knowledge import load as knowledge
    kb = knowledge()
    for e in kb.for_feature(step.feature_id, app) if step.feature_id else []:
        for m in e.mistakes:
            line = f"{m.text} ({_cite(kb, m)})"
            if line not in step.common_mistakes:
                step.common_mistakes.append(line)
        for pre in e.prerequisites:
            line = f"Before this: {pre}"
            if line not in step.assumptions:
                step.assumptions.append(line)
        for c in e.conflicts:
            line = f"sources disagree: {c['text']}"
            if line not in step.flags:
                step.flags.append(line)


def compose_instructions(sl: StepList) -> int:
    """Fill `result`, `how_to` and `check` where a step has none; returns how many steps gained something. Idempotent."""
    changed = 0
    for st in sl.steps:
        before = (st.result, len(st.how_to), len(st.check), len(st.actions))
        if st.result is None:
            st.result = st.goal
        if not st.how_to:
            actions, lines = _derive(st)
            st.how_to = lines
            known = {(a.verb, a.ui_element, a.value) for a in st.actions}
            st.actions += [a for a in actions if (a.verb, a.ui_element, a.value) not in known]
        if not st.check:
            st.check = _checks(st, sl.app)
        _from_knowledge(st, sl.app)
        changed += (st.result, len(st.how_to), len(st.check), len(st.actions)) != before and (len(st.how_to) + len(st.check) > before[1] + before[2])
    return changed


# ---------------------------------------------------------------------------------------------------------------- spoken instructions (transcript route)
_GO_TO = re.compile(r"\bgo to (?:the )?([a-z]+)(?: menu)?(?: and| then|,)? (?:click |choose |select |hit |pick |press )?(?:on )?(?:the )?((?:[a-z]+ ?){1,6})")
_SPOKEN_SET = re.compile(r"\b(?:set|change|put)\s+(?:the\s+)?([a-z][a-z ]{2,30}?)\s+to\s+([a-z0-9][\w.\-]*)")
_SPOKEN_NAME = re.compile(r"\b(?:name it|call it|rename (?:it|them) to)\s+([\w\-]+)")


def speech_details(text: str, app: str) -> tuple[list[Action], list[HowTo]]:
    """What the speaker SAYS to open or set, when the words are names this application's profile knows ("go to skeleton and orient joint", "set the primary axis to x").
    Conservative: both the menu and the item must be known names, so chatter never becomes a menu path. Lines are labelled `said`, never `shown`."""
    from .profiles import get_profile, norm
    known = get_profile(app).ui_names
    low = " ".join(text.lower().split())
    actions: list[Action] = []
    lines: list[HowTo] = []
    for m in _GO_TO.finditer(low):
        menu, words = m.group(1), m.group(2).split()
        item = next((" ".join(words[:k]) for k in range(min(4, len(words)), 0, -1) if norm(" ".join(words[:k])) in known), None)      # the longest known name that starts here
        if norm(menu) in known and item:
            path = f"{menu.title()} > {item.title()}"
            actions.append(Action(verb="open_menu", ui_element=path))
            lines.append(HowTo(text=f"Open {path}.", support="said", evidence=m.group(0)))
    for m in _SPOKEN_SET.finditer(low):
        name, value = m.group(1).strip(), m.group(2)
        if norm(name) in known:
            actions.append(Action(verb="set_value", ui_element=name.title(), value=value.upper() if len(value) == 1 else value))
            lines.append(HowTo(text=f"Set {name.title()} to {value.upper() if len(value) == 1 else value}.", support="said", evidence=m.group(0)))
    for m in _SPOKEN_NAME.finditer(low):
        actions.append(Action(verb="set_value", ui_element="Name", value=m.group(1)))
        lines.append(HowTo(text=f"Name it {m.group(1)}.", support="said", evidence=m.group(0)))
    return actions, lines
