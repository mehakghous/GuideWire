"""Deterministic ingestion of a user-supplied transcript: SRT/VTT, or pasted timestamped lines. No model, no network.

Pipeline: parse timed text -> clean (empty, duplicate and rolling-caption overlap) -> group cues into units ->
detect operations and action cues -> candidate steps / explanation units.

Hard rules:
- A transcript says what was SAID. Every step produced here has support='narrated' and provenance='transcript_rules';
  it is never labelled demonstrated or visually verified. Visual-only actions (a key press nobody mentions) cannot
  appear in the output, and that is reported as a limitation, not hidden.
- Times are the cue times from the file. If a duration is given and a unit lies beyond it, extraction FAILS with a
  validation error; times are never clamped.
- A unit that mentions an operation without an action cue is kept as an explanation, not turned into a step.
- Expected state comes from the catalog (the transcript rarely states it) and is labelled as an assumption.
- Quote evidence is the verbatim unit text, so `ingestion.transcript.check_evidence` can re-check it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from shared.answer import Explanation
from shared.step_record import Action, Step, StepList

from .catalog import normalise_shortcut, BY_ID, Operation
from .negation import negated_at
from .knowledge import finish, make_step
from .transcript import Cue, parse_cues

_LINE = re.compile(r"^\s*(?:[*\-•]\s*)?`?(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?`?\s*(.*)$")
_BRACKET_S = re.compile(r"^\s*\[(\d+(?:\.\d+)?)s\]\s*(.*)$")
_MDLINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_CUE_ACTION = re.compile(r"\b(press|hit|select|click|go to|go into|goes into|toggle|choose|simply|switch|change|use|using|we'?ll|let'?s|"
                         r"i'?m (?:just )?gonna|you can|you'?ll|want to|have to|need to)\b")
_MODE_CHANGE = re.compile(r"\b(toggle|switch|enter|go (?:back )?(?:into|to)|goes into|return|back (?:in)?to|going into|"
                          r"changing this drop|access it|press tab|tab to)\b")
_MARKERS = ("for hotkey users", "once you've", "once you have", "in case you", "to do this", "however", "for example", "let's",
            "once again", "fun fact", "one more", "now let's", "finally")
_SINGLE_WORD_OK = {"object.join", "mesh.separate", "history.undo", "history.redo", "transform.move", "transform.rotate", "transform.scale"}
_MERGE_GAP_S = 10.0
# A unit must not end in the middle of an instruction ('...go to the mesh menu and select | separate'):
_DANGLING = frozenset({"the", "a", "an", "and", "to", "of", "select", "press", "hit", "in", "into", "go", "then", "you", "your", "or", "it"})


@dataclass
class Unit:
    start: float
    end: float
    text: str
    spans: list[tuple[float, float, str]] = field(default_factory=list)


@dataclass
class TranscriptResult:
    steplist: StepList | None
    explanations: list[Explanation] = field(default_factory=list)
    unmatched_units: list[Unit] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)


def parse_timed_text(text: str, duration_s: float | None = None) -> list[Cue]:
    """SRT/VTT first; otherwise lines such as '00:00:12.340 words', '1:23 words', '[83s] words' or markdown bullets
    with backticked timestamps. Raises ValueError if nothing parses."""
    try:
        return parse_cues(text)
    except ValueError:
        pass
    rows: list[tuple[float, str]] = []
    for line in text.splitlines():
        m = _BRACKET_S.match(line)
        if m:
            rows.append((float(m.group(1)), m.group(2)))
            continue
        m = _LINE.match(line)
        if m:
            h, mi, s, frac, body = m.groups()
            t = int(h or 0) * 3600 + int(mi) * 60 + int(s) + (int(frac.ljust(3, "0")) / 1000 if frac else 0)
            rows.append((t, body))
        elif rows and line.strip() and not line.strip().startswith(("*", "`")):
            rows[-1] = (rows[-1][0], rows[-1][1] + " " + line.strip())
    if not rows:
        raise ValueError("no timestamped text found (expected SRT, WebVTT, or lines like '00:00:12.340 text')")
    cues = []
    for i, (t, body) in enumerate(rows):
        end = rows[i + 1][0] if i + 1 < len(rows) else (duration_s if duration_s and duration_s > t else t + 3.0)
        cues.append(Cue(t, end, _MDLINK.sub(r"\1", body)))
    return cues


def clean_cues(cues: list[Cue]) -> tuple[list[Cue], dict]:
    """Drop empty cues, exact consecutive duplicates and rolling-caption overlap (leading words repeating the previous cue's tail)."""
    out: list[Cue] = []
    stats = {"empty": 0, "duplicate": 0, "overlap_trimmed": 0}
    prev_words: list[str] = []
    for c in sorted(cues, key=lambda c: c.start_s):
        text = " ".join(c.text.split())
        if not text:
            stats["empty"] += 1
            continue
        words = text.split()
        if out and " ".join(words).lower() == out[-1].text.lower():
            stats["duplicate"] += 1
            continue
        k = min(len(words), len(prev_words), 12)
        while k >= 3:
            if [w.lower() for w in prev_words[-k:]] == [w.lower() for w in words[:k]]:
                words = words[k:]
                stats["overlap_trimmed"] += 1
                break
            k -= 1
        if not words:
            stats["duplicate"] += 1
            continue
        out.append(Cue(c.start_s, c.end_s, " ".join(words)))
        prev_words = words
    return out, stats


def group_units(cues: list[Cue], max_words: int = 26, max_gap_s: float = 1.5) -> list[Unit]:
    units: list[Unit] = []
    cur: Unit | None = None
    for c in cues:
        low = c.text.lower()
        marker = any(m in low for m in _MARKERS)
        if cur is not None:
            gap = c.start_s - cur.end
            dangling = cur.text.split()[-1].lower() in _DANGLING and len(cur.text.split()) < max_words + 12
            if (marker or gap > max_gap_s or len(cur.text.split()) >= max_words or cur.text.rstrip().endswith((".", "?", "!"))) and not (dangling and not marker):
                units.append(cur)
                cur = None
        if cur is None:
            cur = Unit(c.start_s, c.end_s, c.text, [(c.start_s, c.end_s, c.text)])
        else:
            cur.text += " " + c.text
            cur.end = c.end_s
            cur.spans.append((c.start_s, c.end_s, c.text))
    if cur is not None:
        units.append(cur)
    return units


# Instructional phrase patterns per operation, applied to lowercase transcript text. Bag-of-words aliases are too loose for
# running speech ('separate objects' is a description, 'join two vertices' is not Join). A pattern must match AND the unit
# must contain an action cue. Adding or tightening a pattern is the way to improve this path; each one is tested.
TRANSCRIPT_PATTERNS: dict[str, re.Pattern] = {k: re.compile(v) for k, v in {
    "mode.toggle": r"\btoggle between (?:edit|object)\b|\bpress (?:a )?tab\b[^.]{0,30}\btoggle\b",
    "mode.enter_edit": r"\b(?:enter|entering|go(?:es|ing)?|switch(?:ing)?|toggl\w+|access|change)\b(?:\s+\w+){0,5}?\s+(?:into |to )?edit mode\b|\baccess it by\b",
    "mode.enter_object": r"\b(?:toggl\w+|go(?:es|ing)?|return\w*|switch\w*|chang\w+|exit\w*|leave|back)\b(?:\s+\w+){0,4}?\s+(?:into|to|in)\s+object mode\b",
    "select.object": r"\bselect(?:ing)?\s+(?:all\s+)?(?:the\s+|both\s+|these\s+)?(?:cubes?|objects?|them)\b",
    "select.elements": r"\bselect(?:ing)?\s+(?:one or multiple |a part of |some |the |an |a )?(?:vertices|vertex|edges?|faces?|part)\b|\bselect a part\b",
    "transform.move": r"\bto move,? rotate,? (?:or|and) scale\b|\bmove (?:it|the (?:object|selection|vertices)|our|your|vertices)\b",
    "transform.rotate": r"\bto move,? rotate,? (?:or|and) scale\b|\brotate (?:it|the|our|your|this)\b",
    "transform.scale": r"\bto move,? rotate,? (?:or|and) scale\b|\bscale (?:it|the|our|your|this)\b",
    "history.undo": r"\b(?:hit|press) control z\b|\b(?:hit|press) ctrl\+?z\b|\bto undo\b",
    "history.redo": r"\b(?:hit|press) shift control z\b|\bto redo\b",
    "object.join": r"\bselect join\b|\b(?:press|hit) (?:a )?control j\b|\bjoin (?:these|the|them|those)(?: two)? objects\b",
    "mesh.separate": r"\b(?:select|choose) separate\b|\bpress p\b",
    "mode.multi_edit": r"\bedit multiple (?:mesh )?objects\b",
}.items()}


class KeySpan(str):
    """The words of a key press the speaker names ('hit tab', 'then 1'). Marks a step derived from a KEY rather than from a described operation."""
    key: str = ""


# Keys that stand for one catalog operation in the default layout. Tab is a toggle: the mode before it is not stated.
_KEY_OPS = {"tab": "mode.toggle", "1": "select.elements", "2": "select.elements", "3": "select.elements", "g": "transform.move", "r": "transform.rotate",
            "s": "transform.scale", "p": "mesh.separate"}
_KEYPAT = r"(tab|[123gprs])"
_NOT_COUNT = r"(?!\s*(?:seconds?|secs?|times|minutes?|mins?|more|extra))"
_KEY_FIRST = re.compile(rf"\b(?:press(?:ing)?|hit(?:ting)?|tap(?:ping)?)\s+(?:the\s+)?(?:key\s+)?{_KEYPAT}\b{_NOT_COUNT}")
_KEY_NEXT = re.compile(rf"^[^.;!?]{{0,60}}?,\s*(?:and\s+)?(?:then|next)\s+(?:(?:press|hit|tap)\s+)?(?:the\s+)?{_KEYPAT}\b{_NOT_COUNT}")
_KEY_WINDOW = (30, 60)       # a key is "already explained" if an operation pattern matched this close to it


def _explains(low: str, lo: int, hi: int, f_lo: int, f_hi: int) -> bool:
    """Does an operation-pattern match [f_lo, f_hi) already account for the key at [lo, hi)? Same clause only: overlapping, up to 40 characters
    after the key, or up to 30 before it, with no comma between ('press g to move it' yes; 'press tab, ... then rotate it' no)."""
    if f_lo < hi and lo < f_hi:
        return True
    if f_lo >= hi:
        return f_lo - hi <= _KEY_WINDOW[1] - 20 and "," not in low[hi:f_lo]
    return lo - f_hi <= _KEY_WINDOW[0] and "," not in low[f_hi:lo]


def _key_chain(low: str) -> list[tuple[int, str, "KeySpan", tuple[int, int]]]:
    """Keys named in a chain: 'hit tab, then 1 for vertex select, then g to grab' -> tab, 1, g (each its own step). A chain must START with
    press/hit/tap + a known key, and continues only through ', then <key>', so ordinary prose ('then 2 seconds') is not read as a key press."""
    out, pos = [], 0
    while True:
        m = _KEY_FIRST.search(low, pos)
        if not m:
            return out
        cur, end = m, m.end()
        while True:
            key = cur.group(1)
            span = KeySpan(low[cur.start():cur.end()])
            span.key = key
            out.append((cur.start(), _KEY_OPS[key], span, (cur.start(), cur.end())))
            nxt = _KEY_NEXT.match(low[end:])
            if not nxt or _KEY_FIRST.search(nxt.group(0)[:nxt.start(1)]):     # never skip over another explicit 'hit <key>' inside the gap
                break
            cur = type("M", (), {"group": lambda self, i, n=nxt: n.group(i), "start": lambda self, n=nxt, e=end: e + n.start(1), "end": lambda self, n=nxt, e=end: e + n.end(1)})()
            end = cur.end()
        pos = end


def choose_ops(text: str) -> list[tuple[Operation, str]]:
    return [(o, span) for o, span, _ in _choose(text)]


def _choose(text: str, include_negated: bool = False) -> list[tuple[Operation, str, tuple[int, int]]]:
    """(operation, matched span) a unit INSTRUCTS, by pattern, in order of first appearance. The span is the speaker's own words
    and is kept on the step so its wording ('select ALL the objects') is not lost to the generic template."""
    low = " ".join(text.lower().split())
    found = []
    for op_id, pat in TRANSCRIPT_PATTERNS.items():
        m = pat.search(low)
        if m and (include_negated or not negated_at(low, m.start(), m.end())):   # "do not press tab" is not an instruction to press it
            found.append((m.start(), BY_ID[op_id], m.group(0), (m.start(), m.end())))
    explained = list(found)                                      # operation-pattern matches only
    for st_, op_id, span, (lo, hi) in _key_chain(low):          # keys no operation pattern explains become their own steps
        if any(_explains(low, lo, hi, f_lo, f_hi) for _, _, _, (f_lo, f_hi) in explained) or negated_at(low, lo, hi) and not include_negated:
            continue
        found.append((st_, BY_ID[op_id], span, (lo, hi)))
    found.sort(key=lambda t: t[0])
    ids = {o.id for _, o, _, _ in found}
    ids = {o.id for _, o, sp, _ in found if not isinstance(sp, KeySpan)}
    return [(o, span, rng) for _, o, span, rng in found if not (o.id == "mode.enter_edit" and "mode.toggle" in ids)]  # toggle subsumes a bare mode word


def cue_span(u: "Unit", lo: int, hi: int) -> tuple[float, float, str]:
    """Time span and verbatim text of the cues that contain characters [lo, hi) of the unit's lowercase, single-spaced text."""
    pos, first, last = 0, None, None
    for a, b, t in u.spans:
        n = len(" ".join(t.lower().split()))
        if first is None and lo < pos + n + 1:
            first = (a, b, t)
        if pos <= max(hi - 1, lo) < pos + n + 1:
            last = (a, b, t)
        pos += n + 1
    first = first or u.spans[0]
    last = last or u.spans[-1]
    i0, i1 = u.spans.index(first), u.spans.index(last)
    seg = u.spans[i0:i1 + 1]
    return seg[0][0], seg[-1][1], " ".join(t for _, _, t in seg)


_GENERIC_TITLE = frozenset({"introduction", "overview", "index", "tools", "tool", "properties", "settings", "options", "operators", "editing"})
_FRAME = r"(?:use|using|choose|select|click|press|hit|activate|with|apply|add|enable)\s+(?:the\s+|a\s+|an\s+)?"


def _doc_mapped_steps(u: "Unit", kb, version) -> list[tuple[Step, float, float]]:
    """Steps for tools the speaker NAMES that are not in the hand-written catalog, taken from the manual's Reference block.
    High-precision rule, deliberately: a multi-word page title must appear as a phrase in the unit; a one-word title must appear right
    after an instruction verb ('use the Knife tool'). Anything else is left unmatched rather than guessed. Unreviewed, narrated only."""
    from .kb.candidates import candidate_from_hit, candidate_steps

    low = " ".join(u.text.lower().split())
    out = []
    for h in kb.search(u.text, limit=4).hits:
        words = [w for w in re.findall(r"[a-z0-9]+", h.title.lower()) if w not in _GENERIC_TITLE]
        if not words:
            continue
        phrase = r"\s+".join(re.escape(w) + r"s?" for w in words)
        pat = re.compile(rf"\b{phrase}\b") if len(words) > 1 else re.compile(rf"\b{_FRAME}{phrase}\b")
        m = pat.search(low)
        c = candidate_from_hit(h) if m else None
        if c is None:
            continue
        steps, _, _, _ = candidate_steps(c, u.text)
        s = steps[-1]
        t0, t1, said = cue_span(u, m.start(), m.end())
        s.support, s.provenance = "narrated", "transcript_rules"
        s.evidence = [said[:240]]
        s.video_start_s, s.video_end_s = t0, t1
        s.source_refs = [*s.source_refs, f"transcript:{t0:g}-{t1:g}s"]
        s.assumptions = [*s.assumptions, "Mapped to this manual page because the speaker names the tool; the page was not reviewed against what the video shows.",
                         "Narrated only: nothing here shows the action was performed on screen."]
        s.confidence = 0.5
        out.append((s, t0, t1))
        break
    return out


def ingest_transcript(text: str, *, duration_s: float | None = None, version: str | None = None,
                      video_id: str | None = None, title: str | None = None, kb=None) -> TranscriptResult:
    cues = parse_timed_text(text, duration_s)
    cues, cstats = clean_cues(cues)
    units = group_units(cues)
    steps: list[Step] = []
    expl: list[Explanation] = []
    unmatched: list[Unit] = []
    negated_units = 0
    last_by_op: dict[str, Step] = {}
    for u in units:
        ops = _choose(u.text)
        has_action = bool(_CUE_ACTION.search(u.text.lower()))
        if not ops and kb is not None and has_action:
            mapped = _doc_mapped_steps(u, kb, version)
            if mapped:
                for st, t0, t1 in mapped:
                    st.id = f"s{len(steps) + 1:02d}"
                    steps.append(st)
                continue
        if not ops:
            if _choose(u.text, include_negated=True):          # an operation is named but told NOT to be done (or only hypothetically)
                expl.append(Explanation(text=u.text + " [negated or hypothetical: not treated as an action to perform]",
                                        provenance="transcript_rules", start_s=u.start, end_s=u.end))
                negated_units += 1
            else:
                unmatched.append(u)
            continue
        if not has_action:
            expl.append(Explanation(text=u.text, provenance="transcript_rules", start_s=u.start, end_s=u.end,
                                    sources=list(ops[0][0].sources[:1])))
            continue
        for op, span, (lo, hi) in ops:
            t0, t1, said = cue_span(u, lo, hi)          # tight: only the cues that contain the instruction
            prev = last_by_op.get(op.id)
            is_key = isinstance(span, KeySpan)
            if not is_key and prev is not None and prev.video_end_s is not None and t0 - prev.video_end_s <= _MERGE_GAP_S:
                prev.video_end_s = t1
                prev.evidence.append(said[:240])
                prev.source_refs.append(f"transcript:{t0:g}-{t1:g}s")
                continue
            tpl = op.clause
            kname = (span.key.title() if span.key == "tab" else span.key.upper()) if is_key else ""
            st = make_step(len(steps) + 1, tpl, op, "transcript_rules", confidence=0.6,
                           goal=f"Press {kname} ({tpl.goal[0].lower()}{tpl.goal[1:]})" if is_key else None,
                           extra_refs=(f"transcript:{t0:g}-{t1:g}s",),
                           assumptions=("The expected state comes from the catalog; the transcript does not state it.",
                                        "Narrated only: nothing here shows the action was performed on screen."))
            st.support = "narrated"
            if is_key:
                st.actions.insert(0, Action(verb="press_keys", keys=[kname], value=str(span)[:80]))
            elif st.actions:
                st.actions[0] = st.actions[0].model_copy(update={"value": span[:80]})  # the speaker's words, verbatim
            st.evidence = [said[:240]]
            st.video_start_s, st.video_end_s = t0, t1
            sc = [s for s in op.shortcuts if re.search(rf"\b{re.escape(s.replace('ctrl+', 'control ').replace('+', ' '))}\b|\b{re.escape(s)}\b", u.text.lower())]
            if sc:
                st.alternatives = list(dict.fromkeys(st.alternatives + [f"the transcript mentions the shortcut {sc[0]}"]))
            if op.id == "mode.toggle":
                st.assumptions.append("Tab toggles: the current mode is not stated in the transcript.")
            from .text_steps import user_shortcuts
            for k in user_shortcuts(said):
                if op.shortcuts and k not in {normalise_shortcut(x) for x in op.shortcuts}:
                    st.flags.append(f"the speaker says '{k}', but the manual gives {', '.join(op.shortcuts)} for this operation (their wording is kept, nothing was changed)")
            steps.append(st)
            last_by_op[op.id] = st
    res = TranscriptResult(steplist=None, explanations=expl, unmatched_units=unmatched, stats={
        **cstats, "cues_in": len(cues), "units": len(units), "steps": len(steps), "explanation_units": len(expl),
        "unmatched_units": len(unmatched), "negated_units": negated_units}, limitations=[
        "A transcript cannot show what was done on screen: demonstrated-only actions are not produced.",
        "Only operations in the catalog are recognised; other instructions appear as unmatched units, not steps.",
        "Step start and end times are the span of the matched transcript unit, not the moment of a key press."])
    if steps:
        res.steplist = finish(steps, "transcript", title=title, version=version, duration_s=duration_s)
        res.steplist.video_id = video_id
        res.steplist.video_duration_s = duration_s
    return res
