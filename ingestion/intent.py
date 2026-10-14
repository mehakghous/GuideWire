"""Deterministic intent classification for requests about Blender. Rules only; no model.

It decides WHAT the user needs, not the answer: a how-to, a concept, a shortcut lookup, troubleshooting, a
pasted procedure, a mix of those, a vague request that needs a question back, or something outside the catalog.
The word lists are small and explicit so every decision can be audited in `reasons`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .catalog import UNSUPPORTED_TERMS, match_aliases, match_troubleshooting, tokens

IMPERATIVES = frozenset({
    "select", "press", "click", "go", "enter", "switch", "move", "rotate", "scale", "join", "separate", "undo", "redo", "add",
    "delete", "open", "choose", "hit", "drag", "toggle", "return", "exit", "leave", "duplicate", "use", "pick", "grab", "then",
    # modelling verbs the catalog does not cover yet: they still start a new clause, so "press Tab, extrude it" is two steps
    "extrude", "bevel", "inset", "subdivide", "merge", "fill", "apply", "rename", "hide", "remove", "insert", "smooth",
})
_TROUBLE = re.compile(r"\b(why (can'?t|cant|won'?t|wont|doesn'?t|does not|isn'?t|is not|am i unable)|can'?t|cant|cannot|won'?t|"
                      r"doesn'?t work|does not work|not working|nothing happens|does nothing|has no effect|no effect|greyed out|grayed out|error|fails?|failed)\b")
_CONCEPT = re.compile(r"^(what( is|'s| does| are| do)|explain|define|difference between|meaning of|when (should|do) i|why (do|does|is|are|should) )")
_HOWTO = re.compile(r"^(how (do|can|could|would|should|to)|show me|teach me|guide me|steps? (to|for)|walk me through|i want to|i need to)")
_SHORTCUT = re.compile(r"\b(shortcut|hotkey|key combination|which key|what key|key for)\b")
_EXPLAIN = re.compile(r"\b(explain|why)\b")
_NUMBERED = re.compile(r"^\s*(\d+[.)]|[-*•])\s+", re.M)
_VAGUE_PRONOUN = re.compile(r"\b(it|this|that|these|those)\b")


@dataclass
class Intent:
    kind: str                       # procedure_text | how_to | concept | shortcut | troubleshooting | mixed | vague | unsupported
    ops: list[str] = field(default_factory=list)
    trouble_ops: list[str] = field(default_factory=list)
    unsupported_terms: list[str] = field(default_factory=list)
    explain_requested: bool = False
    asks_shortcut: bool = False
    reasons: list[str] = field(default_factory=list)


def _comma_split(sent: str) -> str:
    """Turn ', <imperative verb>' into a 'then' so a comma-separated procedure splits into clauses."""
    verbs = "|".join(sorted(IMPERATIVES - {"then"}))
    return re.sub(rf",\s+(?=(?:{verbs})\b)", " then ", sent, flags=re.I)


_CONDITION_ONLY = re.compile(r"^(?:if|when|once|in case)\b", re.I)
_LEAD_MARKER = re.compile(r"^(?:and\s+then|then|next|after that|afterwards)\b[\s,]*", re.I)


def split_clauses(text: str) -> list[str]:
    """Split a pasted procedure into clauses: numbered/bulleted lines, sentences, and 'then' chains."""
    text = text.strip()
    if _NUMBERED.search(text):
        parts = [_NUMBERED.sub("", ln).strip() for ln in text.splitlines() if ln.strip()]
    else:
        parts = [text]
    out: list[str] = []
    for part in parts:
        for sent in re.split(r"(?<=[.!?;])\s+|\s*->\s*|\s*→\s*", part):
            for piece in re.split(r",?\s+\b(?:and then|then|after that|next|afterwards)\b,?\s*", _comma_split(sent), flags=re.I):
                piece = _LEAD_MARKER.sub("", piece.strip(" ,.;")).strip(" ,.;")   # a sequencing word is not part of the instruction
                if piece:
                    out.append(piece)
    merged: list[str] = []
    for piece in out:           # "If the cube is not selected, select it": the condition is part of the step, not a step of its own
        if merged and _CONDITION_ONLY.match(merged[-1]) and not _is_imperative(merged[-1]):
            merged[-1] = f"{merged[-1]}, {piece}"
        else:
            merged.append(piece)
    return merged


def _is_imperative(clause: str) -> bool:
    if _CONDITION_ONLY.match(clause) and "," in clause:        # "If it is not selected, select it": judge the part after the condition
        clause = clause.split(",", 1)[1]
    first = re.findall(r"[a-z']+", clause.lower())[:1]
    return bool(first) and first[0] in IMPERATIVES


def classify(text: str) -> Intent:
    t = " ".join(text.lower().split())
    toks = tokens(t)
    ops = [o.id for o, _ in match_aliases(t)]
    trouble = [o.id for o in match_troubleshooting(t)]
    unsup = sorted(w for w in toks & UNSUPPORTED_TERMS)
    if {"geometry", "nodes"} <= toks:
        unsup.append("geometry nodes")
    it = Intent(kind="vague", ops=ops, trouble_ops=trouble, unsupported_terms=unsup,
                explain_requested=bool(_EXPLAIN.search(t)), asks_shortcut=bool(_SHORTCUT.search(t)))
    clauses = split_clauses(text)
    n_imp = sum(_is_imperative(c) for c in clauses)
    procedural = (not t.endswith("?")) and not _HOWTO.match(t) and (n_imp >= 2 or (n_imp >= 1 and len(clauses) >= 2)
                                                                    or bool(_NUMBERED.search(text)) or (n_imp == 1 and len(toks) >= 3 and _is_imperative(clauses[0])))
    howto = bool(_HOWTO.match(t)) or (t.startswith("how") and "?" in text)
    troubleshoot = bool(_TROUBLE.search(t))   # wording only: a known trouble topic alone does not make a how-to a complaint
    concept = bool(_CONCEPT.match(t)) and not troubleshoot

    if troubleshoot:
        it.kind = "troubleshooting"; it.reasons.append("troubleshooting wording or a known trouble trigger")
    elif howto and it.explain_requested and ("why" in t or "explain" in t) and ops:
        it.kind = "mixed"; it.reasons.append("how-to request plus a request to explain")
    elif procedural and it.explain_requested and re.search(r"\b(explain|why)\b", t) and ops:
        it.kind = "mixed"; it.reasons.append("pasted procedure plus a request to explain")
    elif it.asks_shortcut and ops:
        it.kind = "shortcut"; it.reasons.append("asks for a shortcut or key")
    elif concept:
        it.kind = "concept"; it.reasons.append("what/explain/difference wording")
    elif howto:
        it.kind = "how_to"; it.reasons.append("how-to wording")
    elif procedural:
        it.kind = "procedure_text"; it.reasons.append(f"{n_imp} imperative clause(s) of {len(clauses)}")
    else:
        it.kind = "vague"; it.reasons.append("no recognised structure")

    if trouble and not ops:
        it.kind = "troubleshooting"; it.reasons.append("matched a known trouble topic")
    if not ops and not trouble:
        if unsup:
            it.kind = "unsupported"; it.reasons.append(f"only topics outside the catalog: {unsup}")
        elif it.kind in ("how_to", "concept", "shortcut", "procedure_text", "troubleshooting", "mixed", "vague") and (
                len(toks) <= 9 or bool(_VAGUE_PRONOUN.search(t))):
            it.kind = "vague"; it.reasons.append("no recognised operation and the request is too short or refers to 'it'")
        elif it.kind != "vague":
            it.kind = "unsupported"; it.reasons.append("no catalog operation matched")
    return it
