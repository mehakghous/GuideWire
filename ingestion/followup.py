"""Follow-up questions during a tutorial: deterministic resolution against a Session. No model, no network.

`respond(session, text)` decides in this order:
  1. which follow-up INTENT the message is (ordered regexes; the first match wins; every decision is written to `reasons`);
  2. whether the message is really a NEW standalone request (it names a different Blender topic and has no "this / that / step" reference):
     then it goes to the ordinary router and the session is left untouched;
  3. whether any context applies (an abandoned or missing tutorial gets a question back, never a guess);
  4. otherwise an answer built from the CURRENT step: its goal, evidence, catalog operation (explanation, shortcuts, menu paths, prerequisites)
     and, if supplied, the observed application state.
Nothing here marks a step done because it was asked about. Only an explicit statement ("I did that", "skip this") or a stored user action
changes status. Where the sources do not say (why a tutorial author did something; where a button is), the answer says so.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from shared.answer import AnswerBundle, Explanation, RequestSummary, SourceRef
from shared.step_record import Step

from .catalog import BY_ID, Operation, match_aliases, version_status
from .kb.index import stem
from .knowledge import check_prereq, how_to_steps
from .router import route
from .session import Session, human_state

_I = re.IGNORECASE
INTENT_PATTERNS: list[tuple[str, re.Pattern]] = [(n, re.compile(p, _I)) for n, p in [
    ("done_stmt", r"^(?:ok(?:ay)?[, ]+|yes[, ]+)?(?:i(?:'ve| have)?\s+)?(?:already\s+)?(?:did|done|finished|completed)(?:\s+(?:that|it|this|this step|the step))?\W*$"),
    ("already_done_q", r"^(?:what|and) if i(?: have)?(?: already)? (?:completed|did|finished|done)"),
    ("skip", r"\bskip\b"),
    ("resume", r"^(?:resume|return to|go back to) (?:the |my )?(?:tutorial|procedure)\W*$"),
    ("timestamp", r"\b(?:at|around|near|@)\s*(\d{1,2}:\d{2}(?::\d{2})?)\b"),
    ("task_change", r"(?=.*\b(?:actually|instead|rather|never ?mind)\b)(?=.*\b(?:want to|let'?s|i'?d like|learn|make|build)\b)"),
    ("goto", r"\bgo(?:ing)? back\b|\bjump to\b|\brevisit\b|\bgo to step\b|\bback to step\b"),
    ("nothing_happens", r"nothing happens|does ?n[o']t do anything|does nothing|no effect|(?:shortcut|key|hotkey).{0,30}(?:not working|doesn'?t work|isn'?t working)"),
    ("didnt_work", r"^(?:that|it|this)?\s*(?:didn'?t|did not|doesn'?t|does not|isn'?t|won'?t)\s+work\W*$|^(?:that|it) failed"),
    ("result_differs", r"(?:looks?|is|seems?|came out)\s+(?:different|wrong|off)\b|not what (?:i|the tutorial)|different (?:result|from)"),
    ("mistake", r"made a mistake|messed up|screwed up|oops|recover|\bbroke\b|accidentally"),
    ("missing_option", r"(?:don'?t|do not|can'?t|cannot)\s+(?:see|find)|not (?:showing|there|available|visible)|\bmissing\b|greyed|grayed"),
    ("explain_prev", r"(?:previous|last|prior|earlier) step|go over (?:that|it) again|repeat (?:that|the last)"),
    ("explain_rest", r"\brest\b|remaining steps|everything else"),
    ("next", r"what (?:should|do|can) i do next|what'?s next|what is next|next step|then what"),
    ("continue", r"^(?:continue|go on|go ahead|carry on|proceed)\W*$"),
    ("other_one", r"\bthe other (?:one|option|button|step)\b|\bother one\b"),
    ("version", r"\b(?:my|this|the)\s+(?:blender\s+)?version\b|will (?:this|it) work"),
    ("shortcut_alt", r"shortcut|hotkey|key combo|keyboard"),
    ("other_way", r"another way|other way|different way|alternative|other method|another method"),
    ("where", r"where (?:can|do|would|is|are)\b|which (?:menu|button|panel|tab)|how do i find"),
    ("what_does", r"what does (?:this|that|it|the \w+)\b.*\bdo|what is (?:this|that) (?:option|button|setting|tool)|what do(?:es)? (?:this|that)"),
    ("why", r"^why\b|\bwhy (?:are|do|is|should|did)\b|\b(?:reason|point|purpose) (?:for|of)\b|explain (?:this|the current) step|^explain\b"),
]]
NAVIGATION = frozenset({"goto", "skip", "done_stmt", "timestamp", "resume"})   # these point INTO the tutorial by definition
_ANAPHORA = re.compile(r"\b(this|that|these|those|it|here|previous|last|step|option|button|again|other)\b", _I)
_STOP = {"go", "back", "to", "the", "part", "step", "section", "bit", "that", "this", "where", "jump", "revisit", "a", "an"}


@dataclass
class Reply:
    bundle: AnswerBundle
    intent: str
    route: str          # "session" | "standalone" | "clarify"


def classify_followup(text: str) -> str | None:
    t = " ".join(text.strip().split())
    for name, pat in INTENT_PATTERNS:
        if pat.search(t):
            return name
    return None


def _ops_of(step: Step | None) -> list[Operation]:
    out = []
    for r in (step.source_refs if step else []):
        m = re.match(r"catalog:([\w.]+)@", r)
        if m and m.group(1) in BY_ID:
            out.append(BY_ID[m.group(1)])
    return out


def _names_other_topic(text: str, session: "Session") -> bool:
    """A new request names a Blender topic that NO step of the loaded procedure is about, and does not point back with this/that/step.
    A topic that matches some step ("go back to the undo part") is a reference into the tutorial, not a new request."""
    if _ANAPHORA.search(text):
        return False
    in_tutorial = {o.id for s in (session.steps.steps if session.steps else []) for o in _ops_of(s)}
    return any(o.id not in in_tutorial for o, _ in match_aliases(text))


def _mk(session: Session, text: str, intent: str, step: Step | None, *, kind: str = "concept", explanations: list[Explanation] | None = None,
        sources: list[SourceRef] | None = None, questions: list[str] | None = None, clarification: str | None = None,
        unmet: list[str] | None = None, caveats: list[str] | None = None, steps=None, why: str = "", routelabel: str = "session") -> Reply:
    b = AnswerBundle(
        kind=kind, route="session" if routelabel == "session" else "clarify", explanations=explanations or [], sources=sources or [],
        questions=questions or [], clarification=clarification, unmet_prerequisites=unmet or [], caveats=caveats or [], steps=steps,
        trust="catalog" if sources else "none", reasons=[f"follow-up intent: {intent}", *([why] if why else [])],
        needs=["user_state"] if kind == "needs_state" else [],
        request=RequestSummary(goal=text, task_type="follow_up", context="session", refers_to_step=step.id if step else None,
                               constraints={"version": session.version}))
    session.note(text, intent, routelabel, step.id if step else None)
    return Reply(b, intent, routelabel)


def _where_said(step: Step) -> str:
    bits = []
    if step.video_start_s is not None:
        bits.append(f"at {int(step.video_start_s // 60)}:{int(step.video_start_s % 60):02d}")
    if step.evidence and not step.evidence[0].startswith("catalog entry"):
        bits.append(f"the source says: \"{step.evidence[0][:160]}\"")
    return " ".join(bits)


def _describe(step: Step) -> str:
    keys = [" + ".join(a.keys) for a in step.actions if a.keys]
    ui = [a.ui_element for a in step.actions if a.ui_element]
    extra = (f" (keys: {', '.join(keys)})" if keys else "") + (f" (UI: {', '.join(ui)})" if ui else "")
    return f"{step.goal}{extra}"


def _prereq_report(op: Operation | None, observed: dict | None, version_ok: bool = True) -> tuple[list[str], list[str], list[str]]:
    """(unmet, unknown, met) prerequisite texts for an operation against the observed state. Documentation never counts as observation."""
    unmet, unknown, met = [], [], []
    for p in (op.prerequisites if op else ()):
        st = check_prereq(p, observed)
        (unmet if st == "unmet" else met if st == "met" else unknown).append(p.text)
    return unmet, unknown, met


def _state_note(observed: dict | None, expected_step: Step | None = None) -> str:
    if not observed:
        return "I have no view of your Blender state."
    return "Blender reports: " + ", ".join(f"{k}={v}" for k, v in observed.items()) + "."


def respond(session: Session, text: str, *, kb=None, tutorials: list[dict] | None = None) -> Reply:
    intent = classify_followup(text) or "standalone"
    step = session.current_step if session.steps else None

    def standalone(why: str) -> Reply:
        b = route(text, version=session.version, observed=session.observed, kb=kb, tutorials=tutorials)
        b.reasons.append(why)
        b.request = RequestSummary(goal=text, task_type="unclear", context="standalone", constraints={"version": session.version})
        session.note(text, intent, "standalone", None)
        return Reply(b, intent, "standalone")

    if intent == "task_change":
        session.pause()
        r = standalone("the user changed task: the previous tutorial is paused, not deleted")
        r.bundle.caveats.append(f"'{(session.tutorial or {}).get('title') or 'the tutorial'}' is paused; say 'resume the tutorial' to go back.")
        return r
    if intent == "resume" and session.steps:
        session.resume()
        return _mk(session, text, "resume", session.current_step, explanations=[Explanation(text=f"Resuming at: {_describe(session.current_step)}", applies_to_steps=[session.current])])
    if intent == "standalone":
        return standalone("no follow-up wording: treated as a new request")
    if session.steps is None:
        return standalone("no tutorial is loaded: follow-up wording routed as a standalone request")
    if not session.active:
        title = (session.tutorial or {}).get("title") or "an earlier tutorial"
        return _mk(session, text, intent, None, kind="clarification", routelabel="clarify",
                   clarification=f"I paused '{title}' when you changed task. Do you want to resume it, or is this about something new?",
                   why="session inactive: the message was not attached to the paused tutorial")
    if intent not in NAVIGATION and _names_other_topic(text, session):
        return standalone("the message names a different Blender topic and does not refer to the current step")

    ops = _ops_of(step)
    op = ops[0] if ops else None
    srcs = list(op.sources) if op else []
    sid = [step.id]

    def ex(t: str, step_ids=None) -> Explanation:
        return Explanation(text=t, applies_to_steps=step_ids or sid, sources=list(srcs), provenance="catalog_template" if op else "transcript_rules")

    # ---------- state-changing statements (only the user's explicit words)
    if intent == "done_stmt":
        v = session.verify(step)
        done_id = step.id
        session.complete(step.id, "user")
        cav = []
        if v is not None and v.outcome == "unmet":
            cav.append(f"You said step {done_id} is done, but Blender reports it is not: {', '.join(v.unmet)} does not hold. Marked done on your word; the mismatch is recorded.")
        nxt = session.current_step
        return _mk(session, text, intent, nxt, caveats=cav, explanations=[Explanation(text=f"Marked {done_id} done (your report). Next: {_describe(nxt)}", applies_to_steps=[nxt.id])] if nxt else [])
    if intent == "skip":
        sk = step.id
        session.skip()
        return _mk(session, text, intent, session.current_step, explanations=[Explanation(text=f"Skipped {sk}. Later steps may depend on it: " + (", ".join(s.id for s in session.steps.steps if sk in s.depends_on) or "none recorded") + ".", applies_to_steps=[sk])])
    if intent == "goto":
        m = re.search(r"step\s+(\d+)", text, _I)
        target = None
        if m:
            cand = f"s{int(m.group(1)):02d}"
            target = session.step(cand)
        else:
            words = {stem(w) for w in re.findall(r"[a-z]+", text.lower()) if w not in _STOP}
            hits = [s for s in session.steps.steps if words & {stem(w) for w in re.findall(r"[a-z]+", s.goal.lower())}]
            if len(hits) > 1:
                return _mk(session, text, intent, step, kind="clarification", routelabel="clarify",
                           clarification="Which step do you mean? " + "; ".join(f"{s.id}: {s.goal}" for s in hits[:4]))
            target = hits[0] if hits else (session.previous_step() if not words else None)
        if target is None:
            return _mk(session, text, intent, step, kind="clarification", clarification="I could not find that step. Say a step number (1 to "
                       f"{len(session.steps.steps)}) or a word from its description.")
        session.goto(target.id)
        return _mk(session, text, intent, target, explanations=[ex(f"Back at {target.id} ({session.status[target.id]}): {_describe(target)}", [target.id])])
    if intent == "didnt_work":
        session.mark(step.id, "failed", "user")
        unmet, unknown, _ = _prereq_report(op, session.observed)
        q = ["What happened instead (an error message, nothing, or something different)?", "Which mode are you in, and what is selected?"]
        return _mk(session, text, intent, step, kind="clarification", questions=q, clarification=q[0], unmet=unmet,
                   explanations=[ex(f"Marked {step.id} as failed (your report). It expects: " + (", ".join(human_state(p.kind, p.target) for p in step.expected_state) or "no checkable result") + ".")])
    if intent == "timestamp":
        m = INTENT_PATTERNS[[n for n, _ in INTENT_PATTERNS].index("timestamp")][1].search(text)
        parts = [int(x) for x in m.group(1).split(":")]
        sec = float(parts[0] * 3600 + parts[1] * 60 + parts[2]) if len(parts) == 3 else float(parts[0] * 60 + parts[1])
        dur = session.steps.video_duration_s
        timed = [s for s in session.steps.steps if s.video_start_s is not None]
        if not timed:
            return _mk(session, text, intent, step, kind="clarification", clarification="This procedure has no timestamps (it did not come from a video). Which step number do you mean?")
        if dur is not None and sec > dur:
            return _mk(session, text, intent, step, kind="clarification", clarification=f"That is past the end of the video ({dur:g} s long). What time did you mean?")
        hit = next((s for s in timed if s.video_start_s <= sec <= (s.video_end_s or s.video_start_s)), None)
        if hit is None:
            before = [s for s in timed if s.video_start_s <= sec]
            near = before[-1] if before else timed[0]
            return _mk(session, text, intent, near, kind="clarification", clarification=f"No step I extracted covers {int(sec // 60)}:{int(sec % 60):02d}. The nearest is {near.id} ({_describe(near)}). The video may show something there that its narration does not say.", explanations=[ex(_where_said(near), [near.id])])
        o = (_ops_of(hit) or [None])[0]
        return _mk(session, text, intent, hit, sources=list(o.sources) if o else [], explanations=[Explanation(
            text=f"{hit.id}: {_describe(hit)} ({_where_said(hit)}). " + (o.explanation if o else ""), applies_to_steps=[hit.id],
            provenance="transcript_rules", start_s=hit.video_start_s, end_s=hit.video_end_s)], caveats=["Narrated only: what was done on screen at that moment is not known from the captions."])

    # ---------- questions about the current step
    if intent in ("why", "what_does"):
        parts = [f"{step.id}: {_describe(step)}."]
        if op:
            parts.append(op.explanation)
        else:
            parts.append("The source does not say why this step is needed, and it is not an operation I can look up, so I will not guess.")
        for d in step.depends_on:
            ds = session.step(d)
            parts.append(f"It depends on {d} ({ds.goal}), which put Blender in the state this step needs." if ds else "")
        w = _where_said(step)
        if w:
            parts.append(w)
        return _mk(session, text, intent, step, sources=srcs, explanations=[ex(" ".join(p for p in parts if p))])
    if intent == "where":
        parts = []
        if op and op.menu_paths:
            parts.append("Menu: " + "; ".join(op.menu_paths) + ".")
        ui = [a.ui_element for a in step.actions if a.ui_element]
        if ui:
            parts.append("The step names: " + "; ".join(ui) + ".")
        if op and op.shortcuts:
            parts.append("Shortcut: " + ", ".join(s.title() for s in op.shortcuts) + ".")
        if not parts:
            return _mk(session, text, intent, step, kind="needs_state", questions=["Which Blender version are you using, and what does your screen show?"],
                       explanations=[ex("My sources do not give a location for this step, so I will not guess one.")])
        return _mk(session, text, intent, step, sources=srcs, explanations=[ex(" ".join(parts))], caveats=["Menu names are from the current manual; check them against your version."])
    if intent == "shortcut_alt":
        if op and op.shortcuts:
            used = {k.lower() for a in step.actions for k in a.keys}
            same = all(any(w in used for w in s.split("+")) for s in op.shortcuts[:1])
            t = (f"This step already uses {', '.join(s.title() for s in op.shortcuts)}." if same else f"Shortcut: {', '.join(s.title() for s in op.shortcuts)}.")
            if op.menu_paths:
                t += " Without the keyboard: " + "; ".join(op.menu_paths) + "."
            return _mk(session, text, intent, step, sources=srcs, explanations=[ex(t)])
        return _mk(session, text, intent, step, explanations=[ex("No keyboard shortcut is documented for this step in my sources.")])
    if intent == "other_way":
        ways = list(dict.fromkeys(step.alternatives + ([f"menu: {m}" for m in op.menu_paths] if op else []) + ([f"shortcut: {s.title()}" for s in op.shortcuts] if op else [])))
        t = "Documented ways: " + "; ".join(ways) + "." if ways else "No alternative is documented for this step in my sources; I will not invent one."
        return _mk(session, text, intent, step, sources=srcs, explanations=[ex(t)])
    if intent == "other_one":
        opts = "; ".join(f"{s.id}: {s.goal}" for s in session.steps.steps if s.id != step.id and session.status[s.id] != "done")[:300]
        return _mk(session, text, intent, step, kind="clarification", routelabel="clarify",
                   clarification=f"Which one do you mean? I am on {step.id} ({step.goal}). Other steps: {opts or 'none left'}.", why="'the other one' has no referent in the session")
    if intent in ("missing_option", "nothing_happens"):
        unmet, unknown, _ = _prereq_report(op, session.observed)
        v = session.verify(step)
        parts = []
        if unmet:
            parts.append("This step only works when: " + " ".join(unmet) + f" {_state_note(session.observed)}")
        elif op and op.prerequisites:
            parts.append("This step needs: " + " ".join(p.text for p in op.prerequisites) + (" " + _state_note(session.observed) if session.observed else " I cannot tell whether that holds."))
        else:
            parts.append("I do not have a documented prerequisite for this step.")
        if op and op.menu_paths:
            parts.append("It is found in: " + "; ".join(op.menu_paths) + ".")
        q = ["Which Blender version are you using?"] + ([] if session.observed else ["Which mode are you in, and what is selected?"])
        return _mk(session, text, intent, step, kind="needs_state", sources=srcs, unmet=unmet, questions=q, clarification=q[0], explanations=[ex(" ".join(parts))],
                   caveats=["Whether this works depends on your current mode, selection and version; documentation cannot establish that."])
    if intent == "already_done_q":
        v = session.verify(step)
        exp = ", ".join(human_state(p.kind, p.target) for p in step.expected_state)
        check = f"it should leave Blender with {exp}" if exp else "it has no result I can check, so only you can confirm it"
        return _mk(session, text, intent, step, explanations=[ex(f"If you have already done {step.id}, check the result: {check}. Tell me 'I did that' and I will mark it done; I have not marked anything yet.")],
                   caveats=([f"Blender currently reports {', '.join(v.unmet)} as not holding."] if v is not None and v.outcome == "unmet" else []))
    if intent == "mistake":
        und = BY_ID["history.undo"]
        steps, _, cav = how_to_steps(und, session.version, session.observed)
        from .knowledge import finish
        sl = finish(steps, "catalog", version=session.version)
        return _mk(session, text, intent, step, kind="procedure", steps=sl, sources=list(und.sources),
                   explanations=[Explanation(text=f"Press Ctrl+Z (Edit > Undo) to undo the mistake; Edit > Undo History lets you jump back several actions. Then repeat {step.id}: {step.goal}.",
                                             applies_to_steps=sid, sources=list(und.sources))], caveats=cav[:2])
    if intent == "result_differs":
        last = next((s for s in reversed(session.steps.steps) if session.status[s.id] == "done"), step)
        v = session.verify(last)
        if v is None:
            q = ["What does your screen show (mode, what is selected, what changed)?"]
            return _mk(session, text, intent, last, kind="needs_state", questions=q, clarification=q[0],
                       explanations=[ex("After " + last.id + " Blender should show: " + (", ".join(human_state(p.kind, p.target) for p in last.expected_state) or "no checkable result") + ".", [last.id])])
        if v.outcome == "unmet":
            exp = ", ".join(human_state(p.kind, p.target) for p in last.expected_state)
            return _mk(session, text, intent, last, kind="needs_state", sources=srcs, unmet=v.unmet, questions=["Did you skip or undo a step after " + last.id + "?"],
                       explanations=[ex(f"After {last.id} Blender should show {exp}, but it reports: {_state_note(session.observed)} Not holding: {', '.join(v.unmet)}.", [last.id])])
        if v.outcome == "met":
            msg = f"Blender's reported state matches what {last.id} expects, so the difference is elsewhere."
        else:
            msg = f"{last.id} has no result I can check against Blender's state, so I cannot tell what differs from here."
        return _mk(session, text, intent, last, kind="needs_state", questions=["What exactly looks different?"], explanations=[ex(msg, [last.id])])
    if intent == "explain_prev":
        prev = session.previous_step()
        if prev is None:
            return _mk(session, text, intent, step, explanations=[ex("There is no earlier step: you are on the first one.")])
        po = (_ops_of(prev) or [None])[0]
        return _mk(session, text, intent, prev, sources=list(po.sources) if po else [], explanations=[Explanation(
            text=f"{prev.id}: {_describe(prev)}. " + (po.explanation if po else "") + (" " + _where_said(prev) if _where_said(prev) else ""), applies_to_steps=[prev.id])])
    if intent == "explain_rest":
        rest = session.pending_from_current()
        return _mk(session, text, intent, step, explanations=[Explanation(text=f"{s.id}: {_describe(s)}", applies_to_steps=[s.id]) for s in rest] or
                   [ex("Nothing is left: every step is done or skipped.")], sources=srcs,
                   why=f"{len(rest)} step(s) still pending; done and skipped steps were left out")
    if intent in ("next", "continue"):
        unmet, _, _ = _prereq_report(op, session.observed)
        done = session.status[step.id] == "done"
        t = f"{'Next' if done else 'You are on'} {step.id}: {_describe(step)}."
        if not done:
            t += " Finish it first; I have not marked it done."
        later = [s for s in session.steps.steps[session.index(step.id) + 1:] if session.status[s.id] == "pending"][:1]
        if later:
            t += f" After that: {later[0].goal}."
        return _mk(session, text, intent, step, sources=srcs, unmet=unmet, explanations=[ex(t)],
                   caveats=([f"Prerequisite not met in your Blender: {' '.join(unmet)}"] if unmet else []))
    if intent == "version":
        hint = (session.tutorial or {}).get("version_hint")
        parts = [f"You told me you use Blender {session.version}." if session.version else "I do not know your Blender version yet; which one is it?"]
        if hint and re.match(r"^\d+\.\d+", hint):
            parts.append(f"The tutorial was recorded for Blender {hint}.")
            if session.version and hint.split(".")[0] != session.version.split(".")[0]:
                parts.append("The major versions differ, so menu names, shortcuts and defaults may differ; check each step.")
        if op:
            st, note = version_status(op, session.version)
            parts.append(note)
        return _mk(session, text, intent, step, sources=srcs, explanations=[ex(" ".join(parts))], questions=[] if session.version else ["Which Blender version are you using?"])
    return standalone("follow-up pattern matched but no handler applied")
