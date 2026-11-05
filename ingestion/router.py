"""Cost-aware router: decide whether a request can be answered WITHOUT a model, and say so explicitly.

Order (a policy, not a rigid pipeline; every decision is recorded in `bundle.reasons`):
 0. input form: manual step list (JSON) and timestamped transcripts have their own routes and are never run through the
    question logic;
 1. a person-reviewed workflow for the same operation(s), if the Blender version is known and inside its range;
 2. a deterministic catalog answer (how-to steps, concept, shortcut, troubleshooting) for known operations;
 3. offline parsing of a pasted procedure into steps;
 4. a clarification question when the request is too vague or a material prerequisite is unknown;
 5. otherwise an explicit `fallback_required` result. NOTHING IS CALLED: whether to spend model quota is the caller's decision.
This module makes no network or model call and has no way to make one.
"""
from __future__ import annotations

import json
import re

from shared.answer import AnswerBundle, Explanation, SourceRef
from shared.step_record import Step

from .catalog import BY_ID, Operation, version_status
from .rigging_text import MIN_CLAUSES, clauses_of, looks_like_rigging, prerequisite_notes, rigging_to_steplist
from .intent import classify
from .knowledge import finish, how_to_steps
from .text_steps import written_to_steplist
from .transcript_ingest import ingest_transcript, parse_timed_text
from .workflows import ReviewedWorkflowStore, normalise_manual_steps, op_key, text_key

SUPPORTED_HINT = ("switch between Object and Edit Mode, select vertices/edges/faces, move/rotate/scale, undo/redo, "
                  "join objects, separate geometry, edit several objects at once")


def _sources(ops: list[Operation]) -> list[SourceRef]:
    seen, out = set(), []
    for o in ops:
        for s in o.sources:
            if s.url not in seen:
                seen.add(s.url)
                out.append(s)
    return out


def _looks_like_timed_text(text: str) -> bool:
    try:
        return len(parse_timed_text(text)) >= 3
    except ValueError:
        return False


def _fallback(text: str, reason: str, intent_reasons: list[str], unsupported: list[str]) -> AnswerBundle:
    return AnswerBundle(kind="needs_model", route="fallback_required", fallback_reason=reason, unsupported=unsupported,
                        reasons=intent_reasons + ["no model was called; the caller must decide whether to spend quota"], api_calls=0)


def _caveats(ops: list[Operation], version: str | None) -> list[str]:
    out: list[str] = []
    for o in ops:
        st, note = version_status(o, version)
        for c in [*o.caveats, note, *o.unverified]:
            if c not in out:
                out.append(c)
    return out


def _shortcut_text(op: Operation) -> str:
    parts = [f"{op.title}:"]
    if op.shortcuts:
        parts.append("shortcut " + ", ".join(s.replace("ctrl", "Ctrl").replace("shift", "Shift").replace("tab", "Tab").upper() if len(s) == 1 else s.replace("+", "+").title() for s in op.shortcuts))
    if op.menu_paths:
        parts.append("menu " + "; ".join(op.menu_paths))
    return " ".join(parts) + "."


_VERSION_IN_TEXT = re.compile(r"\bblender\s*v?(\d{1,2}\.\d{1,2})\b", re.I)


def _src(kb, sid: str) -> SourceRef:
    s = kb.sources[sid]
    kind = "manual" if s["tier"] == "official" else ("tutorial_video" if s["tier"] == "tutorial" else "forum")
    return SourceRef(kind=kind, title=s["title"], url=s["url"], version=s.get("version"), verified_on=kb_retrieved())


def kb_retrieved() -> str:
    from .rigging_knowledge import PATH
    return json.loads(PATH.read_text(encoding="utf-8")).get("retrieved", "")


def _rigging_troubleshooting(text: str, app: str) -> AnswerBundle | None:
    from .rigging_knowledge import load as knowledge
    kb = knowledge()
    for a in [app, *[x for x in ("maya", "blender") if x != app]]:                # the person's own application first, then the others
        hit = kb.troubleshoot(text, a)
        if hit is None:
            continue
        entry, item = hit
        srcs = [_src(kb, s) for s in item["sources"]]
        steps = " ".join(f"{i}. {f}" for i, f in enumerate(item["fix"], 1))
        who = "the application vendor" if item["tier"] == "official" else "forum or Q&A advice: practical but not guaranteed, and often written for older versions"
        caveats = [f"Trust: {item['tier']} ({who}). Check the menu names against your version."]
        if a != app:
            caveats.append(f"This is {a} advice but you are working in {app}. If that is wrong, say which application you use.")
        for c in entry.conflicts:
            caveats.append("Sources disagree: " + c["text"])
        return AnswerBundle(kind="troubleshooting", route="rigging_knowledge", trust="none",
                            explanations=[Explanation(text=f"Likely cause: {item['cause']}", sources=srcs, provenance="documentation"),
                                          Explanation(text=f"What to try: {steps}", sources=srcs, provenance="documentation")],
                            sources=srcs, caveats=caveats, reasons=[f"matched a known symptom in the {a} knowledge base entry {entry.id}"])
    return None


def route(text: str, *, version: str | None = None, observed: dict | None = None,
          store: ReviewedWorkflowStore | None = None, input_type: str | None = None,
          duration_s: float | None = None, kb=None, tutorials: list[dict] | None = None,
          app: str = "blender") -> AnswerBundle:
    stripped = text.strip()
    # ---- 0. input form
    if input_type == "manual_steps" or (input_type is None and stripped.startswith("{") and '"steps"' in stripped):
        sl, notes = normalise_manual_steps(json.loads(stripped), version)
        return AnswerBundle(kind="procedure", route="manual_steps", steps=sl, caveats=notes, reasons=["manual step list validated against the shared schema"])
    if input_type == "transcript" or (input_type is None and _looks_like_timed_text(stripped)):
        r = ingest_transcript(stripped, duration_s=duration_s, version=version, app=app)
        notes = prerequisite_notes(r.steplist) if r.steplist is not None and r.steplist.app != "blender" else ([], [])        # prerequisites the narration never covers
        return AnswerBundle(kind="procedure" if r.steplist else "unsupported", route="transcript_parser", steps=r.steplist,
                            explanations=r.explanations, caveats=r.limitations + notes[1], assumptions=notes[0],
                            reasons=[f"transcript parsed offline: {r.stats}"],
                            fallback_reason=None if r.steplist else "no instructional operation recognised in the transcript; a model could read it, none was called")

    # ---- a symptom people describe ("my knee flips", "the mesh does not follow the skeleton"): answer from the researched knowledge base, with the tier and source of every line
    if input_type is None and not stripped.startswith("{") and len(stripped) < 400:
        tb = _rigging_troubleshooting(stripped, app)
        if tb is not None:
            return tb

    # ---- rigging and animation instructions: every Maya/Houdini procedure, and Blender text that mostly names rigging features
    if input_type == "rigging_text" or (input_type is None and not stripped.startswith("{") and (app != "blender" or looks_like_rigging(stripped, app))):
        if len(clauses_of(stripped)) < MIN_CLAUSES:
            return AnswerBundle(kind="clarification", route="clarify", reasons=[f"app is {app}: only pasted multi-step procedures are supported there so far"],
                                clarification=f"For {app} I can turn a pasted procedure into steps. Put each step on its own line (at least two).")
        hit = store.find(text_key(stripped), version) if store is not None else None
        if hit is not None:
            return AnswerBundle(kind="procedure", route="reviewed_workflow", steps=hit, reasons=[f"reviewed workflow {text_key(stripped)}"])
        sl, rr = rigging_to_steplist(stripped, app, version)
        return AnswerBundle(kind="procedure", route="rigging_text", steps=sl, assumptions=rr.assumptions, caveats=rr.caveats,
                            reasons=[f"rigging/animation procedure for {app}: {len(sl.steps)} steps, {len(rr.unmatched)} unmatched"])

    it = classify(stripped)
    reasons = list(it.reasons)
    if version is None:        # "... in Blender 4.2?": the user stated their version; an argument from the app still wins
        m = _VERSION_IN_TEXT.search(stripped)
        if m:
            version = m.group(1)
            reasons.append(f"Blender version {version} taken from the request text")
    ops = [BY_ID[i] for i in it.ops]

    # ---- local documentation index, tutorial discovery, state-dependent questions (only when a knowledge base / tutorial index is supplied)
    if kb is not None or tutorials is not None:
        from .answer_kb import answer_extended
        ext = answer_extended(stripped, it, kb, tutorials, version, observed)
        if ext is not None:
            return ext

    # ---- 1. reviewed workflow
    if store is not None and it.kind in ("how_to", "procedure_text") and ops:
        for key in (text_key(stripped), op_key([o.id for o in ops])):
            hit = store.find(key, version)
            if hit is not None:
                return AnswerBundle(kind="procedure", route="reviewed_workflow", steps=hit, reasons=reasons + [f"reviewed workflow {key}"],
                                    sources=_sources(ops))

    # ---- 4/5. vague and unsupported
    if it.kind == "vague":
        return AnswerBundle(kind="clarification", route="clarify", reasons=reasons,
                            clarification=f"Which Blender operation do you mean? I can answer about: {SUPPORTED_HINT}.")
    if it.kind == "unsupported":
        return _fallback(stripped, f"the request is about topics outside the catalog: {it.unsupported_terms or 'unrecognised'}",
                         reasons, it.unsupported_terms)

    caveats = _caveats(ops, version)
    unsupported_part = [w for w in it.unsupported_terms]
    extra_fallback = (f"also mentions topics outside the catalog ({', '.join(unsupported_part)}); those parts were not answered and no model was called"
                      if unsupported_part else None)

    # ---- 2/3. deterministic answers
    if it.kind == "shortcut":
        return AnswerBundle(kind="concept", route="catalog", reasons=reasons, caveats=caveats, sources=_sources(ops), fallback_reason=extra_fallback,
                            explanations=[Explanation(text=_shortcut_text(o), sources=list(o.sources)) for o in ops])

    if it.kind == "concept":
        return AnswerBundle(kind="concept", route="catalog", reasons=reasons, caveats=caveats, sources=_sources(ops), fallback_reason=extra_fallback,
                            explanations=[Explanation(text=o.explanation, sources=list(o.sources)) for o in ops])

    if it.kind == "procedure_text":
        sl, res = written_to_steplist(stripped, version)
        return AnswerBundle(kind="procedure", route="text_parser", steps=sl, assumptions=res.assumptions, caveats=res.caveats + res.warnings,
                            clarification=res.questions[0] if res.questions else None, sources=_sources(ops),
                            fallback_reason=(f"{len(res.unmatched)} clause(s) are outside the catalog and were kept as unvalidated steps: {res.unmatched}"
                                             if res.unmatched else extra_fallback),
                            reasons=reasons + [f"duplicates removed: {res.duplicates_removed}"])

    # how_to / troubleshooting / mixed: build steps for the matched operations
    steps: list[Step] = []
    ctx_unknown: list[str] = []
    ctx_unmet: list[str] = []
    questions: list[str] = []
    op_steps: dict[str, list[str]] = {}
    trouble = [BY_ID[i] for i in it.trouble_ops]
    remedy_ops = [BY_ID[t.remedy_op] for t in trouble if t.remedy_op]
    step_ops = ops if it.kind in ("how_to", "mixed") else (remedy_ops or ops)
    for op in step_ops:
        if op.kind != "procedure":
            continue
        new, ctx, cav = how_to_steps(op, version, observed)
        first = len(steps)
        steps.extend(new)
        op_steps[op.id] = [f"{first + k + 1}" for k in range(len(new))]
        ctx_unknown += [u for u in ctx.unknown if u not in ctx_unknown]
        ctx_unmet += [u for u in ctx.unmet if u not in ctx_unmet]
        questions += [q for q in ctx.questions if q not in questions]
        caveats += [c for c in cav if c not in caveats]
    explanations: list[Explanation] = []
    if trouble:
        for t in trouble:
            link = [f"s{int(n):02d}" for n in op_steps.get(t.remedy_op, [])] if t.remedy_op else []
            explanations.append(Explanation(text=t.explanation, applies_to_steps=link, sources=list(t.sources)))
    elif it.kind == "troubleshooting" and ops:
        for op in ops:
            needs = [p.text for p in op.prerequisites]
            explanations.append(Explanation(text=f"{op.title} only works when: " + " ".join(needs) if needs else op.explanation, sources=list(op.sources),
                                            applies_to_steps=[f"s{int(n):02d}" for n in op_steps.get(op.id, [])]))
    elif it.kind == "mixed":
        for op in ops:
            explanations.append(Explanation(text=op.explanation, sources=list(op.sources),
                                            applies_to_steps=[f"s{int(n):02d}" for n in op_steps.get(op.id, [])]))
    if ctx_unmet:
        questions.append("These prerequisites are not met in your application: " + " ".join(ctx_unmet))
    if not steps and not explanations:
        return _fallback(stripped, "no deterministic answer could be built for this request", reasons, unsupported_part)
    sl = finish(steps, "catalog", version=version) if steps else None
    kind = "troubleshooting" if it.kind == "troubleshooting" else ("mixed" if it.kind == "mixed" else "procedure")
    return AnswerBundle(
        kind=kind, route="catalog", steps=sl, explanations=explanations,
        assumptions=[f"Assumes: {u}" for u in ctx_unknown] if observed is None or ctx_unknown else [],
        caveats=caveats, sources=_sources(ops + trouble), unmet_prerequisites=ctx_unmet,
        clarification=questions[0] if questions and (observed is None or ctx_unmet or ctx_unknown) else None,
        fallback_reason=extra_fallback, reasons=reasons + ([f"troubleshooting trigger: {[t.id for t in trouble]}"] if trouble else []),
    )
