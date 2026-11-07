"""Written rigging and animation instructions (Blender, Maya, Houdini) to shared-schema steps. Rules only; no model, no network.

The user's own wording stays as each step's goal. Each clause is matched to a catalog feature only when one is clearly the best match
(`terms.suggest_feature`); an unmatched clause is still a step, flagged as unvalidated. A clause that says to create a node of a type the
application's profile knows ("Create an IK handle", "Add a Rig Doctor") expects that node to exist afterwards. Nothing is invented: no step
is added that the text does not contain. Validation, craft marking, version notes and the unsupported-feature flags come from the validator.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from shared.step_record import Action, StatePredicate, Step, StepList

from .feature_report import feature_report
from .features import load_catalog
from .intent import split_clauses
from .profiles import get_profile, norm
from .scene_chain import derive_state, flag_order_errors
from .terms import suggest_feature
from .text_steps import user_menu_paths
from .validate import check_structure, sanitize_and_annotate

MIN_CLAUSES = 2                     # one line is a question, not a procedure
_CREATE = re.compile(r"\b(?:create|add|insert|make|build|place)\b", re.I)


@dataclass
class RiggingResult:
    unmatched: list[str] = field(default_factory=list)        # clauses with no catalog feature
    assumptions: list[str] = field(default_factory=list)      # prerequisites the text never covers
    caveats: list[str] = field(default_factory=list)


def clauses_of(text: str) -> list[str]:
    """Each non-empty line, split further at sentence ends and 'then'; numbering and bullets removed."""
    return [c for line in text.splitlines() if line.strip() for c in split_clauses(line)]


def looks_like_rigging(text: str, app: str) -> bool:
    """A procedure (2+ clauses) in which at least half the clauses clearly name a catalog feature."""
    cl = clauses_of(text)
    return len(cl) >= MIN_CLAUSES and sum(suggest_feature(c, app) is not None for c in cl) * 2 >= len(cl)


def _node_words(node: str) -> str:
    """How a person says a node type. Maya camelCase (ikHandle -> "ik handle"), Houdini labels (Rig Doctor), and Blender identifiers: ARMATURE -> "armature",
    CONSTRAINT_IK -> "ik constraint", MODIFIER_ARMATURE -> "armature modifier" (the prefixes only keep Blender's same-named things apart)."""
    if node.isupper() or "_" in node:
        for prefix, suffix in (("CONSTRAINT_", "constraint"), ("MODIFIER_", "modifier")):
            if node.startswith(prefix):
                return norm(f"{node[len(prefix):].replace('_', ' ')} {suffix}")
        return norm(node.replace("_", " "))
    return norm(re.sub(r"(?<!^)(?=[A-Z])", " ", node))          # ikHandle -> "ik handle", Rig Doctor -> "rig doctor"


_TARGET_PREPS = frozenset("to on onto of for from in into at under over after before between using".split())


def _made(tokens: list[str], phrase: str) -> bool:
    """The clause names this node type somewhere other than as the target of a preposition ("add an IK constraint to the bone" makes a constraint, not a bone)."""
    want = phrase.split()
    n = len(want)
    for i in range(len(tokens) - n + 1):
        if tokens[i:i + n] == want or (tokens[i:i + n - 1] == want[:-1] and tokens[i + n - 1] == want[-1] + "s"):
            if not _TARGET_PREPS & set(tokens[max(0, i - 3):i]):          # "to the lower bone": a preposition within three words before it
                return True
    return False


def _created_nodes(clause: str, app: str) -> list[str]:
    if not _CREATE.search(clause):
        return []
    words = f" {norm(clause)} "
    tokens = words.split()
    hits = {n: _node_words(n) for n in get_profile(app).nodes if _made(tokens, _node_words(n))}
    # "add an armature modifier" says a modifier, not an armature object: drop a match whose words sit inside a longer match
    return sorted(n for n, w in hits.items() if not any(m != n and f" {w} " in f" {mw} " for m, mw in hits.items()))


def prerequisite_notes(sl: StepList) -> tuple[list[str], list[str]]:
    """(assumptions, caveats): what the steps assume was already done, and features the application has no tool for."""
    rep = feature_report(sl)
    cat = load_catalog()
    return (["The steps assume you already did: " + "; ".join(f"{m} {cat.get(m).name}" for m in rep.all_missing)] if rep.all_missing else [],
            [f"{cat.get(f).id} has no tool in {sl.app}: the instructions need an add-on or a different workflow" for f in rep.unsupported])


def rigging_to_steplist(text: str, app: str, version: str | None = None) -> tuple[StepList, RiggingResult]:
    cl = clauses_of(text)
    if len(cl) < MIN_CLAUSES:
        raise ValueError("a procedure needs at least two steps; put each step on its own line")
    steps, res = [], RiggingResult()
    for n, c in enumerate(cl, 1):
        fid = suggest_feature(c, app)
        if fid is None:
            res.unmatched.append(c)
        menus = user_menu_paths(c)
        steps.append(Step(
            id=f"s{n:02d}", order=n, goal=c, feature_id=fid, support="narrated", evidence=[c], provenance="user_text", confidence=0.6,
            source_refs=[f"text:clause{n}"], actions=[Action(verb="open_menu", ui_element=m) for m in menus],
            expected_state=[StatePredicate(kind="node_exists", target=t) for t in _created_nodes(c, app)],
            flags=[] if fid else ["not matched to a known rigging feature: kept as written and not validated against the catalog"]))
    sl = StepList(source_type="written", app=app, app_version_tutorial=version, steps=steps, prompt_version="deterministic-rigging-v1")
    derive_state(sl)
    sanitize_and_annotate(sl, get_profile(app))
    check_structure(sl)
    res.assumptions, res.caveats = prerequisite_notes(sl)
    res.caveats += [f"order: {e}; check the order of your steps" for e in flag_order_errors(sl).order_errors]
    if res.unmatched:
        res.caveats.append(f"{len(res.unmatched)} of {len(cl)} steps were not matched to a known feature and stay unvalidated")
    return sl, res
