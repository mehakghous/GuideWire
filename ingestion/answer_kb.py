"""Extended answering over the local knowledge base. Returns an AnswerBundle, or None to let the catalog logic in router.py decide.

Pathways, in the order they are considered (an evaluated policy, not a fixed pipeline; each choice is recorded in `bundle.reasons`):
  1. import_tutorial   a tutorial URL to turn into steps: NOT answerable offline (needs a transcript or a video model); options listed
  2. find_tutorial     explicit request for a tutorial/course, or a project goal ("make a low-poly model"): curated-index discovery
  3. ask_state         "option is missing / greyed out / can't edit": depends on the user's state: documented context + questions
  4. (None)            a known catalog operation: the catalog path in router.py answers it with a reviewed-quality entry
  5. docs_index        concept or how-to from the local manual index: excerpt with attribution, or a Reference-block candidate procedure
  6. outside_index     the manual documents it but it is not in the local index: official page pointers, no model, no network
  7. clarify / decline too vague, or nothing in Blender's documentation matches
Nothing here calls the network or a model. `needs` states what a next step would require.
"""
from __future__ import annotations

import re

from shared.answer import AnswerBundle, Explanation, SourceRef

from .catalog import BY_ID, match_aliases, parse_version
from .intent import Intent
from .kb.candidates import Candidate, candidate_from_hit, candidate_steps, extra_profile, validate_candidate
from .kb.index import Hit, KnowledgeBase, SearchResult, terms
from .knowledge import finish
from .profiles import BLENDER
from . import tutorials as T
from . import handoff as H

LICENCE = "CC-BY-SA 4.0; credit: Blender Documentation Team"
# words that describe a judgement or a feeling rather than a Blender topic: a request made only of these needs a question back
VAGUE = frozenset({"better", "right", "good", "bad", "wrong", "nice", "look", "looks", "looked", "work", "works", "working", "help", "issue", "problem",
                   "thing", "things", "stuff", "again", "fix", "correctly", "properly", "different", "same", "like"})
_URL = re.compile(r"https?://\S+")
_YT = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})")
_IMPORT = re.compile(r"\b(turn|convert|make|import|transform|build)\b.*\b(tutorial|video|workflow|steps?)\b|\bthis (tutorial|video)\b", re.I)
_FIND = re.compile(r"\b(tutorials?|courses?|lessons?|learning (?:plan|path)|recommend|teach me|find me|walk me through|guide me while|follow along|"
                   r"learn (?:blender|how))\b", re.I)
_COMPOSITE = re.compile(r"^(?:how (?:do|can|could|would|should) (?:i|we|you)|how to|i want to|i'd like to|show me how to)\s+"
                        r"(make|create|build|model|design|craft|texture|rig|animate)\b", re.I)
_STATE = re.compile(r"\b(missing|greyed out|grayed out|disabled|unavailable|not (?:showing|available|appearing|working)|isn'?t (?:working|showing|available)|"
                    r"doesn'?t (?:appear|show|work)|does nothing|nothing happens|has no effect|no effect|disappeared|can'?t\s+(?:i\s+)?(?:edit|find|see|select)|cannot\s+(?:i\s+)?(?:edit|find|see|select)|won'?t (?:let|work|edit))\b", re.I)
# A message that only makes sense with a procedure in progress or a screen we cannot see. Without session state it is answered with a
# question; matching it to a manual page by a stray word ("action", "screen") produced irrelevant "official page" pointers.
_FOLLOWUP = re.compile(r"\b(where i left off|pick up where|continue (?:from|with|where)|carry on|what(?:'s| is) next|next step|"
                       r"(?:that|this|the last|the previous) (?:action|step|command|thing)|"
                       r"(?:i'?m|i am) (?:stuck|lost|following)|following (?:these|this|the|your) (?:instructions|steps|tutorial|video)|"
                       r"(?:screen|interface|ui|layout|window) (?:looks?|is|seems?) (?:different|wrong|odd|not the same)|looks different|"
                       r"(?:didn'?t|did not|doesn'?t|does not|won'?t) (?:work|do anything))\b", re.I)
_DIFF = re.compile(r"\b(difference between|differ|versus|vs\.?|compare|compared to)\b", re.I)
_CONCEPT = re.compile(r"^(what('s| is| are| does| do)|explain|define|tell me about|describe)\b", re.I)
_HOWTO = re.compile(r"^(how (do|can|could|would|should)|how to|show me|steps? (to|for)|where (is|do|can))\b", re.I)


def _src(h: Hit, retrieved: str) -> SourceRef:
    return SourceRef(kind="manual", title=f"Blender Manual: {h.title}", url=h.url,
                     version=("main (current manual, Blender 5.x)" if h.branch == "main" else h.branch), verified_on=retrieved, licence=LICENCE)


def version_note(version: str | None, branch: str = "main") -> str | None:
    pv = parse_version(version)
    if pv is None:
        return None
    if pv < (2, 93):
        return (f"The local index was read from the current manual (main). No manual branch older than 2.93 exists, so your Blender {version} "
                "could not be checked: menus and shortcuts may differ.")
    if pv[0] < 5:
        return f"The local index was read from the current manual (main, Blender 5.x); Blender {version} may differ in menus, names and options."
    return None


OLD_BRANCH = "blender-v2.93-release"


def _differs(a: Hit, b: Hit) -> bool:
    ra, rb = a.reference or {}, b.reference or {}
    return (ra.get("menus"), ra.get("shortcuts"), ra.get("modes")) != (rb.get("menus"), rb.get("shortcuts"), rb.get("modes"))


def _excerpt(h: Hit, retrieved: str, applies: list[str] | None = None) -> Explanation:
    return Explanation(text=h.lead, sources=[_src(h, retrieved)], provenance="documentation", is_excerpt=True, applies_to_steps=applies or [])


def _retrieved(kb: KnowledgeBase) -> str:
    try:
        import json
        from .kb.fetch import MANIFEST
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
        return m["branches"].get("main", {}).get("retrieved", "unknown")
    except Exception:
        return "unknown"


def answer_extended(text: str, it: Intent, kb: KnowledgeBase | None, tut_index: list[dict] | None, version: str | None,
                    observed: dict | None) -> AnswerBundle | None:
    t = text.strip()
    reasons = list(it.reasons)
    ret = _retrieved(kb) if kb is not None else "unknown"

    # ---- 1. import a tutorial
    urls = H.find_urls(t)
    if urls and (_IMPORT.search(t) or _FIND.search(t) or len(_URL.sub("", t).split()) <= 6 or not _YT.search(t)):
        info = H.classify_url(urls[0])
        if info.kind == "youtube_playlist":
            return AnswerBundle(
                kind="tutorial_recommendation", route="tutorial_import", trust="none", needs=["network", "user_selection"],
                explanations=[Explanation(text="This is a playlist. Its video list can be read through the official YouTube Data API (about 1 quota unit per 50 videos); "
                                               "you then pick the video(s) to convert. I have not contacted YouTube.", provenance="catalog_template")],
                caveats=["A playlist is not one tutorial: each video is converted separately, from its own captions or transcript."],
                fallback_reason="playlist expansion needs a network call that the caller must authorise (ingestion.youtube.api.playlist_items)",
                reasons=reasons + [f"a playlist link was given ({info.playlist_id})"])
        if info.kind != "youtube_video":
            what = ("a YouTube page that is not a single video (playlist, channel or search results)" if info.kind == "youtube_other"
                    else f"a link to {info.host or 'an unknown site'}")
            return AnswerBundle(
                kind="unsupported", route="tutorial_import", trust="none", needs=["transcript"],
                explanations=[Explanation(text="Pick one YouTube video, or paste the written instructions or a subtitle/transcript file." if info.kind == "youtube_other"
                                          else "Only single YouTube video links are recognised. Paste the written instructions or a subtitle/transcript file instead.",
                                          provenance="catalog_template")],
                fallback_reason=f"unsupported source: {what}; nothing was fetched", reasons=reasons + ["a URL was given but it is not a single YouTube video"])
        known = next((e for e in (tut_index or []) if e["id"] == info.video_id), None)
        sec = H.parse_section(t, info.start_s)
        opts = ["Paste or upload a subtitle file (SRT/VTT) you already have: that route runs offline and produces narrated steps only.",
                "Run the video route (a model watches the public video): needs the Gemini quota and is unverified until a human checks it."]
        cav = ["A link, title or chapter list does not reveal the actions a video shows; no steps were produced.",
               *(["The curated index knows this video: " + known["title"] + (" (creator captions are reported to exist, but no transcript is held)" if known.get("captions_flag") is True else " (caption availability is not verified; no transcript is held)")] if known else [])]
        if not sec.is_empty:
            cav.append("Section requested (" + sec.source + "): " + (f"{sec.start_s or 0:g}s to {('%gs' % sec.end_s) if sec.end_s is not None else 'the end'}" if (sec.start_s is not None or sec.end_s is not None)
                                                                      else "topic '" + " ".join(sec.topic) + "', located in the captions once a transcript is supplied")
                       + ". Once a transcript is supplied, only that part is processed.")
        return AnswerBundle(
            kind="needs_model", route="tutorial_import", trust="none", needs=["transcript", "model"], explanations=[Explanation(text=" ".join(opts), provenance="catalog_template")],
            caveats=cav, fallback_reason="converting a tutorial needs a user-supplied transcript or a video model; neither was used",
            reasons=reasons + [f"a tutorial URL was given (video {info.video_id})"])

    # ---- 2. discover a tutorial
    composite = bool(_COMPOSITE.match(t))
    if composite and kb is not None and not it.ops:
        r = kb.search(t)
        if r.sufficient and r.hits and r.hits[0].title_terms >= 2:
            composite = False        # a strong page match means an operation, not a project ("make a UV sphere")
    if (_FIND.search(t) and not _STATE.search(t)) or (composite and not it.ops):
        d = T.discover(t, tut_index or [], version)
        if d.want.needs_topic:
            return AnswerBundle(kind="clarification", route="clarify", trust="none", reasons=reasons + ["tutorial request without a topic"],
                                clarification="What do you want to learn in Blender (for example 'rigging a character' or 'glass material')?"
                                              + (f" I will look for Blender {d.want.version} material." if d.want.version else ""))
        if d.recommendations:
            expl = [Explanation(text=line, provenance="catalog_template") for line in d.comparison]
            return AnswerBundle(kind="tutorial_recommendation", route="tutorial_index", recommendations=d.recommendations, trust="tutorial_metadata",
                                explanations=expl, needs=["transcript or video model to turn one into steps"],
                                reasons=reasons + [f"curated-index match on {d.want.topic}", f"constraints: version={d.want.version}, level={d.want.level}, max_duration_s={d.want.max_duration_s}"],
                                caveats=["These are metadata matches from a small curated index; what each video actually shows has not been checked.", *d.notes])
        return AnswerBundle(kind="tutorial_recommendation", route="tutorial_index", trust="none", needs=["network"],
                            caveats=[f"Nothing in the curated tutorial index matches {d.want.topic or 'this request'}"
                                     + (" within your constraints" if d.excluded else "") + ". Searching for one needs an external search "
                                     "(for example the YouTube Data API within its quota) and nothing was called.", *d.notes],
                            fallback_reason="no curated tutorial matches; external search not performed", unsupported=d.want.topic,
                            reasons=reasons + ["tutorial or project-goal request with no index match"])

    # ---- 3. depends on the user's state
    if _STATE.search(t):
        return _ask_state(t, it, kb, version, observed, reasons, ret)

    # ---- 3b. depends on a procedure in progress or on the screen: we hold neither, so ask rather than match a page by a stray word
    if _FOLLOWUP.search(t) and not it.ops and not it.trouble_ops:
        obs = ""
        if observed and observed.get("mode"):
            obs = f" (I can see you are in {observed['mode']})"
        return AnswerBundle(
            kind="clarification", route="clarify", trust="none", needs=["session_context"],
            clarification="I do not have a procedure in progress or a view of your screen" + obs + ". Paste the steps you are following (or tell me the tutorial and "
                          "the step you are on), and say what you expected and what happened instead, plus your Blender version.",
            reasons=reasons + ["refers to an earlier action, a procedure in progress or the screen; no session state is held"])

    # ---- 4. a known catalog operation answers itself
    if it.ops or it.trouble_ops:
        return None

    if kb is None:
        return None

    # ---- 5/6/7. local documentation
    r = kb.search(t)
    if r.terms and set(r.terms) <= VAGUE:
        return None                               # 'fix it' must not be matched against a page title: ask what is meant
    vn = version_note(version)
    if _DIFF.search(t):
        return _difference(t, kb, ret, vn, reasons)
    if r.outside_index:
        return AnswerBundle(
            kind="unsupported", route="outside_index", trust="index_pointer", needs=["network"], version_note=vn,
            pointers=[SourceRef(kind="manual", title=f"Blender Manual: {title}", url=f"https://docs.blender.org/manual/en/latest/{p}.html",
                                version="page title from the manual's published inventory; content not indexed", verified_on=ret, licence=LICENCE)
                      for p, title in r.elsewhere],
            fallback_reason=r.reason + ". It is not in the local index; reading that page needs the network (no model is required for a documentation page).",
            reasons=reasons + [r.reason])
    if not r.sufficient:
        if not r.terms or set(r.terms) <= VAGUE or (len(r.terms) <= 1 and not r.hits):
            return None                           # nothing concrete to look up: the caller asks for clarification
        return AnswerBundle(kind="decline", route="decline", trust="none", fallback_reason=r.reason, reasons=reasons + [r.reason],
                            caveats=["Nothing in the Blender documentation index matches this request."])
    top = r.hits[0]
    # older versions: if the same page exists in the oldest indexed manual branch, answer from THAT page (menus move between versions)
    pv = parse_version(version)
    if pv is not None and pv < (4, 0):
        old = kb.get_page(top.path, OLD_BRANCH)
        if old is not None:
            diff = _differs(top, old)
            top = old
            vn = (vn or "") + f" Read from the {OLD_BRANCH} manual (the oldest available) because your Blender {version} is older than the current manual." +                  (" The menu path or shortcut differs from the current manual." if diff else "")
    cand = candidate_from_hit(top)
    howto = bool(_HOWTO.match(t)) or it.kind in ("how_to",)
    if howto and cand is not None:
        return _how_to(cand, top, kb, t, observed, version, vn, ret, reasons + [r.reason])
    ex = [_excerpt(top, ret)]
    cav = ["This is an excerpt from the manual, not a step-by-step procedure."] if howto else []
    return AnswerBundle(kind="concept", route="docs_index", trust="doc_passage", explanations=ex, sources=[_src(top, ret)], caveats=cav,
                        version_note=vn, reasons=reasons + [r.reason] + (["how-to wording, but the page has no Reference block to extract steps from"] if howto else []))


def _how_to(cand: Candidate, top: Hit, kb: KnowledgeBase, text: str, observed, version, vn, ret, reasons) -> AnswerBundle:
    cand = validate_candidate(cand, kb)
    steps, assumptions, questions, notes = candidate_steps(cand, text, observed)
    names = [v.menu for v in cand.variants if v.menu]
    sl = finish(steps, "catalog", version=version, profile=extra_profile(BLENDER, names))
    for s in sl.steps:
        if s.provenance == "doc_reference":
            s.source_refs = steps[-1].source_refs
    caveats = list(notes) + ([f"Needs review before it can be trusted as a workflow: {'; '.join(cand.problems)}"] if cand.problems else [])
    return AnswerBundle(kind="procedure", route="docs_index", steps=sl, trust="doc_extracted", explanations=[_excerpt(top, ret, [s.id for s in sl.steps])],
                        sources=[_src(top, ret)], assumptions=assumptions, questions=questions, caveats=caveats, version_note=vn,
                        clarification=questions[0] if questions else None, reasons=reasons + [f"candidate status: {cand.status}"])


def _difference(text: str, kb: KnowledgeBase, ret: str, vn: str | None, reasons: list[str]) -> AnswerBundle:
    body = re.split(r"difference between|differ|versus|vs\.?|compare[d]? (?:to|with)?", text, flags=re.I)[-1]
    sides = [s.strip(" ?.") for s in re.split(r"\band\b|\bor\b|\bvs\.?\b|,|\bwith\b|\bto\b", body, flags=re.I) if len(terms(s)) >= 1]
    hits: list[Hit] = []
    outside: list[str] = []
    for s in sides[:2]:
        r = kb.search(s)
        if r.outside_index:
            outside += [t for _, t in r.elsewhere[:1]]
        elif r.sufficient and r.hits and r.hits[0].path not in {h.path for h in hits}:
            hits.append(r.hits[0])
    if len(hits) >= 2:
        return AnswerBundle(kind="concept", route="docs_index", trust="doc_passage", explanations=[_excerpt(h, ret) for h in hits],
                            sources=[_src(h, ret) for h in hits], version_note=vn, caveats=["Each excerpt describes one tool; the manual does not state the difference "
                                                                                           "explicitly, so compare them yourself or ask for a model summary."],
                            reasons=reasons + ["comparison: one page per side"])
    if hits:
        return AnswerBundle(kind="concept", route="docs_index", trust="doc_passage", explanations=[_excerpt(hits[0], ret)], sources=[_src(hits[0], ret)], version_note=vn,
                            caveats=["Only one side of the comparison is in the local index." + (f" The other side matches an unindexed page: {', '.join(outside)}." if outside else "")],
                            needs=["network"] if outside else [], reasons=reasons + ["comparison: one side found"])
    return AnswerBundle(kind="unsupported", route="outside_index", trust="none", needs=["network", "model"],
                        fallback_reason="neither side of the comparison is in the local index" + (f" (unindexed pages: {', '.join(outside)})" if outside else ""),
                        reasons=reasons + ["comparison: no side found"])


def _ask_state(text: str, it: Intent, kb: KnowledgeBase | None, version: str | None, observed: dict | None, reasons: list[str], ret: str) -> AnswerBundle:
    q = ["Which Blender version are you using?", "Which mode are you in (Object Mode or Edit Mode)?",
         "What type of object is selected (mesh, curve, camera, ...), and how many objects are selected?"]
    expl: list[Explanation] = []
    sources: list[SourceRef] = []
    assumptions: list[str] = []
    unmet: list[str] = []
    trust = "none"
    if it.ops:
        op = BY_ID[it.ops[0]]
        from .knowledge import apply_context
        ctx = apply_context(op, observed)
        unmet = [*ctx.unmet, *[BY_ID[p].title for p in ctx.prepend_ops]]
        where = f" It is found in: {'; '.join(op.menu_paths)}." if op.menu_paths else ""
        needs = " ".join(p.text for p in op.prerequisites)
        expl.append(Explanation(text=f"{op.title}.{where} It only works when: {needs}" if needs else f"{op.title}.{where}", sources=list(op.sources)))
        sources = list(op.sources)
        trust = "catalog"
        assumptions = [f"Assumes: {u}" for u in ctx.unknown]
    elif kb is not None:
        r = kb.search(text)
        if r.sufficient and r.hits:
            top = r.hits[0]
            c = candidate_from_hit(top)
            if c is not None:
                menus = "; ".join(v.menu for v in c.variants if v.menu) or "its tool or shortcut"
                modes = " / ".join(c.modes_raw) or "the modes the manual lists"
                expl.append(Explanation(text=f"According to the manual, {top.title} is found in {menus} and is available in {modes}. If the option is missing or "
                                             f"greyed out, check that you are in {modes} and that something suitable is selected.",
                                        sources=[_src(top, ret)], provenance="documentation"))
                trust = "doc_extracted"
            else:
                expl.append(_excerpt(top, ret))
                trust = "doc_passage"
            sources = [_src(top, ret)]
    return AnswerBundle(kind="needs_state", route="docs_index" if kb is not None else "clarify", explanations=expl, sources=sources, trust=trust, questions=q,
                        clarification=q[0], assumptions=assumptions, unmet_prerequisites=unmet, needs=["user_state"], version_note=version_note(version),
                        caveats=["Whether the option is available depends on your current mode, selection and version; documentation cannot establish that."],
                        reasons=reasons + ["state-dependent wording (missing / greyed out / can't)"])
