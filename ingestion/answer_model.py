"""Model-backed question answering, grounded on what GuideWire already knows.

The rule-based layer (router.py, followup.py) answers only what its catalog and patterns cover; for everything else it used to deflect. This module sends the question to a model together
with the best matching context we hold, and asks for an honest answer:

  * the rigging knowledge base: the few entries (of 45) that best match the question and the application (menu paths, options, outline, facts, mistakes, symptom-to-fix, with their source tier);
  * for Blender, the best passages of the local manual index;
  * the loaded tutorial: its steps (id, time, goal, how-to lines), the current step and what the learner has marked done;
  * the last few things the learner said.

Rules the model is given (system prompt below): ground in the context first and say which part; general knowledge is allowed but must be labelled as such and never used for an exact
menu path or value it is not sure of; never claim the tutorial said something its steps do not say; say "not in the tutorial" and "I am not sure" when true; read through typos and wrong
terms; ask one short question only when the answer would differ. The model never changes the session: steps are marked done, skipped or jumped only by the rule-based follow-up logic.

`ModelAnswerer` is the object the service and the gateway call. Every call goes through whatever provider it is given, so the cost guard (ingestion/budget.py) applies: cache, ceilings, log.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from shared.answer import AnswerBundle, Explanation, SourceRef
from shared.step_record import HowTo, Step, StepList

from .rigging_knowledge import Entry, Knowledge, _tokens
from .rigging_knowledge import load as load_knowledge
from .session import Session

SYSTEM = """You are the answering assistant of GuideWire, a tutor that helps learners follow Blender, Maya and Houdini rigging tutorials. You answer one learner question at a time.

CONTEXT you are given, in order: ENTRIES from GuideWire's own knowledge base (each with an id and a trust tier), MANUAL passages (Blender only), the TUTORIAL the learner is following (its steps, with ids and times), and the learner's recent messages.

How to answer:
1. Read the question as a beginner wrote it. Spelling mistakes, grammar errors, missing words and wrong terms are normal: work out what they meant, and if they used a wrong term, say the right one gently in the answer.
2. Use the CONTEXT first. When a fact or menu path comes from an ENTRY, MANUAL passage or TUTORIAL step, list its id in source_ids or step_ids. Questions about "he", "the video", "this step" or a time are about the TUTORIAL: answer from its steps only.
3. You may add general knowledge of the application when the context is missing or thin. Then set grounding to "general_knowledge" (or "mixed"), say in one short phrase that this part is not from GuideWire's sources, and keep to what you are sure of. Never invent an exact menu path, shortcut, node or option name, or number. If you are not sure of one, say so and say where to look (the menu set, the Tab menu, the manual page).
4. NEVER say the tutorial or the video said, did or explained something that its steps do not show. If the question asks about something the steps do not contain (a setting, a version, a reason, a later part), say that it is not in the tutorial, set in_tutorial to "no", and then you may add what is generally true, labelled as such.
5. Mention the application version when the tutorial's version is given and differs from what the learner says they use.
6. If the question is too vague to answer well (for example "all my joints are at the origin" with no hint where), ask ONE short clarifying question, set confidence to "low", and give nothing that you do not know.
7. Be short and concrete: two to six sentences, or a short numbered list for steps. Plain words. Name the menu path or key exactly as the context gives it.
8. You cannot see the learner's screen and you cannot change their progress. Do not say you marked, skipped or completed anything.
9. Set wants_steps to true ONLY when the learner explicitly asks for steps they can follow ("give me the steps", "walk me through", "step by step", "a plan", "what do i do, in order"), however it is worded. For an ordinary question or an explanation set it to false. When it is true, list in source_ids the ENTRIES whose steps the learner needs.
10. Copy every menu path, tool name, node name and shortcut CHARACTER FOR CHARACTER from the ENTRIES or MANUAL passages. If none of them gives the exact name, name the tool in plain words and say where to look: never write a menu path from memory (a reply that said "Skin > Paint Weights" for "Skin > Paint Skin Weights Tool" misled a learner).
11. For a how-to question ("how do i make", "how do i add", "how do i attach") give the short ordered sequence: 3 to 6 numbered steps, one action each, using every outline step of the matching ENTRY and the menu or key it gives, and nothing the context does not support. Add one closing line saying what the learner should see when it worked, if an ENTRY gives a check.
12. For "which tutorial should i watch" or any request to recommend a video or course: you cannot see GuideWire's tutorial list, so do not recommend, name or describe any tutorial, channel or course from memory. Ask ONE short question about what the learner wants to make and their level, say that GuideWire can search tutorials for that goal, and leave answer empty with confidence "low".
13. Versions: never say or imply that steps, menus or tools written for one version of the application work the same in another version, unless an ENTRY or MANUAL passage says so. Say which version the tutorial shows (when the context gives it), that menus and names can differ in a newer or older version, and that the learner should check the release notes or the manual page for their version.
14. "Why" questions about the tutorial ("why did he change the solver", "why do we clear the parent"): if the tutorial steps do not give a reason, say plainly that the tutorial does not give a reason (in_tutorial "no"); you may then add a reason from general knowledge, clearly labelled as general knowledge and not as something the instructor said.

Return JSON only."""

SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "the reply to show the learner"},
        "grounding": {"type": "string", "enum": ["tutorial", "knowledge_base", "manual", "general_knowledge", "mixed", "none"]},
        "source_ids": {"type": "array", "items": {"type": "string"}, "description": "ids of ENTRIES or MANUAL passages used"},
        "step_ids": {"type": "array", "items": {"type": "string"}, "description": "ids of tutorial steps the answer is about"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "in_tutorial": {"type": "string", "enum": ["yes", "no", "not_applicable"]},
        "clarifying_question": {"type": ["string", "null"]},
        "wants_steps": {"type": "boolean", "description": "true only when the learner explicitly asks for steps, a plan or a walk-through to follow; false for an ordinary question"},
    },
    "required": ["answer", "grounding", "source_ids", "step_ids", "confidence", "in_tutorial", "clarifying_question", "wants_steps"],
}

# intents that CHANGE the session (done, skipped, jumped, resumed, next): the rule-based follow-up logic handles them, never the model
STATE_INTENTS = frozenset({"done_stmt", "already_done_q", "skip", "resume", "goto", "task_change", "next", "continue", "timestamp"})


def changes_progress(text: str, session: Session) -> bool:
    """True when `text` is a progress command (done, skip, back, next, a timestamp) AND a tutorial is loaded, so it must be handled by the rules. With NO tutorial loaded there is no progress to change:
    "i made the skeleton, whats next" is a question about what to do and goes to the model (found 2026-11-09: it got a fixed deflection in all three applications)."""
    from .followup import classify_followup
    return bool(session.steps and session.steps.steps) and classify_followup(text) in STATE_INTENTS


# ------------------------------------------------------------------------------------------------ retrieval
def _entry_score(e: Entry, q: frozenset[str]) -> float:
    """How much of the question this entry covers: its everyday phrases, symptom phrases, menu paths, id words and facts, best field wins."""
    best = 0.0
    fields: list[str] = list(e.phrases) + [e.id.split(".", 1)[-1].replace("_", " ")]
    fields += [p for t in e.troubleshooting for p in t["symptom_phrases"]]
    fields += [u["path"] for u in e.ui]
    for text in fields:
        w = _tokens(text)
        if w:
            best = max(best, len(q & w) / len(w))
    body = _tokens(" ".join([s.text for s in e.facts] + [s.text for s in e.outline][:6]))
    if q and body:
        best = max(best, 0.6 * len(q & body) / len(q))
    return best


def retrieve_entries(question: str, app: str, k: int = 4, kb: Knowledge | None = None) -> list[Entry]:
    kb = kb or load_knowledge()
    q = _tokens(question)
    scored = sorted(((_entry_score(e, q), e.id, e) for e in kb.entries if app in e.apps), key=lambda t: (-t[0], t[1]))
    return [e for s, _i, e in scored[:k] if s >= 0.34]


def render_entry(e: Entry, kb: Knowledge) -> str:
    lines = [f"ENTRY {e.id} (apps: {', '.join(e.apps)})"]
    for u in e.ui:
        opts = f" [options: {', '.join(u['options'])}]" if u.get("options") else ""
        lines.append(f"  menu/UI: {u['path']}{opts}")
    if e.prerequisites:
        lines.append("  needs first: " + "; ".join(e.prerequisites[:4]))
    for label, items in (("outline", e.outline[:6]), ("fact", e.facts[:5]), ("check", e.verify[:2]), ("common mistake", e.mistakes[:3])):
        for s in items:
            lines.append(f"  {label} [{s.tier}]: {s.text}")
    for t in e.troubleshooting[:3]:
        lines.append(f"  if \"{t['symptom_phrases'][0]}\": cause [{t['tier']}]: {t['cause']} | fix: {t['fix'] if isinstance(t['fix'], str) else '; '.join(t['fix'])}")
    srcs = sorted({x for grp in (e.outline, e.facts, e.verify, e.mistakes) for s in grp for x in s.sources})[:3]
    if srcs:
        lines.append("  sources: " + "; ".join(f"{kb.sources[x]['title']} ({kb.sources[x]['tier']})" for x in srcs))
    return "\n".join(lines)


def manual_passages(question: str, manual, limit: int = 3) -> list[tuple[str, str, str]]:
    """(id, title, passage) from the local Blender manual index; empty when there is no index or no good match."""
    if manual is None:
        return []
    try:
        res = manual.search(question, limit=limit)
    except Exception:                               # an index problem must never stop an answer
        return []
    out = []
    for i, h in enumerate(res.hits, start=1):
        if not res.sufficient and i > 1:
            break
        text = manual.passage(h, res.terms) or h.lead
        if text:
            out.append((f"MANUAL{i}", h.title, re.sub(r"\s+", " ", text)[:600]))
    return out


def tutorial_block(session: Session | None) -> str:
    if session is None or session.steps is None or not session.steps.steps:
        return "TUTORIAL: none is loaded. Questions about 'the video' or 'he' cannot be answered from a tutorial; say so."
    sl = session.steps
    head = f"TUTORIAL: \"{(session.tutorial or {}).get('title') or sl.title or 'loaded steps'}\" for {sl.app}"
    if sl.app_version_tutorial:
        head += f", version stated in the extraction: {sl.app_version_tutorial} (a model's reading, not confirmed)"
    head += f". {len(sl.steps)} steps. The learner is on {session.current or 'the first step'}."
    lines = [head]
    for s in sl.steps:
        t = ""
        if s.video_start_s is not None:
            m, sec = divmod(int(s.video_start_s), 60)
            t = f" [{m}:{sec:02d}]"
        how = "; ".join(h.text for h in s.how_to[:3])
        done = session.status.get(s.id)
        mark = f" ({done})" if done and done != "pending" else ""
        lines.append(f"  {s.id}{t}{mark}: {s.goal}" + (f" | how: {how[:170]}" if how else ""))
    return "\n".join(lines)


def build_prompt(question: str, app: str, session: Session | None, manual=None, kb: Knowledge | None = None) -> tuple[str, str, list[Entry]]:
    kb = kb or load_knowledge()
    q = question if not session or not session.turns else question + " " + " ".join(t.user for t in list(session.turns)[-2:])
    entries = retrieve_entries(q, app, kb=kb)
    parts = [f"APPLICATION: {app}"]
    parts.append("ENTRIES (GuideWire knowledge base):\n" + ("\n".join(render_entry(e, kb) for e in entries) if entries else "  none matched this question."))
    man = manual_passages(question, manual) if app == "blender" else []
    if man:
        parts.append("MANUAL passages (Blender documentation):\n" + "\n".join(f"  {i} - {title}: {text}" for i, title, text in man))
    parts.append(tutorial_block(session))
    if session is not None and session.turns:
        parts.append("RECENT LEARNER MESSAGES: " + " | ".join(t.user for t in list(session.turns)[-3:]))
    if session is not None and session.version:
        parts.append(f"The learner says their {app} version is {session.version}.")
    return SYSTEM, "\n\n".join(parts) + f"\n\nLEARNER QUESTION: {question}", entries


def session_from_tutorial(app: str, steps: list[dict], *, title: str | None = None, app_version: str | None = None, current: str | None = None, history: list[str] | None = None, video_url: str | None = None) -> Session:
    """A Session built from a brief step list a client sends (id, goal, start_s, how_to texts), for a stateless caller such as the gateway. The learner's progress is not carried
    over: `current` says which step they are on, nothing is marked done, and `history` is the last few things they said."""
    sess = Session(app=app)
    if steps:
        built = [Step(id=d["id"], order=i, goal=d["goal"], video_start_s=d.get("start_s"), how_to=[HowTo(text=t, support="said") for t in d.get("how_to", [])[:3]])
                 for i, d in enumerate(steps, start=1)]
        sess.load(StepList(source_type="youtube", app=app, title=title, app_version_tutorial=app_version, steps=built), tutorial={"id": "client", "title": title or "tutorial", "source_type": "youtube", **({"url": video_url} if video_url else {})})
        if current and sess.step(current) is not None:
            sess.goto(current)
    for h in (history or [])[-3:]:
        sess.note(h, "history", "client", None)
    return sess


@lru_cache(maxsize=1)
def default_manual():
    """The local Blender manual index (knowledge/kb.sqlite), or None when it is not built."""
    from .service import _default_kb
    return _default_kb()[0]


# ------------------------------------------------------------------------------------------------ the answerer
@dataclass
class ModelAnswerer:
    provider: object                      # anything with generate_json(system=, prompt=, schema=); wrap it in BudgetedProvider for the cost guard
    manual: object | None = None          # ingestion.kb.index.KnowledgeBase for Blender manual passages
    knowledge: Knowledge | None = None
    recheck_sweep: int = 0                # with recheck: how many OTHER parts of the video to look at when the first clip does not show it (each is one more call)
    recheck: bool = False                 # when the steps cannot answer a question about the tutorial, look at the video clip around the right moment (ingestion/video_recheck.py); one extra call

    def __call__(self, question: str, session: Session | None = None, app: str | None = None) -> AnswerBundle:
        kb = self.knowledge or load_knowledge()
        app = app or (session.app if session is not None else "blender")
        system, prompt, entries = build_prompt(question, app, session, self.manual, kb)
        raw = self.provider.generate_json(system=system, prompt=prompt, schema=SCHEMA)
        bundle = self.to_bundle(raw, entries, kb, session, question)
        if self.recheck and session is not None and session.steps is not None and raw.get("in_tutorial") == "no" and bundle.explanations:
            from .video_recheck import apply_recheck
            from .video_recheck import recheck as recheck_video
            got = recheck_video(self.provider, question, session, [s for s in raw.get("step_ids", []) if isinstance(s, str)], self.recheck_sweep)
            if got is not None:
                win, res = got
                bundle.explanations[0].text, note = apply_recheck(bundle.explanations[0].text, win, res)
                bundle.caveats.append(note)
                bundle.api_calls += 1
                bundle.reasons.append(f"video recheck of {win.start_s}-{win.end_s} s ({win.why}): found={res['found']}")
        return bundle

    @staticmethod
    def to_bundle(raw: dict, entries: list[Entry], kb: Knowledge, session: Session | None, question: str) -> AnswerBundle:
        answer = (raw.get("answer") or "").strip()
        ask = (raw.get("clarifying_question") or "").strip() or None
        conf = raw.get("confidence", "low")
        used = [i for i in raw.get("source_ids", []) if isinstance(i, str)]
        valid_steps = {s.id for s in session.steps.steps} if session is not None and session.steps else set()
        step_ids = [s for s in raw.get("step_ids", []) if s in valid_steps]
        refs = []
        for e in entries:
            if e.id in used:
                for sid in sorted({x for grp in (e.outline, e.facts, e.verify, e.mistakes) for s in grp for x in s.sources})[:2]:
                    src = kb.sources[sid]
                    refs.append(SourceRef(kind="manual" if src["tier"] == "official" else "forum", title=src["title"], url=src.get("url")))
        clarifying = bool(ask) and (conf == "low" or not answer)
        bundle = AnswerBundle(
            kind="clarification" if clarifying else "concept", route="clarify" if clarifying else "model",
            explanations=[] if clarifying else [Explanation(text=answer, applies_to_steps=step_ids, sources=refs, provenance="model")],
            clarification=ask if clarifying else None, sources=refs, api_calls=1,
            caveats=([] if raw.get("grounding") in ("tutorial", "knowledge_base", "manual") else ["Part of this answer is general knowledge, not from GuideWire's sources."]),
            reasons=[f"model answer: grounding={raw.get('grounding')}, confidence={conf}, in_tutorial={raw.get('in_tutorial')}, entries offered={[e.id for e in entries]}, used={used}"],
            trust="doc_passage" if raw.get("grounding") in ("knowledge_base", "manual", "tutorial") else "none",
        )
        if raw.get("wants_steps") is True and not clarifying and (session is None or session.steps is None):
            # the model judged (by meaning) that the learner wants steps and which topics they need; the STEPS come only from those knowledge-base entries, never from the model
            from .starter_plan import plan_from_entries
            chosen = [e for e in entries if e.id in used and (e.outline or e.ui)]
            sl = plan_from_entries(session.app if session is not None else "blender", chosen) if chosen else None
            if sl is not None:
                bundle.steps, bundle.kind, bundle.trust = sl, "procedure", "catalog"
                bundle.caveats = ["The steps are drafted from GuideWire's knowledge base, not from a tutorial: it is the usual order, and a tutorial may do it differently.", *bundle.caveats]
                bundle.reasons.append(f"wants_steps: steps built from knowledge base topics {[e.id for e in chosen]}")
        return bundle


__all__ = ["changes_progress", "ModelAnswerer", "build_prompt", "retrieve_entries", "session_from_tutorial", "default_manual", "STATE_INTENTS", "SCHEMA", "SYSTEM"]
