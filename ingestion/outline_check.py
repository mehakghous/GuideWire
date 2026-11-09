"""After extraction: use the knowledge base's ordered outlines to point at steps that MAY be missing or out of order.

An outline is the typical order of operations for a topic ("Skeleton: create joints, name them, ..."). Put into the extraction prompt it made the model copy the sequence instead of watching
(docs/evaluation_report_2026-11-09.md, section 1.6), so it is used here only AFTER extraction, as a checklist for a person: nothing is added to, removed from or reordered in the step list.

A topic is "in play" when at least half of its outline items (and at least two) are matched by some step. For such a topic:
  * an outline item no step matches is a HINT "possibly missing" (the video may simply skip it: outlines are typical, not required);
  * matched items whose steps run in a different order than the outline are a HINT "possibly out of order".
A hint is a question for the reviewer, never a claim. Matching is by shared words (an item is matched by a step when the step's text contains at least MIN_SHARE of the item's content words).
"""
from __future__ import annotations

from dataclasses import dataclass

from shared.step_record import Step, StepList

from .rigging_knowledge import Knowledge, _tokens
from .rigging_knowledge import load as load_knowledge

MIN_SHARE = 0.5          # share of an outline item's words that a step must contain
MIN_ITEMS_MATCHED = 2    # a topic is only "in play" when at least this many of its items are matched, and at least half of them


@dataclass(frozen=True)
class Hint:
    kind: str            # "missing" | "order"
    entry_id: str
    item: str            # the outline item
    after_step: str | None   # the last step id before the place the item would go (None = at the start)
    detail: str

    def render(self) -> str:
        return f"{self.kind}: {self.detail}"


def _step_tokens(st: Step) -> frozenset[str]:
    return _tokens(" ".join([st.goal, st.result or "", *(h.text for h in st.how_to), *(a.ui_element or "" for a in st.actions)]))


def _match(item_tokens: frozenset[str], step_tokens: frozenset[str]) -> bool:
    return bool(item_tokens) and len(item_tokens & step_tokens) / len(item_tokens) >= MIN_SHARE


def outline_hints(sl: StepList, kb: Knowledge | None = None) -> list[Hint]:
    kb = kb or load_knowledge()
    steps = [(s, _step_tokens(s)) for s in sl.steps]
    hints: list[Hint] = []
    for e in kb.entries:
        if sl.app not in e.apps or len(e.outline) < 3:
            continue
        items = [(it.text, _tokens(it.text)) for it in e.outline]
        first_match: list[int | None] = []          # for each outline item, the index of the FIRST step that matches it
        for _text, toks in items:
            first_match.append(next((i for i, (_s, st) in enumerate(steps) if _match(toks, st)), None))
        matched = [m for m in first_match if m is not None]
        if len(matched) < MIN_ITEMS_MATCHED or len(matched) * 2 < len(items):
            continue
        last_seen = None
        for k, ((text, _toks), m) in enumerate(zip(items, first_match)):
            if m is None:
                after = steps[last_seen][0].id if last_seen is not None else None
                hints.append(Hint("missing", e.id, text, after, f"{e.id}: the usual step \"{text.rstrip('.')}\" has no matching step" + (f" (it would come after {after})" if after else "")))
            else:
                last_seen = m if last_seen is None else max(last_seen, m)
        seq = [m for m in first_match if m is not None]
        for a, b in zip(seq, seq[1:]):
            if b < a:
                hints.append(Hint("order", e.id, items[first_match.index(b)][0], steps[b][0].id,
                                  f"{e.id}: \"{items[first_match.index(b)][0].rstrip('.')}\" is usually done before \"{items[first_match.index(a)][0].rstrip('.')}\" but its step ({steps[b][0].id}) comes after step {steps[a][0].id}"))
                break
    return hints
