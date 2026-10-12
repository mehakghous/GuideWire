"""Deterministic conversion of a pasted written procedure into shared-schema steps. Rules only; no model.

It maps each clause to a catalog operation by aliases, keeps the user's own wording as the step goal, and checks
what it can: documented shortcuts and menu paths, version, and the Edit/Object Mode prerequisite chain.
What it will NOT do: add steps the text does not contain, silently replace the user's shortcut, or pretend a
clause outside the catalog is understood. Those become explicit flags, assumptions or clarification questions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from shared.step_record import Action, Step, StepList

from .catalog import BY_ID, Operation, StepT, match_aliases, normalise_shortcut, version_status
from .intent import split_clauses
from .knowledge import finish, make_step
from .negation import clause_negated
from .profiles import norm

_MOD = r"(?:ctrl|control|ctl|shift|alt)"
_COMBO = re.compile(rf"\b((?:{_MOD}\s*[+-]\s*)+[a-z0-9])\b", re.I)
_PRESS = re.compile(r"\b(?:press(?:ing)?|hit(?:ting)?|type)\s+(?:the\s+)?(?:key\s+)?([a-z0-9]|tab|esc|enter)\b", re.I)
_MENU = re.compile(r"([A-Z][A-Za-z0-9 ]*?(?:\s*>\s*[A-Z][A-Za-z0-9 ]*?)+)(?=[\s,.;)]|$)")
_CLAIM = re.compile(r"\b(?:will|should)\s+(?:turn|become|see|look|change|appear|show|be)\b.*$", re.I)
# Main verbs for which the catalog has NO operation: a clause that starts with one is never mapped to a different operation
# just because it also mentions an object it knows.
_UNCATALOGUED_VERBS = frozenset({"delete", "remove", "add", "create", "insert", "duplicate", "extrude", "apply", "rename", "hide",
                                 "show", "bevel", "subdivide", "smooth", "export", "import", "save", "render", "make", "set"})
_COND = re.compile(r"^(?:if|when|once|in case)\s+(.+?),\s*\S.*$", re.I)
_KNOWN_KEYS = {"tab", "g", "r", "s", "p", "f", "e", "x", "z", "j", "a", "d", "1", "2", "3"}


@dataclass
class ParseResult:
    steps: list[Step]
    warnings: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    duplicates_removed: int = 0
    caveats: list[str] = field(default_factory=list)


def _norm_clause(c: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", c.lower()))


def user_shortcuts(clause: str) -> list[str]:
    out = [normalise_shortcut(m.group(1)) for m in _COMBO.finditer(clause)]
    combo_keys = {k.split("+")[-1] for k in out}
    for m in _PRESS.finditer(clause):
        k = m.group(1).lower()
        if k in _KNOWN_KEYS or len(k) == 1:
            if k not in combo_keys:
                out.append(k)
    return out


def user_menu_paths(clause: str) -> list[str]:
    return [" > ".join(s.strip() for s in m.group(1).split(">")) for m in _MENU.finditer(clause)]


def _split_and(clause: str) -> list[str]:
    parts = re.split(r"\s+and\s+(?=[A-Za-z])", clause)
    if len(parts) > 1 and all(match_aliases(p) for p in parts):
        return parts
    return [clause]


def _pick_ops(clause: str, mode: str | None) -> tuple[list[Operation], bool]:
    """(ops in text order, resolved_toggle). A bare 'Tab' is resolved with the tracked mode when it is known."""
    first = (re.findall(r"[a-z']+", clause.lower()) or [""])[0]
    if first in _UNCATALOGUED_VERBS:      # 'Delete the cube by selecting it' must not be reduced to 'select'
        return [], False
    hits = match_aliases(clause)
    if not hits:
        return [], False
    top = hits[0][1]
    ops = [o for o, n in hits if n == top]
    if len(ops) > 1:
        # "Press Ctrl+Z to enter edit mode": the part after "to" is the purpose and names the operation; the key is only the means.
        # One clause is one step, so tied operations are narrowed to those named in the purpose.
        m_to = re.search(r"\bto\b(.*)$", clause, re.I)
        tail = m_to.group(1) if m_to else ""
        if tail:
            tail_ids = {h.id for h, _ in match_aliases(tail)}
            in_tail = [o for o in ops if o.id in tail_ids]
            if in_tail and len(in_tail) < len(ops):
                ops = in_tail
    if len(ops) > 1:
        low = clause.lower()
        ops.sort(key=lambda o: min((low.find(w) for g in o.aliases for w in g if w in low and set(g) <= set(re.findall(r"[a-z0-9]+", low))), default=999))
    resolved = False
    if ops[0].id == "mode.toggle" and top == 1 and mode in ("OBJECT", "EDIT_MESH"):
        ops = [BY_ID["mode.enter_edit" if mode == "OBJECT" else "mode.enter_object"]]
        resolved = True
    return ops, resolved


_BARE_KEY = re.compile(rf"^(?:press(?:ing)?|hit(?:ting)?|tap)\s+(?:the\s+)?(?:(?:{_MOD}\s*[+-]\s*)+[a-z0-9]|[a-z0-9]|tab|esc|enter)\W*$", re.I)


def _merge_key_and_action(clauses: list[str]) -> tuple[list[str], set[str]]:
    """'Press Shift+A, add a cube' is ONE action written twice (the key, then what it does). When a bare key-press clause and the clause right
    after it are BOTH outside the catalog, they are kept as one step with the user's words joined; known operations are never merged
    ('Press Tab, select a face' stays two steps)."""
    out, merged, i = [], set(), 0
    while i < len(clauses):
        c = clauses[i]
        if i + 1 < len(clauses) and _BARE_KEY.match(c) and not _pick_ops(c, None)[0] and not _pick_ops(clauses[i + 1], None)[0] and not clause_negated(clauses[i + 1]):
            joined = f"{c.rstrip(' .')}, {clauses[i + 1]}"
            out.append(joined)
            merged.add(joined)
            i += 2
            continue
        out.append(c)
        i += 1
    return out, merged


def parse_written(text: str, version: str | None = None) -> ParseResult:
    res = ParseResult(steps=[])
    raw = split_clauses(text)
    clauses: list[str] = []
    prev = None
    for c in raw:
        n = _norm_clause(c)
        if n == prev:
            res.duplicates_removed += 1
            res.warnings.append(f"duplicate instruction removed: '{c}'")
            continue
        prev = n
        clauses.extend(_split_and(c))
    clauses, merged = _merge_key_and_action(clauses)
    mode: str | None = None
    mode_assumed, assumed_idx = False, 0
    name = lambda m: "Edit" if m == "EDIT_MESH" else "Object"
    for c in clauses:
        neg = clause_negated(c)
        ops, resolved = ([], False) if neg else _pick_ops(c, mode)
        if not ops:
            st = Step(id="s00", order=1, goal=c[0].upper() + c[1:], actions=[Action(verb="other")], confidence=0.3, support="unknown",
                      provenance="user_text", source_refs=[f"user:clause {len(res.steps) + 1}"], evidence=[c],
                      flags=(["negated instruction: it says NOT to do something, so it is kept as written and not mapped to an operation"] if neg else
                             ["not in the Blender catalog: shortcuts, menu paths and expected state cannot be validated"])
                            + (["merged: the key press and the action it performs were written as two clauses and are kept as one step"] if c in merged else []))
            res.steps.append(st)
            res.unmatched.append(c)
            continue
        for op in ops:
            tpl: StepT = op.clause
            idx = len(res.steps) + 1
            assumptions: list[str] = []
            flags: list[str] = []
            need = op.needs_mode
            if need:
                if mode is None:
                    assumptions.append(f"Assumes {name(need)} Mode: the instructions do not say how or when it was entered")
                    mode, mode_assumed, assumed_idx = need, True, idx
                elif mode != need:
                    flags.append(f"prerequisite not met: this needs {name(need)} Mode but the steps before it leave you in {name(mode)} Mode; a step may be missing")
                    res.warnings.append(f"step {idx} ('{c}'): " + flags[-1])
                    if mode_assumed and op.sets_mode == mode:
                        res.warnings.append(f"step {assumed_idx} assumed {name(mode)} Mode, but step {idx} is what enters it: the order may be wrong")
                        res.steps[assumed_idx - 1].flags.append(f"order: step {idx} enters the {name(mode)} Mode this step assumed")
            if op.id == "mode.toggle" and mode is None:
                assumptions.append("Tab toggles between modes: the current mode is not stated, so the result is unknown")
            for sc in user_shortcuts(c):
                if op.shortcuts and sc not in {normalise_shortcut(s) for s in op.shortcuts}:
                    flags.append(f"you wrote '{sc}', but the manual gives {', '.join(op.shortcuts)} for this operation (your wording is kept, nothing was changed)")
            for mp in user_menu_paths(c):
                if op.menu_paths and not any(norm(m) in norm(mp) for m in op.menu_paths):   # 'Choose Object > Join' contains 'Object > Join'
                    flags.append(f"menu path '{mp}' does not match the documented path {', '.join(op.menu_paths)}")
            cond = _COND.match(c)
            if cond:
                flags.append(f"conditional step: it only applies if/when {cond.group(1).strip()}, which cannot be checked from the instructions "
                             "(the mode it leaves you in is therefore uncertain)")
            cm = _CLAIM.search(c)
            if cm:
                flags.append(f"stated result '{cm.group(0)[:60]}' cannot be checked: the catalog only knows "
                             f"{'the mode change' if op.sets_mode else 'no observable result'} for this operation")
            vstat, vnote = version_status(op, version)
            if vstat == "incompatible":
                flags.append(vnote)
            conf = 0.85 if (user_shortcuts(c) or user_menu_paths(c)) and not flags else 0.7
            st = make_step(idx, tpl, op, "user_text", goal=c[0].upper() + c[1:], extra_refs=(f"user:clause {idx}",),
                           confidence=conf, assumptions=tuple(assumptions))
            st.evidence = [c]
            st.flags.extend(flags)
            res.steps.append(st)
            res.caveats.extend(x for x in op.caveats if x not in res.caveats)
            for a_ in assumptions:
                if a_ not in res.assumptions:
                    res.assumptions.append(a_)
            if op.sets_mode:
                mode, mode_assumed = op.sets_mode, False
            elif op.id == "mode.toggle" and mode in ("OBJECT", "EDIT_MESH"):
                mode, mode_assumed = ("EDIT_MESH" if mode == "OBJECT" else "OBJECT"), False
    if res.assumptions:
        res.questions.append("The instructions leave some prerequisites unstated: " + "; ".join(res.assumptions) + ". Is that right?")
    return res


def written_to_steplist(text: str, version: str | None = None) -> tuple[StepList, ParseResult]:
    res = parse_written(text, version)
    if not res.steps:
        raise ValueError("no steps found in the text")
    sl = finish(res.steps, "written", version=version)
    return sl, res
