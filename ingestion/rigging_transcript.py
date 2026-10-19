"""Deterministic reading of a user-supplied transcript for a rigging or animation tutorial in Maya, Houdini or Blender. No model, no network.

Same hard rules as `transcript_ingest` (a transcript says what was SAID: every step is narrated, never demonstrated; times are the cue times and are never
clamped; evidence is the verbatim unit text). The difference is what is recognised: not the Blender modelling catalog but the rigging feature catalog.
A spoken unit becomes a step when it contains an action cue AND either names one catalog feature clearly (`terms.suggest_feature`) or says to create a
node type the application profile knows ("let's create an IK handle", "add a rig doctor"). Anything else stays an explanation or an unmatched unit,
never a guessed step. Neighbouring units about the same feature are merged into one step.
"""
from __future__ import annotations

import re

from shared.answer import Explanation
from shared.step_record import Action, HowTo, StatePredicate, Step, StepList

from .features import load_catalog
from .instructions import speech_details
from .profiles import get_profile
from .rigging_discovery import _AREA_WORDS
from .rigging_text import _created_nodes
from .scene_chain import derive_state, flag_order_errors
from .terms import suggest_feature
from .transcript_ingest import TranscriptResult, Unit, clean_cues, cue_span, group_units, parse_timed_text
from .validate import check_structure, sanitize_and_annotate

# speech about doing something, in rigging vocabulary as well as the general cues
_ACTION = re.compile(r"\b(?:create|creating|add|adding|insert|make|making|build|place|put|select|click|go to|use|using|set|setting|bind|binding|paint|painting|"
                     r"mirror|orient|parent|constrain|key|keyframe|bake|export|import|rotate|move|drag|draw|name|rename|let'?s|we'?ll|we'?re going to|"
                     r"i'?m going to|you can|you'?ll|want to|have to|need to|go ahead)\b", re.I)
_FILLER = re.compile(r"^(?:(?:okay|ok|so|now|alright|right|well|and|then|next|first|also|just|um|uh|yeah|guys|everyone|hello|hi)\b[,.\s]*)+", re.I)
_CHATTER = re.compile(r"\b(?:welcome|in this (?:video|tutorial|lesson)|(?:show|showing) you how to|going to (?:show|assume)|i (?:will|am going to) be (?:showing|using)|hope (?:that|this)|let me know|thanks? for watching|subscribe|see you|last (?:video|tutorial)|previous (?:video|tutorial)|went over|we (?:learned|covered|went)|assume (?:that )?you (?:do )?know|any questions|in the description|check out)\b", re.I)
_TESTING = re.compile(r"\b(?:let\'?s test|to test|test (?:it|this|the|out)|check (?:if|that|whether)|just check|make sure (?:it|that|everything) (?:is )?(?:working|works)|you\'?ll notice|you will notice|see (?:if|that) it works|works (?:like|as|correctly)|now if i|if i (?:go|move|grab|take|click)|you can see|as you can see)\b", re.I)
MERGE_GAP_S = 15.0
EDGE_S = 45.0                       # the first and last seconds of a video, where greetings, recaps and sign-offs live
# a spoken unit often holds several instructions ("create a joint chain now go to skeleton and orient joint"): cut it where the speaker moves on
_BOUNDARY = re.compile(r"(?<=[.!?;])\s+|\b(?:and then|and now|then|next|now|after that|afterwards|finally)\b[,\s]*", re.I)
_VERSION_WORDS = re.compile(r"\b(?:old(?:er)? versions?|previous versions?|earlier versions?|used to|no longer|legacy|deprecated)\b", re.I)


def _trim(text: str, n: int = 160) -> str:
    t = _FILLER.sub("", " ".join(text.split())).strip(" ,.;")
    if len(t) > n:
        cut = t[:n]
        end = max(cut.rfind(". "), cut.rfind("? "))
        t = cut[:end + 1] if end > 60 else cut.rsplit(" ", 1)[0] + "..."
    return t[:1].upper() + t[1:]


def _matches(text: str, app: str) -> bool:
    return bool(_created_nodes(text, app)) or (any(rx.search(text) for rx in _AREA_WORDS.values()) and suggest_feature(text, app) is not None)


def _segments(u: Unit, app: str) -> list[tuple[str, float, float, str]]:
    """(text, start, end, verbatim cue text) for each instruction-sized piece of a unit; times come from the cues the piece sits in.
    Cut at every caption boundary and wherever the speaker moves on ("then", "next", "now" ...), then glue a piece that matches nothing back onto the
    piece before it, so an instruction split across two captions ("create a joint" / "chain for the leg") is whole again."""
    flat = " ".join(u.text.split())
    cuts = {0, len(flat)}
    pos = 0
    for _, _, t in u.spans:                                     # caption boundaries, in the same coordinates cue_span uses
        pos += len(" ".join(t.split())) + 1
        cuts.add(min(pos, len(flat)))
    cuts |= {m.end() if m.group(0).strip(" ,.;!?") == "" else m.start() for m in _BOUNDARY.finditer(flat)}
    pieces: list[list] = []
    cl = sorted(cuts)
    for a, b in zip(cl, cl[1:]):
        seg = flat[a:b].strip(" ,.;")
        if not seg:
            continue
        if pieces and not _matches(seg, app) and len(seg) < 90 and not _CHATTER.search(seg):
            pieces[-1][0] += " " + seg
            pieces[-1][2] = b
        else:
            pieces.append([seg, a, b])
    out = []
    for seg, a, b in pieces:
        t0, t1, said = cue_span(u, a, b)
        out.append((seg, t0, t1, said))
    return out or [(flat, u.start, u.end, u.text)]


def _cues(said: str, app: str, version: str | None) -> list[str]:
    from .rigging_discovery import _VERSION
    out = []
    for m in _VERSION[app].finditer(said):
        if version is None or m.group(1).split(".")[0] != version.split(".")[0]:
            out.append(f"version cue: the speaker mentions {app} {m.group(1)} here; this step may be different in your version")
    if not out and (w := _VERSION_WORDS.search(said)):
        out.append(f"version cue: the speaker contrasts this with another version ('{w.group(0)}'); this step may be different in your version")
    return out


def ingest_rigging_transcript(text: str, app: str, *, duration_s: float | None = None, version: str | None = None,
                              video_id: str | None = None, title: str | None = None) -> TranscriptResult:
    cat = load_catalog()
    cues, cstats = clean_cues(parse_timed_text(text, duration_s))
    units = group_units(cues)
    steps: list[Step] = []
    expl: list[Explanation] = []
    unmatched: list[Unit] = []
    for u in units:
        for text_, t0, t1, said in _segments(u, app):
            nodes = _created_nodes(text_, app)
            # free speech shares many words with catalog names ("edit mode ... move"): a piece must also use rigging/animation vocabulary to count
            fid = suggest_feature(text_, app) if any(rx.search(text_) for rx in _AREA_WORDS.values()) else None
            edge_s = min(EDGE_S, 0.1 * duration_s) if duration_s else EDGE_S             # 10% of a short clip, at most 45 s
            edge = t0 < edge_s or (duration_s is not None and t0 > duration_s - edge_s)
            if _CHATTER.search(text_) and (edge or fid is None):             # intro, outro, recap, "I assume you know ...": talk, not an instruction (only at the ends, or when it names no feature)
                expl.append(Explanation(text=text_, provenance="transcript_rules", start_s=t0, end_s=t1))
                continue
            if _TESTING.search(text_) and steps and not nodes and (fid is None or fid == steps[-1].feature_id):     # "now if I move it you can see ...": how to CHECK the previous step, not a new step
                steps[-1].check.append(HowTo(text=_trim(text_), support="said", evidence=said[:240]))
                continue
            if not _ACTION.search(text_):
                if fid:
                    expl.append(Explanation(text=text_, provenance="transcript_rules", start_s=t0, end_s=t1))     # talks about a feature, tells you to do nothing
                else:
                    unmatched.append(Unit(t0, t1, text_, [(t0, t1, said)]))
                continue
            if not fid and not nodes:
                unmatched.append(Unit(t0, t1, text_, [(t0, t1, said)]))
                continue
            prev = steps[-1] if steps else None
            if prev is not None and fid and prev.feature_id == fid and prev.video_end_s is not None and t0 - prev.video_end_s <= MERGE_GAP_S:
                prev.video_end_s = t1                                    # the same feature carried on across neighbouring pieces
                prev.evidence.append(said[:240])
                prev.source_refs.append(f"transcript:{t0:g}-{t1:g}s")
                continue
            goal = cat.get(fid).name if fid else _trim(text_)
            st = Step(
                id=f"s{len(steps) + 1:02d}", order=len(steps) + 1, goal=goal, feature_id=fid, support="narrated", provenance="transcript_rules", confidence=0.5,
                actions=[Action(verb="other", value=_trim(text_, 80))], evidence=[said[:240]], video_start_s=t0, video_end_s=t1,
                source_refs=[f"transcript:{t0:g}-{t1:g}s"],
                expected_state=[StatePredicate(kind="node_exists", target=t) for t in nodes],
                assumptions=["Narrated only: nothing here shows the action was performed on screen.",
                             *(["The matching catalog feature is a guess from the wording."] if fid else [])],
                flags=[] if fid else ["not matched to a known rigging feature: kept as spoken and not validated against the catalog"])
            acts, lines = speech_details(said, app)                         # menu paths and settings the speaker names, from the piece's own captions
            st.actions += acts
            st.how_to += lines
            st.flags += _cues(text_, app, version)
            steps.append(st)
    res = TranscriptResult(steplist=None, explanations=expl, unmatched_units=unmatched, stats={
        **cstats, "cues_in": len(cues), "units": len(units), "steps": len(steps), "explanation_units": len(expl), "unmatched_units": len(unmatched),
        "app": app}, limitations=[
        "A transcript cannot show what was done on screen: demonstrated-only actions are not produced.",
        f"Only operations that name a rigging/animation catalog feature, or a node type known for {app}, become steps; other speech is listed as unmatched.",
        "Step start and end times are the span of the matched transcript unit, not the moment the action happened."])
    if steps:
        sl = StepList(source_type="transcript", app=app, app_version_tutorial=version, title=title, steps=steps, prompt_version="deterministic-rigging-transcript-v1",
                      video_duration_s=duration_s, video_id=video_id)
        derive_state(sl)
        sanitize_and_annotate(sl, get_profile(app), duration_s)
        check_structure(sl, duration_s)
        res.limitations += [f"order: {e}; the narration may skip a step or go out of order" for e in flag_order_errors(sl).order_errors]
        res.steplist = sl
    return res
