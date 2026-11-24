"""Finer steps without new words: a step with several how-to lines becomes one step per line (audit I-1).

The extraction prompt gives each step 1 to 3 how-to lines ("Press Tab, place the node", "Connect it", "Set Name to base"). Those lines are already about one per labelled action in Blender
and Maya, so showing each line as its own step gives the finer steps without a model call and without writing anything new:

  - every new step's goal is the original how-to line, word for word (with its support and evidence);
  - the original step's goal becomes the display group label of its parts (schema 0.12 group_id / group), so nothing is lost and nothing is re-worded;
  - `why`, "Watch out" notes, alternatives and version notes stay with the FIRST part (the learner reads them before acting); `result`, `check` and `expected_state` (what GuideWire
    verifies) stay with the LAST part, because that is when the whole original step has been done; `start_state` stays with the first part;
  - actions are shared out by order and by words: each action goes to the line that mentions its element, value or key, never moving backwards (a monotonic alignment);
  - times are the original step's range on every part: no per-line time exists, and none is invented;
  - ids and orders are renumbered, `depends_on` follows the original step's LAST part.

A step with fewer than two how-to lines is left exactly as it is. Nothing here calls a model or the network.

    finer = split_steps(step_list)
"""
from __future__ import annotations

import re

from shared.step_record import Action, Step, StepList

MAX_LABEL = 80
_WORD = re.compile(r"[a-z0-9_*.]+")
_STOP = frozenset("the a an and or to of in on at it its is this that then with for from into as by be your you press click select set type enter open use".split())
_KEY_WORDS = {"space": ("space", "spacebar"), "ctrl": ("ctrl", "control"), "control": ("ctrl", "control"), "return": ("enter", "return"), "enter": ("enter", "return")}
_VERB_WORDS = {"press_keys": ("press", "hit"), "drag": ("drag", "connect", "wire", "move"), "open_menu": ("menu", "open"), "set_value": ("set", "type", "enter", "name"), "select": ("select", "choose", "pick"), "click": ("click", "place", "press")}
_EPS = 0.01          # how strongly an action with no matching words is pulled toward the position it would have if actions and lines were spread evenly


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 0}


def _action_words(a: Action) -> set[str]:
    out = _words(" ".join(filter(None, [a.ui_element, a.value])))
    for k in a.keys:
        k = k.lower()
        out.update(_KEY_WORDS.get(k, (k,)))
    return out


def _score(a: Action, line_words: set[str], line_text: str) -> float:
    s = float(len(_action_words(a) & line_words))
    low = line_text.lower()
    if s and any(v in low for v in _VERB_WORDS.get(a.verb, ())):
        s += 0.25                                                  # the verb agrees with a line that already shares words with the action: a tie-breaker only
    return s


def _units(actions: list[Action]) -> list[list[int]]:
    """Indexes of the actions, in order, with typing into a search box kept with the action before it: `set_value` with no element is what a learner types after pressing Tab
    (Houdini's node menu) or opening a menu, so it belongs to the same line as that action."""
    units: list[list[int]] = []
    for i, a in enumerate(actions):
        if units and a.verb == "set_value" and not a.ui_element and actions[units[-1][-1]].verb in ("press_keys", "open_menu", "click"):
            units[-1].append(i)
        else:
            units.append([i])
    return units


def assign_actions(actions: list[Action], lines: list[str]) -> list[int]:
    """For each action (in order) the index of the line it belongs to. Order-preserving: an action never goes to an earlier line than the action before it."""
    if not actions or not lines:
        return []
    units, m = _units(actions), len(lines)
    n = len(units)
    lw = [_words(t) for t in lines]
    best = [[0.0] * m for _ in range(n)]
    back = [[0] * m for _ in range(n)]
    for i, u in enumerate(units):
        for j in range(m):
            gain = sum(_score(actions[x], lw[j], lines[j]) for x in u) - _EPS * abs((i + 0.5) / n - (j + 0.5) / m)
            if i == 0:
                best[i][j], back[i][j] = gain, -1
            else:
                k = max(range(j + 1), key=lambda x: (best[i - 1][x], x))      # on a tie, stay on the later line
                best[i][j], back[i][j] = best[i - 1][k] + gain, k
    j = max(range(m), key=lambda x: (best[n - 1][x], x))
    unit_line = [0] * n
    for i in range(n - 1, -1, -1):
        unit_line[i] = j
        j = back[i][j]
    out = [0] * len(actions)
    for u, line in zip(units, unit_line):
        for x in u:
            out[x] = line
    return out


def _label(goal: str) -> str:
    goal = " ".join(goal.split())
    if len(goal) <= MAX_LABEL:
        return goal
    cut = goal[: MAX_LABEL - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return cut + "…"


_PREPARATION = re.compile(r"^\s*(?:(?:hold\s+)?shift[- ]?\s*)?(?:and\s+)?select\b|^\s*click\s+(?:on\s+)?the\s+\w+(?:\s+\w+)?\s+(?:bone|joint|mesh|object|controller)\b", re.I)


_NOT_AN_OBJECT = re.compile(r"\b(tool|menu|mode|tab|panel|dropdown|option|button|checkbox|field|constraint|modifier|node|parameter|press|hit|type|move|drag|rotate|scale|extrude|set|enter|parent|clear|add|delete|duplicate|rename|name)\b", re.I)      # selecting one of these is the action itself, and a line that also does something is not only a selection


_ONLY_OPENS = re.compile(r"^\s*(?:click|open)\s+(?:on\s+)?(?:the\s+)?(?:mode\s+)?(?:selector|dropdown|drop-down|menu|tab)\b", re.I)
_ALSO_DOES = re.compile(r"\b(select|choose|pick|set|type|enter|check|uncheck|expand|drag|move)\b", re.I)


def _is_preparation(text: str) -> bool:
    """A line that only gets something selected ("Select the foot bone", "Shift-select the foot IK controller bone"). It belongs to the action that comes after it: "select X, then Shift-select Y, then press Ctrl+P"
    is one thing to do, and cutting it after the selection leaves the next step starting "press Ctrl+P on it"."""
    if _ONLY_OPENS.match(text) and not _ALSO_DOES.search(text):
        return True                                                  # "Click the Mode selector in the upper left header." opens what the next line chooses from: one operation
    return bool(_PREPARATION.match(text)) and ">" not in text and not _NOT_AN_OBJECT.search(text)


def _parts_of_lines(owner: list[int], n_lines: int, findable: list[bool], texts: list[str] | None = None) -> list[list[int]]:
    """The lines of a step in parts, in order. Each line starts a part, but a part with no action that names something (a menu, tool, field, node, a key with a menu way, a typed value) has nothing to point
    at on screen. Such a part is joined to the part AFTER it when it is only a selection (it prepares what follows), otherwise to the part before it; at the very start it waits for the part after it, at the very
    end it joins the part before. Lines are never reordered or dropped."""
    has = [any(o == j and f for f, o in zip(findable, owner)) for j in range(n_lines)]
    out: list[list[int]] = []
    carry: list[int] = []
    for j in range(n_lines):
        prep = texts is not None and _is_preparation(texts[j])
        if prep and j < n_lines - 1:                                # a selection never ends a part: it is the start of the part that follows (whatever action the words were matched to)
            carry.append(j)
        elif has[j]:
            out.append(carry + [j])
            carry = []
        elif not out:
            carry.append(j)
        else:
            out[-1] = out[-1] + [j]
    if carry:
        if out:
            out[-1] = out[-1] + carry                               # a selection at the very end of the step: nothing follows it, so it stays with what came before
        else:                                                       # no line has an action: nothing to point at anywhere, the step stays whole
            return [list(range(n_lines))]
    return out


def split_step(step: Step, findable: list[bool] | None = None) -> list[Step]:
    """The parts of one step, or [step] when it has fewer than two how-to lines or only one part would remain. A part is one how-to line, or several when the lines between actions
    have nothing to point at. ids and orders are placeholders: split_steps renumbers them."""
    lines = step.how_to
    if len(lines) < 2:
        return [step]
    owner = assign_actions(step.actions, [h.text for h in lines])
    flags = findable if findable is not None and len(findable) == len(step.actions) else [_words_findable(a) for a in step.actions]
    groups = _parts_of_lines(owner, len(lines), flags, [h.text for h in lines])
    if len(groups) < 2:
        return [step]
    last = len(groups) - 1
    parts: list[Step] = []
    for k, idx in enumerate(groups):
        first, final = k == 0, k == last
        parts.append(step.model_copy(update={
            "goal": lines[idx[0]].text,
            "actions": [a for a, o in zip(step.actions, owner) if o in idx],
            "how_to": [lines[j] for j in idx],
            "start_state": step.start_state if first else [],
            "expected_state": step.expected_state if final else [],
            "check": step.check if final else [],
            "result": step.result if final else None,
            "why": step.why if first else None,
            "common_mistakes": step.common_mistakes if first else [],
            "alternatives": step.alternatives if first else [],
            "version_dependent": step.version_dependent if first else [],
            "verification": step.verification if final else None,
            "verifiable": bool(step.expected_state) and final and step.kind == "mechanics",    # derived at validation, which model_copy skips: set it here
            "depends_on": step.depends_on if first else [],
            "group_id": None, "group": None,                       # set by split_steps, which knows the numbering
            "evidence": list(step.evidence),
            "flags": list(step.flags),
        }, deep=True))
    return parts


_GROUNDED = ("tool", "menu", "mode", "property", "sidebar", "operator_panel", "context_menu", "node", "parm", "pane")   # what the guide's grounders can locate on screen (the same list as app/step_state.GROUNDED_KINDS)


def _words_findable(a: Action) -> bool:
    """An action the resolver did not (or cannot) resolve is worth finding only when its words are a menu path to look for: two or more names, or one name that is opened as a menu. One name that
    is not a menu ("Bone", a handle) is something in the 3D view that the guide describes in words only (the rule app/step_state.text_target applies)."""
    ui = (a.ui_element or "").replace("›", ">").replace("→", ">")
    path = [x for x in (p.strip() for p in ui.split(">")) if x]
    return bool(path) and (len(path) > 1 or a.verb == "open_menu")


def _findable(sl: StepList) -> dict[str, list[bool]]:
    """For each step id, per action: can the guide point at it on screen? It is what a part must have to be worth a step of its own. Blender and Houdini actions are resolved against the application's
    own interface (the resolver the session runs on load) and are findable when the result is something a grounder can locate; a key press or a drag in the viewport is not. Maya has no screen
    guidance yet, so any action counts there. The steps themselves are not changed: resolved targets are never stored."""
    try:
        if sl.app == "blender":
            from ingestion.targets import resolve_steps
            resolved = resolve_steps(sl.steps)
        elif sl.app == "houdini":
            from ingestion.targets_houdini import resolve_steps as resolve_houdini
            resolved = resolve_houdini(sl.steps)
        else:
            return {s.id: [True] * len(s.actions) for s in sl.steps}       # Maya: the guide has no way to point at the screen yet, so a part only needs an action
    except Exception:
        return {}
    return {r.id: [_action_findable(a, next((p.target for p in r.start_state if p.kind == "mode"), None)) for a in r.actions] for r in resolved}


_MODE_OPERATORS = ("object.mode_set", "object.mode_set_with_submode", "object.editmode_toggle", "object.posemode_toggle")


def _action_findable(a: Action, mode: str | None) -> bool:
    """One resolved action: something the grounders can locate, or a key press that has a menu or the mode dropdown as its other way (G, R, S, E and Tab all do): the guide points at that way, so a part made of
    it is worth a step. A bare modifier or a key with no menu way is not."""
    t = a.target
    if t is None:
        return _words_findable(a)
    if t.kind in _GROUNDED:
        return True
    if t.kind == "keys" and t.operator:
        if t.operator in _MODE_OPERATORS:
            return True
        from shared import menu_routes
        return menu_routes.alternative_for_keys(a.keys, t.operator, mode) is not None
    return False


def split_steps(sl: StepList) -> StepList:
    """The step list with every multi-line step split into one step per line. The original goals become the groups. Unchanged when no step has two or more lines."""
    if not any(len(s.how_to) >= 2 for s in sl.steps):
        return sl
    flags = _findable(sl)
    new: list[Step] = []
    last_of: dict[str, str] = {}                                    # original step id -> id of its last part
    pending_deps: list[tuple[int, list[str]]] = []
    group_no = 0
    for st in sl.steps:
        parts = split_step(st, flags.get(st.id))
        group_no += 1
        label = _label(st.goal)
        for k, p in enumerate(parts):
            idx = len(new)
            nid = f"s{idx + 1:02d}"
            p = p.model_copy(update={"id": nid, "order": idx + 1})
            if len(parts) > 1 or st.group_id:
                p = p.model_copy(update={"group_id": f"g{group_no:02d}", "group": label})
            if p.depends_on:
                pending_deps.append((idx, p.depends_on))
            new.append(p)
        last_of[st.id] = new[-1].id
    for idx, deps in pending_deps:
        mapped = [last_of.get(d, d) for d in deps]
        mapped = [d for d in mapped if d != new[idx].id]
        new[idx] = new[idx].model_copy(update={"depends_on": mapped})
    # a lone step between groups keeps no group of its own unless it had one: groups must be runs of consecutive steps with ONE label, which this numbering guarantees
    n_parts = len(new)
    return sl.model_copy(update={"steps": new, "warnings": [*sl.warnings, f"steps split into finer steps for display: {len(sl.steps)} steps became {n_parts}"]})
