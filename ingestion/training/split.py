"""Group-aware, deterministic train/dev/test split with a leakage audit. Pure functions, no I/O.

Rule: a whole group (one tutorial video, one manual page, one synthetic scene template family) lands in exactly one
split. Splitting by example would put clips of the same tutorial, or near-duplicate synthetic variants, on both sides.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Iterable

from .example import TrainingExample

SPLITS = ("train", "dev", "test")


def _bucket(group_key: str, salt: str) -> float:
    h = hashlib.sha256(f"{salt}|{group_key}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64


def assign_groups(group_keys: Iterable[str], fractions=(0.7, 0.15, 0.15), salt: str = "guidewire-v1") -> dict[str, str]:
    if abs(sum(fractions) - 1.0) > 1e-9:
        raise ValueError("fractions must sum to 1")
    out = {}
    for g in sorted(set(group_keys)):
        b, acc = _bucket(g, salt), 0.0
        for name, f in zip(SPLITS, fractions):
            acc += f
            if b < acc:
                out[g] = name
                break
        else:
            out[g] = SPLITS[-1]
    return out


def split_examples(examples: list[TrainingExample], fractions=(0.7, 0.15, 0.15), salt: str = "guidewire-v1"):
    """Returns {split: [examples]}. Dev/test keep only eval-eligible examples; the rest of those groups are dropped
    from evaluation rather than moved to train (moving them would leak the group)."""
    assignment = assign_groups((e.group_key for e in examples), fractions, salt)
    out = {s: [] for s in SPLITS}
    for e in examples:
        s = assignment[e.group_key]
        if s != "train" and not e.eval_eligible:
            continue
        out[s].append(e)
    return out


def find_leaks(splits: dict[str, list[TrainingExample]]) -> list[str]:
    """Audit: group keys that appear in more than one split, and identical inputs across splits."""
    problems, seen_group, seen_text = [], defaultdict(set), defaultdict(set)
    for name, items in splits.items():
        for e in items:
            seen_group[e.group_key].add(name)
            if e.input_text:
                seen_text[hashlib.sha256(e.input_text.strip().lower().encode()).hexdigest()].add(name)
    problems += [f"group {g!r} in {sorted(s)}" for g, s in seen_group.items() if len(s) > 1]
    problems += [f"identical input text in {sorted(s)}" for s in seen_text.values() if len(s) > 1]
    return problems
