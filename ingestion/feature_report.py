"""Which catalog features a step list teaches, and which prerequisites it silently assumes.

A step's feature is its `feature_id` when set (by the model or a person). Otherwise `terms.suggest_feature` offers a guess, kept apart as
"suggested" and never written onto the step. Prerequisites come from the catalog's dependency graph, so a tutorial that skips "set a rest
pose" before "bind skin" is told so before the learner starts. Reads step lists only; it does not touch any application.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shared.step_record import StepList

from .features import CRAFT_FEATURES, load_catalog
from .terms import suggest_feature


@dataclass
class FeatureReport:
    app: str
    tagged: dict[str, list[str]] = field(default_factory=dict)       # feature id -> step ids, from feature_id
    suggested: dict[str, list[str]] = field(default_factory=dict)    # feature id -> step ids, rule-based guess only
    unmatched: list[str] = field(default_factory=list)               # step ids with no feature
    unknown: list[str] = field(default_factory=list)                 # feature ids on steps that are not in the catalog
    missing_prerequisites: dict[str, list[str]] = field(default_factory=dict)   # feature id -> prerequisite ids no step covers
    craft: list[str] = field(default_factory=list)                   # covered features judged by eye (never graded)
    unsupported: list[str] = field(default_factory=list)             # covered features the app has no tool for

    def render(self) -> str:
        cat = load_catalog()
        name = lambda fid: f"{fid} {cat.get(fid).name}" if fid in cat else fid
        out = [f"app: {self.app}; steps matched to a feature: {sum(map(len, self.tagged.values())) + sum(map(len, self.suggested.values()))}"
               f", unmatched: {len(self.unmatched)}"]
        out += [f"  teaches {name(f)} (steps {', '.join(s)})" for f, s in self.tagged.items()]
        out += [f"  probably teaches {name(f)} (steps {', '.join(s)}; guessed from the wording)" for f, s in self.suggested.items()]
        out += [f"  UNKNOWN feature id {f}" for f in self.unknown]
        out += [f"  {name(f)} is craft: compared by eye, not graded" for f in self.craft]
        out += [f"  {name(f)} has no tool in {self.app}: needs an add-on or a different workflow" for f in self.unsupported]
        for f, miss in self.missing_prerequisites.items():
            out.append(f"  {name(f)} assumes you already did: " + "; ".join(name(m) for m in miss))
        return "\n".join(out)


def feature_report(sl: StepList) -> FeatureReport:
    cat = load_catalog()
    r = FeatureReport(app=sl.app)
    for s in sl.steps:
        if s.feature_id and s.feature_id not in cat:
            r.unknown.append(s.feature_id)
        elif s.feature_id:
            r.tagged.setdefault(s.feature_id, []).append(s.id)
        else:
            guess = suggest_feature(" ".join([s.goal, *(a.ui_element or "" for a in s.actions)]), sl.app)
            if guess:
                r.suggested.setdefault(guess, []).append(s.id)
            else:
                r.unmatched.append(s.id)
    covered = set(r.tagged) | set(r.suggested)
    for fid in [*r.tagged, *r.suggested]:
        if fid in r.missing_prerequisites:
            continue
        miss = [p.id for p in cat.prerequisites(fid) if p.id not in covered]
        if miss:
            r.missing_prerequisites[fid] = miss
    r.craft = sorted(f for f in covered if f in CRAFT_FEATURES)
    r.unsupported = sorted(f for f in covered if cat.get(f).support_code(sl.app) == "U")
    return r
