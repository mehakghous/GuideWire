# Ingestion & Step Generation: Technical Plan

Owner: Ayesha Raza (`/ingestion`) · Status: **DRAFT v0.1 for review** · Written: 2026-10-10
Sources: `GuideWire_FYP_Proposal_Revised_v3.docx`, repo state at commit `7ae0e0f`, Google/YouTube docs fetched 2026-10-10.

Legend: **[V]** verified (proposal text, repo, or vendor doc read on the date above) · **[D]** proposed decision · **[A]** assumption needing an experiment.

---

## 1. My responsibilities (from Proposal §7, §10 and README)

| Area | Deliverable | Proposal date |
|---|---|---|
| Foundations | Lit review; requirements for task interpretation; joint grounding spike (with Umaima) | Aug 30 – Sep 13 |
| Spike | YouTube metadata/chapters + URL-based extraction spike | Sep 13 – 20 |
| Core | Workflow model (step records); step-generation pipeline | Sep 20 – Oct 4 / Oct 11 |
| Compliance | Written questions to YouTube/Google; choose fallback | Oct 11 – 25 |
| Scope | Workflow areas + representative tasks for Unity/Resolve (with Umaima) | Oct 11 – 25 |
| Integration | Connect step lists to guidance engine; basic automatic step progression (expected action/state logic) | Oct 25 – Nov 15 |
| FYP-1 | Written-instruction to workflow | Nov 22 – Dec 6 |
| FYP-2 | Request understanding and question routing; video ambiguity (semantic side); doc-grounded Q&A; accuracy refinement; semantic version comparison; two-stage ranking + fit check; chapter-by-chapter extraction; unify entry points; correctness and recommendation-quality evaluation | Jan 3 – Mar 21 |

**Out of my scope [V]:** screen capture, UI detection, grounding, overlay (Umaima); UI, accounts, session engine, data store, curated-index *content*, dashboard, BKT (Mehak).

**Ambiguities to settle (see §11):**
1. "Workflow model: step records" is listed for me, but "Design shared data model / Data model implementation" is Mehak's. Both own the same object.
2. "Basic automatic step progression" is mine, "Visual action verification" is Umaima's, both Nov 1–15. The boundary is undefined.
3. "Expected-state mapping, unverifiable-step marking, two-sided mismatch prompt" is shared (Feb 14–21).

## 2. Current state

**Repo [V]:** an empty skeleton. Every folder (`app`, `docs`, `ingestion`, `shared`, `tests`, `vision`) holds only `.gitkeep`. There is no code, no schema and no tests. `main` has two commits. `origin/mehak/step-format` exists but points at the same commit as `main`, so there is no step-format work to build on yet.

**Schedule reality [V]:** today is Oct 10. By the proposal's own dates the YouTube/URL-extraction spike (Sep 13–20) and the workflow model (Sep 20 – Oct 4) are already late, and the step-generation pipeline is due tomorrow. Nothing exists in the repo. This plan is deliberately sequenced to recover this: schema first, because it unblocks both teammates.

**Environment problems [V]:**
- `python` and `py` are not available in this machine's shell (Python 3.11 is required by the README). Install it before M0 code.
- `requirements.txt` lists `youtube-transcript-api`. That library works by fetching transcripts outside the official API (my knowledge, unverified here). Proposal §4.f forbids scraping third-party transcripts, so **remove it**.
- `requirements.txt` has no Google GenAI SDK and no HTTP or YouTube client. `.env.example` has a generic `LLM_API_KEY` and no `YOUTUBE_API_KEY`.
- The README's Blender version is still a placeholder. The gold set and predicate vocabulary depend on it.

## 3. The core problem, restated

The product value (checked progress) depends on one thing I produce: **step records whose expected state can be machine-checked**. Everything else (discovery, Q&A) is secondary.
A free-text `expected_state` ("the cube is now in Edit Mode") is useless to Umaima's verifier and to the adapter. If my output is not constrained to what the adapter or screen can report, the whole chain fails at the end. So the plan is organised around:

1. A **closed, small vocabulary of state predicates** (shared contract).
2. An extraction pipeline that **emits predicates only from that vocabulary**, and marks the step `unverifiable` otherwise.
3. **Deterministic validation** of every LLM output before it reaches anyone else.

## 4. Principal technical challenges

1. Predicate vocabulary: expressive enough for tutorials, small enough that Blender's Python API and vision can both check it.
2. Video extraction fidelity: invisible inputs, vague narration, hallucinated UI names, timestamp drift.
3. Honest confidence: the proposal says confidence is heuristic. It must still be useful for deciding which steps to flag.
4. Compliance: the entire YouTube route is contingent on Google's answers.
5. Cost and latency: time to first usable step, and evaluation cost.
6. Integration: three people building against an unwritten contract.

## 5. Recommended architecture

```
 input ─┬─ YouTube URL ──► MetadataClient (YouTube Data API: duration, chapters, embeddable, license)
        ├─ written text ─►                                  │
        └─ goal / Q   ──► (FYP-2: RequestRouter)            ▼
                                              Segmenter  (chapters → segments; else 1 segment)
                                                          │
                                          Extractor (provider interface)
                                            ├─ GeminiVideoExtractor (public URL + schema)   [video]
                                            └─ TextExtractor (LLM, text only)               [written]
                                                          │  raw JSON
                                                          ▼
                                       Validator (deterministic, no LLM)
                                        schema · timestamps · predicate vocab · UI-name lookup
                                                          │
                                       Confidencer (validator flags + optional 2nd-pass agreement)
                                                          ▼
                                          StepList  ──► shared/ contract ──► Mehak (review UI, store)
                                                                          └─► Umaima/guidance (StepEvaluator)
```

Modules (under `/ingestion`, importing contract types from `/shared`):
`providers/` (LLM interface + Gemini impl + fake for tests) · `youtube/` (metadata, chapter parsing from description) · `extract/` (prompts, segmenter, extractors) · `validate/` · `confidence/` · `eval/` (gold set, metrics, runner) · `cli.py` (`python -m ingestion.cli --url ...` for demos and experiments).

Rules:
- Network and model calls live only behind `providers/` and `youtube/` (the "AI Gateway" in the proposal). Everything else is pure and unit-testable.
- No media, audio or transcript is ever downloaded, cached or logged. Only structured results, keyed by video ID, with a `fetched_at` timestamp so the 30-day purge can be implemented.

## 6. Shared contract (proposed v0.1; goes in `/shared`)

```python
class StatePredicate(BaseModel):
    kind: Literal["mode","active_tool","workspace","selection_type","panel_open","property_equals"]
    target: str                # e.g. "EDIT_MESH", "builtin.extrude_region", "Shading"
    value: str | float | None  # for property_equals only
class Action(BaseModel):
    verb: Literal["click","select","press_keys","drag","set_value","open_menu","other"]
    ui_element: str | None     # name as shown in the UI, e.g. "Add > Mesh > Cube"
    keys: list[str] = []; value: str | None = None
class Step(BaseModel):
    id: str; order: int; goal: str; actions: list[Action]
    start_state: list[StatePredicate]; expected_state: list[StatePredicate]
    verifiable: bool           # False when expected_state is empty / unreadable
    video_start_s: float | None; video_end_s: float | None
    alternatives: list[str] = []; version_dependent: list[str] = []; common_mistakes: list[str] = []
    confidence: float          # 0..1 heuristic, not calibrated
    evidence: list[str]        # short quotes/observations backing the step
    review_status: Literal["drafted_automatically","reviewed","drafted_without_source"]
class StepList(BaseModel):
    schema_version: str; source_type: Literal["youtube","written","goal_draft"]
    video_id: str | None; app: str; app_version_tutorial: str | None
    steps: list[Step]; extracted_at: datetime; model_id: str
```

This covers every field Proposal §5 lists for a step record. **[D]** The predicate `kind` set is intentionally small and Blender-first. It is the main negotiation with Umaima and Mehak (§11). Unity and Resolve reuse the same kinds with their own `target` names via the app profile.

## 7. Technical decisions

### D1. Video to steps: URL-based video model (Gemini), behind a provider interface. Keep, with experiments
- **Evidence [V]:** Gemini accepts public YouTube URLs only, in preview. The free tier is capped at 8 h of YouTube video per day. Default sampling is 1 fps. Cost is about 100 tokens/s of video at low `media_resolution` and about 300 at high. Timestamps use `MM:SS`.
- **Not documented [V]:** `start_offset`/`end_offset` clipping with YouTube URLs. The docs show clipping only for uploaded files, and say clipping works only in `static` mode.
- **Alternatives:**
  - (a) Metadata and chapters only. Compliant but yields no real steps. Use it as baseline B0.
  - (b) User-pasted transcript or steps into a text LLM. Fully compliant. Use it as baseline B1 and as the fallback ladder rung.
  - (c) Download frames or audio and run Whisper or a local VLM. Prohibited by §4.f.
  - (d) Another provider with URL input. None verified. Keep the interface so one can be swapped in.
- **Why:** it is the only verified route that sees the screen and hears the narration without storing media. The proposal's design already depends on it.
- **Risks [A]:** (1) low-res frames may not make small Blender UI text legible, so test high resolution; (2) clip offsets may not work, so chapter segmentation would then need a prompt-level "analyse only 03:10–07:45" instruction, whose accuracy is unknown; (3) timestamp accuracy; (4) preview limits and pricing may change.

### D2. LLM vs deterministic, per subproblem
| Subproblem | Approach |
|---|---|
| Metadata, chapter parsing (`0:00 Intro` lines in description) | Deterministic (regex + API) |
| Step content from video | Video model, structured output |
| Step content from written text | Text LLM, same schema |
| Schema, timestamp, predicate checks | Deterministic |
| Is a UI name real? | Deterministic lookup against a per-app, per-version name list (see D4) |
| Tutorial vs installed version | Deterministic semver compare; LLM only to infer a version from description cues |
| Candidate ranking, stage 1 | Deterministic weighted score |
| Fit check, stage 2 | LLM on title, description and chapter titles first; add video minutes only if it measurably improves top-3 hit rate |
| Doc-grounded Q&A | Retrieval at query time + LLM, citing page and version |

### D3. Staged processing. **Two passes per segment**
Pass 1 gives an outline (step goals plus time ranges). Pass 2 fills in actions and predicates per step. Smaller outputs are easier to validate, and the segment loop makes chapter-by-chapter extraction a configuration flag instead of a rewrite. **[D]** Build the segment loop from day one (one segment = whole video). Whether chapter mode is kept stays an evidence-based decision, as the proposal says.

### D4. Hallucination control through a name list
Build a per-version list of real UI names (tool names and mode names from Blender's Python API, plus manual headings). The Validator downgrades any `ui_element` not found, via exact or fuzzy match, and shows it as "unrecognised UI name, please check". It is cheap, deterministic and directly attacks the most damaging failure (guiding the learner to something that does not exist). Gathering the Blender list may need a small script run inside Blender; coordinate with Umaima's adapter work.

### D5. Confidence = evidence, not model self-report
Combine: validator flags (unknown UI name, missing timestamp, unmapped predicate), agreement between two independent extraction runs for the same segment (a diff of step goals and predicates), and the model's self-rating as a weak signal. Evaluate by whether low-confidence flags actually capture wrong steps (§10). Do not describe it as calibrated, matching Proposal §4.c.

### D6. Written instructions first
Written to steps uses the same schema, with no video risk. It becomes the first milestone and unblocks teammates. It also is the demo fallback if the video route fails.

### D7. Model provider and cost **[V + estimate]**
Prices per 1M tokens (paid, Gemini pricing page): 2.5 Flash $0.30 in / $2.50 out; 3.5 Flash-Lite $0.30 / $2.50; 3.6 and 3.8 Flash $0.75 / $3.75 through 2026 and $1.50 / $7.50 from 2027. Estimated cost of a 15-minute video: 900 s × 100 tok/s = 90k input tokens ≈ $0.03 at $0.30/M (about $0.08 at 300 tok/s), plus a few thousand output tokens. So 50 videos × 3 configurations stays within roughly tens of dollars. Model names change quickly: pin the model ID in config and record it in every `StepList`. I have not verified free-tier rate limits (the page does not list them) or whether free-tier inputs are used to train models; since inputs are public videos this is acceptable, but check before sending anything private.

### D8. Out of my scope on purpose
No fine-tuned models, no local speech or vision models, no embeddings or vector DB in FYP-1, no agent frameworks. Each adds cost without addressing a verified need.

## 8. Pipeline details

1. **Input normalisation:** parse video ID from URL; reject non-YouTube; fetch metadata (`videos.list`, 1 quota unit). Reject if not embeddable, not public or too long (set a configurable cap).
2. **Segmentation:** chapters from description, else one segment. Merge chapters shorter than N seconds.
3. **Extraction:** schema-constrained call per segment, carrying a short summary of prior state ("end state of previous segment").
4. **Validation (hard fail → retry once with the error message; second failure → mark the segment failed, never silently dropped):** schema valid · timestamps monotonic and within duration · every predicate in the vocabulary · steps non-empty and ordered · action verbs known.
5. **Annotation:** UI-name lookup flags, unverifiable marking (no readable predicate), confidence.
6. **Output:** `StepList` JSON with `review_status="drafted_automatically"`.
7. **Failure modes handled explicitly:** private/unavailable video, API quota exhausted, model refusal or empty output, timeouts (retry with backoff, bounded), partial segment success (return partial list with a visible gap marker), tutorial not about a supported app (report as out of scope).

## 9. Milestones

| # | Window | Deliverable | Done when |
|---|---|---|---|
| M0 | Oct 10 – 14 | Python 3.11 env; `requirements.txt` cleaned; **send the three compliance questions**; draft `shared` contract v0.1 as a PR; fake-LLM provider | Contract PR open; email sent; `pytest` runs |
| M1 | Oct 12 – 18 | Written to `StepList` (text LLM) + Validator + 5 hand-written Blender fixtures (JSON) delivered to Mehak and Umaima | Fixtures load in Mehak's review UI and drive Umaima's overlay stub; validator unit tests pass |
| M2 (**gate**) | Oct 14 – 20 | **Spike S1** (see §12): URL extraction on 5 videos | Go or no-go on the video route recorded in `docs/` |
| M3 | Oct 20 – Nov 1 | YouTube pipeline: metadata, chapters, segment loop, two-pass extraction, validator, UI-name list, CLI | CLI on 3 unseen videos returns a valid `StepList` in under the target time |
| M4 | Oct 25 – Nov 15 | `StepEvaluator`: pure function `(Step, observed_state) → met / unmet / unverifiable`; hooked to guidance engine | Table-driven tests; runs against adapter-state fixtures |
| M5 | Nov 15 – 22 | Stabilise for Nov 22 demo: end-to-end Blender run on a written input and one video; honest limitations list | Demo script rehearsed; known failures documented |
| M6 | Nov 22 – Dec 6 | Written-instruction polish (messy real-world input) | Gold set for written input passes target |
| FYP-2 | Jan – Mar | Router, doc Q&A, ranking and fit check, version compare, accuracy refinement, evaluation (§10) | Per proposal §7, re-planned from M5 evidence |

**Defer / drop first if late (consistent with Proposal §8):** chapter mode evaluation → opening-minutes video fit check (use text fit check only) → Unity/Resolve depth. Never drop validation or the gold-set evaluation.

## 10. Testing and evaluation

**Tests**
- Unit: URL parsing, chapter parsing, each validator rule, semver compare, `StepEvaluator`.
- Contract: every fixture and every extractor output validates against `shared` schema; schema-version bump test.
- Integration: pipeline with the fake provider (recorded responses) so CI needs no network or keys; separate opt-in `-m live` tests.
- Failure injection: malformed JSON, empty steps, out-of-range timestamps, quota error, private video, timeout.
- End-to-end: CLI to JSON to Mehak's review model to Umaima's overlay stub.

**Gold set [D]:** 10 Blender tutorials, steps hand-annotated by me and independently by one teammate (check agreement on a subset). Include **3–5 screencasts we record ourselves** and upload as public videos. We then control the rights, can log exact ground truth state from Blender, and avoid third-party licence ambiguity. Add Creative Commons or first-party videos for realism. Size is small, so results are reported as directional (as the proposal already states).

**Metrics:** step recall and precision (match on goal and ±5 s window); action accuracy; predicate accuracy vs gold; verifiable-step rate; hallucinated-UI-name rate; schema-valid-first-try rate; time to first usable step; total latency and cost per video; whether low-confidence flags catch wrong steps (precision/recall of the flag).

**Baselines:** B0 chapters-only (one step per chapter); B1 text LLM on a user-supplied transcript (for videos where we own the captions); full pipeline variants: single-pass vs two-pass, low vs high `media_resolution`, whole-video vs chapter mode. Discovery (FYP-2): single recommendation vs top-3, as in the proposal.

## 11. Decisions that need your review

1. **Contract ownership.** I propose I draft `shared/` schema v0.1 this week as a PR to Mehak (who owns data storage), since I own the producer side and nothing exists yet. Agree with Mehak and Umaima, who must accept the predicate vocabulary. *This is the most urgent item and blocks everyone.*
2. **`StepEvaluator` boundary.** I propose pure logic (predicate comparison, advance/hold/unverifiable) is mine; getting the observed state (adapter, vision) is Umaima's, and the result type is shared.
3. **Remove `youtube-transcript-api`** from `requirements.txt` and add `google-genai`, `httpx`, `pydantic` (already there), `pytest`. Needs a PR to the team's repo.
4. **Billing.** Who holds a Gemini/YouTube API key, free tier vs a small paid budget (estimated tens of dollars for the whole evaluation)? Free-tier limits are not documented in what I fetched.
5. **Recording our own gold-set screencasts** (3–5, public YouTube) vs relying only on third-party videos. I recommend recording.
6. **Overdue work.** The schedule is already behind, so the Nov 22 demo should be scoped as: written to steps plus one video working end-to-end on Blender, nothing more.

## 12. Early feasibility experiments (run before building M3)

| ID | Question | Method | Kill / change condition |
|---|---|---|---|
| S1a | Do `start_offset`/`end_offset` work with YouTube URLs? | Same video, with and without offsets, compare token counts and output range | If not, segment by prompt instruction; if inaccurate, drop chapter mode |
| S1b | Can the model read Blender UI text at low vs high `media_resolution`? | 5 videos, count steps naming correct tool | If low fails and high is too costly, restrict to high-res and shorter videos |
| S1c | Is structured output reliable for long step lists with video? | 20 runs, schema-valid rate | If under ~90 percent first-try after prompt work, use outline + per-step pass only |
| S1d | Is extraction good enough to beat B0 and B1? | 5 gold videos, metrics above | If no better than B1, make the user-supplied-transcript/steps path primary |
| S2 | Run-to-run stability | Same video 3 times, step-goal agreement | If low, the agreement signal is meaningful for confidence; if high but wrong, it is not |
| S3 | Predicate coverage | Take 5 tutorials, hand-write steps; what fraction of expected states fit the vocabulary? | If under ~50 percent, the vocabulary is too narrow and "checked progress" is the weak point of the whole project; escalate to the team |
| S4 | Time to first usable step | Whole-video vs chapter 1 | Decides whether chapter mode stays |

S3 does not need any model and can start now.

## 13. Critical review: what I would change in the proposal

1. **Compliance questions sooner.** They are scheduled Oct 11–25 but block the architecture. Send them now, and design as if the answer might be no (fallback ladder is already built into D1 and D6).
2. **Text LLM first, video second.** The proposal sequences video extraction first. I reverse it so the schema and validator are proven without the riskiest dependency.
3. **Segment loop from the start.** The proposal treats chapter mode as a late conditional feature; the cheap way to keep it conditional is to build the loop now.
4. **Closed predicate vocabulary.** The proposal says "expected state" without defining its form. Without it, verification cannot be built in parallel.
5. **Fit check starts text-only.** Proposal §5 uses the opening minutes of the video; I begin with titles, descriptions and chapters, and add video only if it improves hit rate.
6. **Deterministic UI-name check** added; the proposal relies on confidence alone.
7. **Own recorded gold set** added for exact ground truth and licence safety.

**Skeptical review of this plan:** every module maps to a proposal deliverable; the only additions (name list, predicate vocabulary, own recordings) exist to make checked progress possible. The largest remaining risks are S1 (video route quality), S3 (vocabulary coverage), and Google's answers. Integration is most likely to fail on mismatched state naming between my predicates and Umaima's adapter, so M1 fixtures are consumed by both of them before any video work.

## 14. Status log

| Date | Update |
|---|---|
| 2026-10-10 | Plan drafted. No code written. Assumptions A in §7 and §12 are untested. |
| 2026-10-10 (later) | **M0 + M1 code implemented on branch `ayesha/ingestion-foundation`** (uncommitted). See "Implementation status" below. |

### Implementation status (actual, as of 2026-10-10)

**Decisions confirmed by Ayesha:** I draft `shared/` schema v0.1; step extraction, including deriving expected state from the video (resolving "click this" etc.), is entirely hers. Interpretation used: the pure `StepEvaluator` comparison logic lives in `ingestion/` and takes an observed-state dict; reading the *live* screen/adapter remains Umaima's, since it cannot be derived from the video.

**Built and tested offline (35 unit tests, all passing, Python 3.11.9):**
- `shared/step_record.py`: contract v0.1 (StepList, Step, Action, StatePredicate); `verifiable` is derived, never trusted from the model.
- `shared/examples/*.json`: 3 hand-written Blender step lists (labelled as hand-written) for Mehak's review UI and Umaima's overlay. Fewer than the 5 planned.
- `ingestion/profiles.py`: Blender vocabulary. **Written from memory, not yet checked against a real Blender install**; unknown names give warnings only.
- `ingestion/validate.py`: closed-vocabulary sanitising (out-of-vocabulary predicates dropped and flagged), fuzzy UI-name check, structural checks (order, duplicate ids, timestamps within duration and monotonic).
- `ingestion/evaluator.py`: `evaluate_step` returns met / unmet / unverifiable; a state that was not observed is never counted as a failure.
- `ingestion/extract.py`: written-text and video extraction with one error-informed retry, then a hard `ExtractionError`.
- `ingestion/youtube/metadata.py`: URL/ID parsing, chapter parsing, ISO duration, `videos.list` fetch (the fetch itself is untested).
- `ingestion/providers/`: provider interface, `ScriptedProvider` (tests only), `GeminiProvider`.
- `ingestion/cli.py`; `requirements.txt` (removed `youtube-transcript-api`; added `google-genai`, `httpx`, `pytest`); `.env.example`; `pytest.ini`.

**NOT verified (no API keys during development):** `GeminiProvider` was only checked to construct its request objects with SDK `google-genai 2.29.0`; no live call has been made. The prompt quality, JSON-schema acceptance by Gemini, YouTube URL input, timestamp accuracy and `fetch_metadata` are all untested. Experiments S1a–S1d (§12) are still to be run and are the next gate.

**Known limitations / not yet done:** segment (chapter) loop and two-pass extraction (M3); gold set and evaluation harness; Blender name list generated from a real install; Unity and Resolve profiles; written-input timestamps are nulled after validation rather than before; no confidence signal beyond model self-rating and validator penalties.

### Live integration results (2026-10-10, first contact with real APIs)

Keys are read from `.env` via `python-dotenv`; checked by presence and length only, never printed. `tests/test_live_smoke.py` (`pytest -m live -s`) repeats checks 1 and 3 below.

| # | Check | Result | Authentication only, or end-to-end? |
|---|---|---|---|
| 0 | Both keys load; `.env` is git-ignored | **Pass** | n/a |
| 1 | YouTube `videos.list` on a known public video | **Pass** (title, 214 s, embeddable, public) | Real data returned, so key and quota work |
| 2 | Gemini with the configured model `gemini-2.5-flash` | **Fail, 404**: model closed to new users. Default changed to `gemini-3.6-flash`. Models seen by this key include 3.5-flash(-lite), 3.6/3.7/3.8-flash, 3.1-pro-preview | Key authenticates; the old default was the problem |
| 3 | Structured output + written pipeline, `gemini-3.5-flash-lite` | **Pass after a fix**, 5 steps in ~6 s | End-to-end for text (see below) |
| 4 | Video extraction, 1 CC video (`34FBeC9mktE`, "Object and Edit Mode – Blender 2.80 Fundamentals", 188 s) | **Inconsistent.** See below | **Not established** |

**Check 3 findings.** The first live run exposed a real design bug: the model put the predicate kind into `target` and the name into `value`, so every predicate was rejected or dropped and every step came back unverifiable. Fix: a separate model-facing `DraftPredicate` (`kind`, `name`, `expected_value`) plus mode aliases (e.g. "Edit Mode" to `EDIT_MESH`) and an inline example. After the fix, a 5-step instruction gave 3 verifiable steps with correct mode, workspace, tool and selection predicates, and the aesthetic step ("make it look nice") stayed unverifiable. Weaknesses seen: confidence is 1.0 for almost everything (self-rated, so uninformative), and "delete the default cube" came back unverifiable. This is one hand-written input, so it demonstrates the mechanism, not accuracy.

**Check 4 findings (video, one 188 s video, not enough to claim anything):**
- The URL route is *accepted*: `generate_content` with the public YouTube URL returned a usable response (HTTP 200) and the model clearly saw the video (it identified the Blender 2.80 version, which is in the title, so this alone is weak evidence).
- `gemini-3.6-flash`: one run succeeded after one retry, giving 4 steps with plausible timestamps and one unrecognised-name flag. `gemini-3.5-flash-lite`: first run 2 steps; later runs 1 step, and a failure. `gemini-3.8-flash` and `gemini-3.5-flash`: HTTP 503 "high demand" on all attempts (transient).
- **Timestamp overrun is a systemic failure mode.** All 5 runs in which the model returned content (2 models) needed at least one retry, and every rejection message I saw was a timestamp past the end of the video (197–238 s on a 188 s video; I did not log the reason for every rejected attempt). Telling the model the duration in the prompt did not fix it for flash-lite. The structural validator caught every case and the retry sometimes recovered, which is the purpose of the validator, but it means timestamp trust is currently low.
- **Coverage looks sparse** (4 steps over 188 s, with gaps), and I have **not** checked any step against the actual video, so correctness is unknown. A human has to watch the video and compare before any accuracy claim.
- Token cost measured: about 18,000 prompt tokens for the 188 s video, roughly 96 tokens per second, i.e. the default (low) media resolution. At the listed price this is cents per video, but whether Blender's small UI text is legible at this resolution (S1b) is untested.
- Quota used: 1 `search.list` call (of 100 per day) to find candidates, plus a handful of `videos.list` calls.
- Nothing yet tests clip offsets (S1a) or high media resolution (S1b), and nothing has compared against baselines (S1d).

**Security incident.** During check 4 the HTTP client logged the full request URL, including the YouTube API key as a `?key=` query parameter, into the session output. Fixed: the key is now sent in the `x-goog-api-key` header, and `httpx`/Google SDK loggers are silenced in the CLI. **The YouTube key should be rotated** because it appeared in that output. The key itself is not recorded in any file.

**Consequences for the plan.** (1) Pin and record the model per run; model availability changes quickly and `gemini-2.5-flash` is already closed to new keys. (2) Timestamp reliability becomes an explicit S1 measurement. Candidate mitigations, none yet tested: clamp small overruns, ask for MM:SS, use chapter segments so each call has a short range, or use a stronger model. (3) The self-reported confidence is not usable alone, which supports the D5 plan to combine it with validator flags and run-to-run agreement. (4) Retry-on-503 with longer backoff is needed before batch experiments.

**Departures from the proposal so far:** `youtube-transcript-api` dropped (conflicts with §4.f); closed predicate vocabulary introduced; written-instruction path built before the video path. Rationale in §13.


---

# Part II: Cost audit, architecture evaluation and proposed experiment (2026-10-10)

No Gemini calls, code changes or paid calls were made for this part. The only new network use was free YouTube Data API metadata (`search.list` and `videos.list`, quota only) and reading official Google documentation. Evidence labels: **[M]** measured, **[C]** calculated from measured usage and published prices, **[E]** estimate on stated assumptions, **[U]** unknown.

## 15. Implementation status audit

| Item | Status | Evidence |
|---|---|---|
| Shared contract, validator, evaluator, YouTube parsing, extraction orchestration | Implemented | 36 offline tests pass (scripted provider, no network) |
| YouTube Data API auth and metadata | Works | live `videos.list` returned real data |
| Gemini auth | Works | model list, structured JSON and text generation returned HTTP 200 |
| Written-instruction extraction | Works on **one** hand-written 5-line input | 3 of 5 steps verifiable and plausible; not scored against a gold set |
| Video ingestion + structured output | **Partially works, unreliable.** Gemini accepts the public YouTube URL and returns schema-shaped JSON | 5 of 8 live runs returned content; 3 of those ended accepted after a retry (R1: 2 steps, R4: 4 steps, R7: 1 step) and 2 failed validation twice (R6, R8); the other 3 runs got only HTTP 503; see §16 |
| Video correctness vs the actual source | **Not verified.** No step has been compared with the video | no gold annotation exists |
| Raw model responses saved | **No.** Only the two *post-validation* outputs of R1 and R4 survive, in `%TEMP%\gw_out` (outside the repo) | rejected first attempts and 503 bodies exist only in session text |
| Per-attempt usage logging | Added late; only R7 and R8 have usage | R1–R6 ran before `GeminiProvider.usage` existed |
| Run log, cost ledger, HTTP status per attempt | **Missing** | needed for any defensible cost analysis |

**Missing measurements** (cannot be recovered without new calls): token usage for R1, R4, R6; raw first-attempt outputs and step counts before validation; thinking-token usage on `gemini-3.6-flash` (billed as output); per-call latency; the billing tier of the key; whether 503 responses are billed.

## 16. Every live video-extraction attempt

All runs used one video: **"Object and Edit Mode – Blender 2.80 Fundamentals"**, Blender channel, [https://www.youtube.com/watch?v=34FBeC9mktE](https://www.youtube.com/watch?v=34FBeC9mktE), 188 s. Licence `creativeCommon` (Data API `status.license`), public, embeddable, **captions: none** (`contentDetails.caption=false`), chapters: none. No other video was ever sent to Gemini. Config: default media resolution, default fps, temperature 0.2, JSON-schema output, up to 3 provider attempts per call, 2 extraction attempts (a retry feeds the validator error back).

| Run | Model | Prompt | Calls | HTTP | Tokens in / out per call | Outcome | Steps accepted (verifiable / not) | Timestamps | Cost |
|---|---|---|---|---|---|---|---|---|---|
| R1 | gemini-3.5-flash-lite | v1 (duration not stated) | 2 | 200, 200 | [U] | attempt 1 rejected: step s02 at 237 s > 188 s; attempt 2 accepted | 2 (1 / 1) | 0–32 s | ~$0.012–0.016 [E] |
| R2 | gemini-3.8-flash | v1 | 3 | 503 ×3 ("high demand") | none | failed, no output; wall time 262 s | 0 | n/a | $0 assumed [U] |
| R3 | gemini-3.5-flash | v1 | 3 | 503 ×3 | none | failed; wall 21 s | 0 | n/a | $0 assumed [U]; model has no entry on the pricing page, so its price is [U] |
| R4 | gemini-3.6-flash | v1 | 2 | 200, 200 | [U] | attempt 1 rejected: step s02 at 197 s > 188 s; attempt 2 accepted | 4 (3 / 1) | 18–187 s | ~$0.03 [E], plus unmeasured thinking tokens |
| R5 | gemini-3.6-flash | v2 | 3 | 503 ×3 | none | failed | 0 | n/a | $0 assumed [U] |
| R6 | gemini-3.5-flash-lite | v1 | 2 | 200, 200 (inferred: a validation error needs a response) | [U] | both rejected; last error: s03 at 238 s > 188 s | 0 | n/a | ~$0.013–0.015 [E] |
| R7 | gemini-3.5-flash-lite | v2 (+ "video is exactly 188 s") | 2 | 200 ×2 (inferred) | 17,956 / 823 then 17,994 / 205 [M] | attempt 1 rejected (reason not captured); attempt 2 accepted | **1** | not recorded | **$0.01336 [C]** |
| R8 | gemini-3.5-flash-lite | v2 | 2 | 200 ×2 (inferred) | 17,956 / 676 then 17,994 / 965 [M] | both rejected; last error: s05 at 236 s > 188 s | 0 (the model returned at least 5 steps) | n/a | **$0.01489 [C]** |

For the four measured calls `total = prompt + candidates`, so flash-lite used no billed thinking tokens [M]. Unmeasured for 3.6-flash.

Manually checked against the video: **none.** Total of all video runs that got a response (R1, R4, R6, R7, R8): about **$0.09 ± 50%** (two runs measured, three estimated). Text-only smoke tests: under $0.01 [E]. Which tier was billed is [U]: on the free tier the charge would be $0 but quota is consumed and content may be used to improve Google's products (per the pricing page).

### What the two surviving outputs show
Only the accepted outputs of R1 and R4 exist. Raw responses were not saved, and I am not reconstructing any.

- **R1 (flash-lite), 2 steps, 0–32 s.** s01 "Explain Object Mode" has no action and no expected state, with confidence 1.0 (an explanation, not an instruction). s02 clicks "Object Mode" then "Edit Mode" and expects `mode=EDIT_MESH`, which is sensible. Coverage is 32 s of 188 s (17%).
- **R4 (3.6-flash), 4 steps, 18–187 s.** Coverage 62 s of 188 s (33%; an earlier draft of this document wrongly said 81 s / 43%, corrected after the validator computed it). Uncovered: 0–18 s (intro, skipped by the prompt), 31–117 s (86 s), 132–152 s (20 s). Weak expected states: s02 "Edit multiple mesh objects" expects the same `EDIT_MESH` as s01, so it cannot be told apart. s03 "Join" expects `mode=OBJECT`, which was already true before the step and verifies nothing. Self-rated confidence is 0.85–1.0 throughout, so it does not separate good steps from weak ones. s04's `Mesh > Separate > Selection` was flagged "unrecognised" only because my starter vocabulary lacks it: a validator false positive, not a model error.
- The `evidence` fields contain quote-like text. The video has no captions, so I cannot check the quotes, and they might be paraphrase or invention. They are **unverified**.

### Where the problems originate
| Problem | Model | Prompt | Validator | Timestamp conversion | Strategy |
|---|---|---|---|---|---|
| Timestamps past the end (every content-returning run needed at least one retry; every rejection reason I saw was this) | **Yes**: 197–238 s on a 188 s video | Partly: v1 did not state the duration; v2 did, and it still happened | No: the rule is correct | None exists (we ask for seconds and use them as is). Whether the model mixed MM:SS and seconds is [U], because raw output was not saved | Plausible: one long call over the whole video |
| Sparse coverage (17%, 33%) | Yes | Yes: no coverage or density requirement | No | n/a | Possibly |
| Weak or redundant expected states | Yes | Partly: nothing asks for a state that *changes* | No: nothing checks expected state against start state | n/a | n/a |
| False "unrecognised UI name" | n/a | n/a | **Yes**: incomplete vocabulary | n/a | n/a |
| 503 on larger models | Provider capacity (transient) | n/a | n/a | n/a | Short backoff (2 s, 4 s), no fallback model |

## 17. Pricing and cost model

USD per 1M tokens, Standard paid tier, from the [Gemini pricing page](https://ai.google.dev/gemini-api/docs/pricing) fetched 2026-10-10:

| Model | Input | Output (incl. thinking) | Batch (50% off) | Cached input | Notes |
|---|---|---|---|---|---|
| 3.5 Flash-Lite | 0.30 | 2.50 | 0.15 / 1.25 | 0.03 (+$1.00/h storage) | no 2027 change listed |
| 3.6 Flash | 0.75 | 3.75 | 0.375 / 1.875 | 0.075 (+$0.50/h) | **doubles on 2027-01-01**, which falls inside the FYP-2 evaluation window |
| 3.8 Flash | same as 3.6 | same | same | same | same |
| 3.5 Flash | not on the page | | | | price [U] |

Free tier: input and output are free for these models, and content is used to improve Google's products. The paid tier does not use content that way. The pricing page lists no free-tier rate numbers. **Consequence:** participant screen captures (FYP-2) and private user text must go through a paid-tier key. YouTube-URL input is a free preview feature capped at 8 h of video per day on the free tier, with no length limit on the paid tier. Whether our key is paid or free is [U].

**Measured** [C from M]: flash-lite cost $0.0074, $0.0059, $0.0071 and $0.0078 per 188 s call. A run is two calls at today's retry rate, so about **$0.013–0.015 per run**, whether it succeeds or fails. Failed attempts are not free: R8 cost about as much as R7 and produced nothing usable.

**Cost per correct, usable step: [U].** No step is verified. If all 4 steps of R4 were correct it would be about $0.008 per step (~$0.033 / 4). That is only a lower bound that illustrates the metric.

### Projections (single pass, low media resolution) [E]
Assumptions: 96 tokens/s all-in for the video, measured on this one video (about 87 if the ~1.5k tokens of system prompt and schema are subtracted; the docs say ~98); 3,000 fixed tokens per call; output 250 tokens per minute of video (range 100–350, from four calls on one video, so weak); retry factor 2× as observed; no thinking tokens; 3.6-flash 2026 prices.

| Video | Input tokens | Output (mid) | flash-lite, 1 call | 3.6-flash, 1 call | 3.6-flash at 2027 price | ×2 attempts (lite / 3.6) | One call feasible? |
|---|---|---|---|---|---|---|---|
| 3 min | 20k | ~750 | $0.008 | $0.018 | $0.036 | $0.016 / $0.036 | yes |
| 30 min | 176k | ~7.5k | $0.071 | $0.160 | $0.32 | $0.14 / $0.32 | yes |
| 2 h | 694k | ~30k | $0.28 | $0.63 | $1.27 | $0.57 / $1.27 | borderline: near the 1M context |
| 8 h | 2.77M | ~120k | $1.13 | $2.53 | $5.05 | $2.26 / $5.05 | **no**: over the 1M context (docs: ~3 h at low resolution) and the 65k output limit |

**Dollars are not the constraint; correctness and reliability are.** Even 8 hours is a few dollars, but whole-video calls cannot run above roughly 2.5–3 hours, and I have no accuracy evidence beyond a 3-minute video. The 5.7 h candidate [VWmMNPuhdqc](https://www.youtube.com/watch?v=VWmMNPuhdqc) would need about 2M tokens and cannot be sent whole.

## 18. Architecture alternatives

**A. Whole-video Gemini (baseline, kept).** Works end to end only after a retry, on a 3-minute video. Timestamp overruns in every content-returning run, sparse coverage, no accuracy evidence, and a context limit that rules out courses. Cost is fine.

**B. Chapter or segment processing.** Chapters come from description lines (`parse_chapters` is implemented and unit-tested). Of the 16 candidate videos whose metadata I fetched today, only 3 have chapters (the 188 s baseline has none), so the **fallback must be fixed windows** (3–5 min) with a small overlap, de-duplicated by timestamp and goal. **Critical dependency:** clip offsets for YouTube URLs are *undocumented* (Google's docs show clipping only for uploaded files). If offsets are ignored, every segment call re-ingests the whole video, cost multiplies by the segment count, and nothing is saved. So B has value only if S1a shows offsets are honoured. Also unknown: whether returned timestamps are clip-relative or absolute (the pipeline must add the segment start if relative). A retry then affects one segment, not the whole video. Context between segments is a compact carry-over (last end state, open assumptions), as the plan already proposes.

**C. Transcript-first.** **Rejected as the primary path.** `captions.download` requires permission to edit the video and costs 200 quota units, so captions of other people's videos are not available through the API, and scraping or downloading audio is prohibited by the proposal's own §4.f. Captions are also often absent: 10 of the 16 videos I looked up have `caption=false`, including the baseline. A transcript also cannot show which tool is on screen. It stays useful in two permitted forms: a transcript the *user* pastes (the written path takes it as a hint), and captions on videos we own. When no transcript exists the video route is the fallback.

**D. One-time indexing and cache.** **Recommended and cheap.** Key = `(video_id, schema_version, prompt_version, model_id)`; value = the validated `StepList` plus run metadata (attempts, usage, status). Invalidate on key change, on a change in the video's `publishedAt` or duration, and at **30 days** (the proposal's cache limit until Google answers). Store in SQLite (a `StepList` is a few KB). Concurrency: a unique key plus a `status` column (`pending/running/done/failed`) so one worker extracts and others wait. Failed or partial jobs are stored with their status and never served as results. Reusable tutorial content is cached; user edits, version warnings and progress are separate per-user rows. Savings: per-user cost is indexing cost divided by users. A curated index of ~100 videos at ~$0.10 each is a one-time **~$10**, then about $0 per learner, and a monthly refresh costs the same again. With ~10 study participants on a few shared tutorials, cache hits would be the norm.

**E. Task-oriented retrieval.** For "bevel in an 8-hour course": (1) match the request against chapter titles and description text (free); (2) if a chapter matches, extract only that chapter (needs offsets, otherwise unaffordable and unreliable); (3) check sufficiency: at least one step whose goal matches the request, else widen to neighbouring chapters; (4) with no chapters, say "could not locate a section" instead of processing 8 hours. This is a different need from "give me the complete navigable tutorial", which uses full segmented indexing in the background. **Defer to FYP-2**; it depends on B.

**F. Model routing.** Text-only jobs (written instructions, request understanding, fit check) suit flash-lite (2.5× cheaper input and 1.5× cheaper output than 3.6-flash). Video evidence so far: flash-lite gave 2, 0, 1 and 0 accepted steps on four runs versus 4 for 3.6-flash on one run. That is far too thin to choose a winner, so the 3.6-flash default stays, and flash-lite is compared on the same videos in the experiment. The 2027 doubling of 3.6/3.8 matters for FYP-2 budgeting. An escalation rule (cheap model first, stronger only for rejected segments) is plausible but untested.

**Other levers to test:** `count_tokens` on the YouTube URL may report input tokens without generating (documented as free; unverified for YouTube URLs). `fps` below 1 and low media resolution may cut tokens (fps for YouTube URLs undocumented). Explicit context caching (cached input is 10% of input price) might make repeated passes cheap, but whether a YouTube URL can be cached is [U].

## 19. Decision matrix

"Expected" entries are hypotheses, not results. + good, ○ uncertain, − poor.

| Criterion | A. whole video | B. segments | C. transcript-first | D. cache | E. task retrieval | F. routing |
|---|---|---|---|---|---|---|
| Cost per correct step | ○ unknown | ○ same tokens if offsets work, N× if not | + cheap but mostly unavailable | + amortised | + for partial use | + for text jobs |
| Timestamp accuracy | − measured poor | + expected better (short ranges) | ○ good where captions exist | n/a | ○ | n/a |
| Coverage | − 17–33% | + expected | − text only | n/a | partial by design | ○ |
| Blender UI grounding | ○ unverified | ○ | − cannot see the screen | n/a | ○ | ○ |
| Reliability / retries | − every run retried | + retry per segment | n/a | + removes repeat work | ○ | ○ |
| Latency | ○ 20–40 s for 3 min | + first segment early | + | + instant on hit | + | ○ |
| Long videos | − impossible above ~3 h | + | + | + | + | n/a |
| Needs transcripts | no | no | **yes, often unavailable** | no | no | no |
| Implementation effort | done | medium | medium | low | medium | low |
| Compliance risk | as proposal | same | high if scraped (excluded) | 30-day limit applies | same | paid tier for private data |
| FYP fit | baseline | core if S1a passes | optional | do now | FYP-2 | partly now |

## 20. Recommendation

**Hybrid:** keep A as the baseline and default for videos up to ~10 min; add segmenting (B) only if offsets work; add a cache (D); add logging and a cost ledger; use routing (F) for text jobs now.

| Class | Items |
|---|---|
| **Immediate, low-risk (after your approval)** | (1) JSONL run log per attempt: model, config, prompt version, HTTP status, usage, latency, raw response (local, git-ignored, secrets redacted); (2) cost ledger with a hard stop and a `count_tokens` pre-flight; (3) `max_output_tokens` cap; (4) longer 503 backoff plus an optional fallback model; (5) validator flag for steps whose expected state equals their start state; (6) vocabulary additions (e.g. `Separate`); (7) a prompt variant asking for MM:SS timestamps and stating a coverage expectation, tested on the same video; (8) SQLite cache keyed as in D. All are logging, validation or storage changes; none replaces the working pipeline. |
| **Needs experimental validation** | clip offsets and their timestamp frame of reference (S1a); fixed-window segmentation and merge; media resolution and fps effects (S1b); flash-lite vs 3.6-flash on video; explicit caching of YouTube URLs; thinking-token cost on 3.6-flash |
| **Defer** | task-oriented retrieval over long courses; escalation routing; second annotator and larger gold set; multi-language |

## 21. Proposed experiment (not run; needs your approval)

### 21.1 Videos
Metadata verified today through the free YouTube Data API. Only video 1 has ever been sent to Gemini.

| # | Title | URL | Duration | Licence | Captions | Chapters | Why |
|---|---|---|---|---|---|---|---|
| 1 | Object and Edit Mode – Blender 2.80 Fundamentals (Blender) | [34FBeC9mktE](https://www.youtube.com/watch?v=34FBeC9mktE) | 188 s | CC | none | none | continuity with all earlier runs; no-caption case |
| 2 | Select & Transform – Blender 2.80 Fundamentals (Blender) | [hTL6AKR8YDs](https://www.youtube.com/watch?v=hTL6AKR8YDs) | 666 s | CC | yes | none | mid-length, clear tool and UI actions; tests fixed-window segmentation |
| 3 | In-Depth Floor Plan Tutorial Part 1 [UPDATED 2025] (Dude Blender) | [94kAIpRnhcY](https://www.youtube.com/watch?v=94kAIpRnhcY) | 1,383 s | CC | yes | **29** | long tutorial with real chapters: tests chapter segmentation and carry-over (architectural modelling, so less basic than 1–2) |
| 4 (optional) | your own 3–4 min Blender screencast, uploaded **public**, with some deliberately vague "click this" moments | to be recorded | ~200 s | yours | optional | none | exact ground truth, ambiguous narration, no licence question |

Not proposed: [VWmMNPuhdqc](https://www.youtube.com/watch?v=VWmMNPuhdqc) (5.7 h): too large for the baseline and not annotatable in the time available; it stays a documented infeasible case. The set is small by necessity, so results are directional.

### 21.2 Ground truth
Annotated by a human before any model output is seen, never from Gemini. You annotate videos 1 and 2 fully and the first three chapters of video 3; Umaima independently annotates video 1 to check agreement. Each gold step: `order`, `goal`, `t_start` (the second the action begins), `action` (verb and UI element as shown on screen), `expected_state` as shared-contract predicates, `verifiable_from_state` (yes/no), `importance` (core if the tutorial's result depends on it, else optional). Tolerance: ±5 s for videos up to 10 min, ±10 s for longer. Scoring is **blind**: outputs are anonymised and shuffled across arms before matching. Estimated annotation time is 1.5–2 h.

### 21.3 Metrics (from the gold list and the run log)
- **Step match:** a predicted step matches a gold step if |Δt_start| is within tolerance and a human judges the goal and action the same (one-to-one). **Precision** = matched / predicted. **Core recall** = matched core gold / core gold. A step with the right action and a wrong timestamp counts as an action match and a timestamp miss.
- **Timestamp accuracy** = matched steps within tolerance / matched steps; also the count of timestamps past the video end.
- **Unsupported or incorrect rate** = predicted steps with no matching action in the video, or with a wrong tool or mode, / predicted steps.
- **Verifiable %** = steps with at least one predicate; **predicate correctness** = predicates on matched steps that agree with gold.
- **Coverage** = core gold steps recalled; also uncovered seconds.
- **Retry rate** = extraction attempts beyond the first; **validation failure rate**; **provider error rate** by HTTP status.
- **Latency** = wall time to an accepted result, and time to first usable step for segmented arms.
- **Cost** = every call, failed ones included, from recorded usage × published prices. **Cost per correct usable step** = total cost / matched steps with the correct action and a timestamp within tolerance.

### 21.4 Design
- **Stage 0 (gate, S1a, near-zero cost).** `count_tokens` on video 1 with and without `start_offset`/`end_offset`, one variant with `fps=0.5` and one with high media resolution, to see whether they change input tokens. `count_tokens` is documented as not billed; if it rejects YouTube URLs I fall back to one `generate_content` per variant with `max_output_tokens=20` (at most 4 calls, about $0.06 on 3.6-flash). One more call on a 60 s clip asks for timestamps, to learn whether they are clip-relative or absolute.
- **Stage 1, only if offsets are honoured.** Three arms on videos 1–3 (and 4 if recorded):
  - **Arm A (baseline):** the current pipeline, `gemini-3.6-flash`, whole video, at most 2 attempts.
  - **Arm B (segmented):** chapters where present, else 4-minute windows with 10 s overlap; at most 2 attempts per segment; same model; carry-over summary; merge with de-duplication.
  - **Arm C (routing probe):** same segments as B on `gemini-3.5-flash-lite`.
  Each arm runs once per video, so run-to-run variance is not measured and is stated as a limitation. If offsets are *not* honoured, Stage 1 runs arms A and C on videos 1 and 2 only, and arm B is dropped.

### 21.5 Cost cap
Worst case at 3.6-flash 2026 prices, using the measured 96 tokens/s, 1.5k fixed tokens per call and the output caps below (thinking tokens count inside the cap):

| Arm | Worst-case calls | Input tokens | Output tokens (cap) | Worst-case cost |
|---|---|---|---|---|
| A, videos 1–3 | 3 videos × 2 = 6 | 2 × (18k + 64k + 133k) = 430k | 6 × 16k = 96k | 0.32 + 0.36 = **$0.68** |
| B, videos 1–3 | 10 segments × 2 = 20 | 430k + 20 × 1.5k = 460k | 20 × 6k = 120k | 0.35 + 0.45 = **$0.80** |
| C (flash-lite) | same 20 calls | 460k | 120k | 0.14 + 0.30 = **$0.44** |
| Stage 0 | up to 5 | up to 90k | up to 100 | **$0.07** |
| Optional video 4 (~200 s) | up to 6 | ~110k | 36k | ~**$0.25** |
| **Total worst case** | | | | **≈ $2.24** |

**Proposed hard cap: $3.00.** Expected spend is probably $0.8–1.2, because observed outputs were at most about 1k tokens per call. The one quantity I cannot bound from evidence is thinking-token usage on 3.6-flash; the output cap contains it, so the worst case above assumes the cap is fully used. The cap counts failed calls that return usage.

Limits: at most 4 videos; at most 3 model configurations; at most 2 attempts per segment; `max_output_tokens` of 16k (whole video) and 6k (segment); a per-call `count_tokens` pre-flight that aborts if the projected input exceeds 250k tokens; a ledger updated after every call from `usage_metadata`.

**Immediate stop** if: cumulative cost reaches $3.00, or reaches $2.00 before arm C starts (then I ask first); two consecutive HTTP 429; any 4xx other than 429; the pre-flight count exceeds the limit; or a free-tier key would exceed 8 h of video in a day. 503s are retried at most twice with backoff and logged. If Stage 0 shows `count_tokens` does not work and the fallback calls cost more than expected, I stop and report.

## 22. Open questions and decisions needed from you
1. **Approve the experiment and the $3.00 cap**, or lower it, and accept one run per arm per video.
2. **Is your Gemini key on the paid or the free tier?** (Google AI Studio shows this.) It decides whether spend is real, which quota applies, and whether content is used to improve Google's products.
3. **Annotation:** can you annotate videos 1, 2 and the first three chapters of 3, and can Umaima double-annotate video 1?
4. **Record video 4?** I recommend it for exact ground truth, but it costs your time.
5. **Approve the low-risk items in §20** (logging, ledger, cache) before the experiment. I will not touch the working pipeline until you do.
6. Google's answers to the three compliance questions are still pending; the 30-day cache limit is the safe assumption.

## 23. Status log (continued)
| Date | Update |
|---|---|
| 2026-10-10 | Cost audit and architecture comparison written. No code or live-call changes. Experiment proposed, awaiting approval. |


---

# Part III: Accuracy-first diagnosis, offline improvements, transcript feasibility, evaluation (2026-10-10)

Scope of this part: code analysis, existing evidence, official documentation, and offline changes. **No Gemini calls were made.** Free YouTube Data API lookups were not repeated. Labels: **[DONE]** implemented and unit-tested offline; **[PROPOSED]** not built; **[HYPOTHESIS]** needs live evidence; **[VERIFIED-DOC]** read in official documentation on 2026-10-10.

A correction to Part II: the R4 output covers **62 s of 188 s (33%)**, not 81 s (43%) as first written. The new coverage check computed the figure from the saved output and exposed my arithmetic error. Part II has been corrected in place.

## 24. Diagnosis: what is wrong, why, and what kind of fix it needs

Evidence base: R1 and R4 accepted outputs (saved), the recorded error messages and token counts of R6–R8, and code inspection. Raw responses and rejected first attempts were not saved, so several causes cannot be separated yet. The run log added in §25 closes that gap for future runs.

| # | Problem | Evidence | Likely cause(s) | Kind of fix | Status |
|---|---|---|---|---|---|
| 1 | Timestamps past the video end | 5 of 5 content-returning runs needed a retry; rejections saw 197, 236, 237, 238 s on a 188 s video; one accepted step ends at 187 s, one second before the end | H-T1: the model's temporal grounding on YouTube-URL input is imprecise (1 fps frames; Google makes no accuracy claim). H-T2: we asked for float seconds while Google's docs use `MM:SS`, so the model may convert badly. H-T3: steps are filled in from prior knowledge of the topic past what the video shows. H-T4: the model misjudges total duration | T2: prompt/schema (v3). T1, T3, T4: model or processing strategy, not fixable by wording. Detection: deterministic | Detection **[DONE]** (all violations listed, nothing clamped). v3 `MM:SS` **[DONE offline]**, effect **[HYPOTHESIS]** |
| 2 | Sparse coverage (17%, 33%) | R1 32 s, R4 62 s of 188 s | No coverage requirement in v2 prompt; whole-video single pass; smaller model stops early (flash-lite gave 2, 0, 1, 0 accepted steps) | Prompt (v3 coverage rule) + processing (segments) + model | Detection **[DONE]**. Prompt effect **[HYPOTHESIS]** |
| 3 | Vague, repeated, unsupported steps | R1 s01 "Explain Object Mode" (no action). R4 s01/s02 have identical start and expected state. Quote-like `evidence` cannot be checked (video has no captions) | Schema lets an explanation be a step; no "support" distinction; model paraphrases evidence | Schema (`support` field) + deterministic checks + independent reference text | `support`, duplicate/overlap/identical-state flags **[DONE]**. Evidence check against a user-supplied transcript **[DONE]**. Unsupported rate needs human labels |
| 4 | Expected state wrong or unchanged | R4 s03 "Join" expects `mode=OBJECT` and starts in `OBJECT` | Prompt asked for conditions "certain after the step", not conditions that *change*; no check | Prompt rule + deterministic check | Check **[DONE]**: such a step is marked `verifiable=false`, predicates kept. Prompt rule **[DONE v3]** |
| 5 | Overconfident self-rating | confidence 0.85–1.0 on every step, including a non-action and a vacuous state | LLM self-report is not calibrated; the task rewards fluent output | Do not trust it alone | Composite confidence **[DONE]**: min(model rating, cap by `support`) × penalties; caps and penalties are **uncalibrated priors**. Calibration is an E1 measurement |
| 6 | Wrong Blender names | None observed so far, which is not evidence of correctness: no gold exists | Model priors; version drift (tutorial is 2.80) | Real vocabulary for the pinned version | Starter list widened **[DONE]**; generation script `scripts/dump_blender_vocab.py` written but **not run** (no Blender installed) |
| 7 | False-positive vocabulary warnings | `Mesh > Separate > Selection` flagged although real | My starter list was incomplete | Vocabulary coverage | Fixed for observed case **[DONE]**; message now says the name "may be real but missing from the list". The widened list weakens detection of invented names, so the real dump matters |
| 8 | Passes structure, still wrong | all accepted outputs | JSON validity says nothing about content | Human gold + metrics; semantic checks only catch some classes | Metrics module **[DONE]**; gold needs human work |
| 9 | Inconsistent across models and retries | flash-lite 2/0/1/0 steps; 3.6-flash 4; each retry differs | Sampling variance (temperature 0.2), model capability, 503 capacity | Repeat runs; compare on same videos | **[HYPOTHESIS]**, measured in E1 with n = 3 |

**Which problems the prompt cannot fix:** #1 (T1, T3, T4), most of #2, #8, #9. These need better evidence (a reference transcript or human gold), a different processing strategy (short segments), or a different model.

## 25. Offline improvements implemented (all unit-tested, no API calls)

71 tests pass (`pytest`); the 36 earlier tests were kept, one assertion was changed on purpose (confidence is now capped by support).

| Change | Files | What it does | Principle |
|---|---|---|---|
| All structural errors reported with codes (`TS_BEYOND_END`, `TS_NOT_MONOTONIC`, `BAD_ORDER`, `DUP_ID`, `EMPTY_STEP`) | `ingestion/validate.py` | One retry prompt lists **every** violation, not just the first | Detect, do not repair |
| No clamping. Failed extraction raises `ExtractionError` carrying the last parsed list (`.partial`) and `.issues` | `ingestion/extract.py` | A reviewer sees exactly what the model said (timestamps preserved) | Never invent or move a value to make it pass |
| Retry text says: do not change unlisted steps; use `null` instead of guessing | `extract.py` | Discourages "fixing" by fabrication | |
| Timestamp parser for `MM:SS`, `H:MM:SS`, numbers | `ingestion/timecode.py` | **Format conversion only.** `03:30` on a 188 s video is still an error | Formatting correction is separate from content change |
| Prompt `v3` (candidate) next to unchanged `v2` (baseline) | `extract.py` | MM:SS timestamps, explicit duration, coverage rule, "state must change something", `support` and honest-evidence rules, null over guessing | `v2` stays the default until live evidence says otherwise |
| `support` field (`demonstrated / narrated / inferred / unknown`) and `model_confidence` kept alongside the composite `confidence` | `shared/step_record.py` (schema 0.2, additive) | Directly evidenced vs inferred, as the annotation protocol needs | |
| Composite confidence | `validate.py` | `min(model rating, cap by support) × penalties` (unknown UI name, dropped predicate, uninformative state, claimed support without evidence, duplicate goal, missing time, overlap) | Heuristic, uncalibrated, documented as such |
| Semantic checks: expected state already true (step becomes `verifiable=false`); identical start+expected state to an earlier step; near-duplicate goals; overlaps; coverage gaps (> max(30 s, 15% of video)); coverage below 50% | `validate.py`, `StepList.warnings` | Catches content problems that valid JSON hides | Flags, never rewrites |
| `StepEvaluator` honours `verifiable` | `ingestion/evaluator.py` | A vacuous step is never reported as "met" | |
| Opt-in JSONL run log (raw response, usage, issues, accepted) | `ingestion/runlog.py`, CLI `--run-log`, `runs/` git-ignored | Future runs keep the evidence this audit lacked | |
| Widened Blender vocabulary + overlay loader + `dump_blender_vocab.py` | `ingestion/profiles.py`, `scripts/` | | The dump script is **untested** |
| User-supplied SRT/WebVTT parser and deterministic evidence-quote check | `ingestion/transcript.py` | Flags quotes absent from the supplied transcript or mistimed against it | Reference text comes from the user, never fetched |
| Evaluation module: gold format and metrics | `ingestion/eval/gold.py`, `metrics.py` | Precision, core recall, timestamp accuracy, coverage, state precision/recall, duplicates, order inversions, unsupported rate, cost per correct usable step | Tests use **synthetic** data, labelled as such |
| Regression fixtures | `tests/fixtures/real_runs/` | The two real accepted outputs; the tests lock in the findings above | Rejected attempts and raw outputs were never saved and are **not** reconstructed |
| CLI `--prompt-version`, `--run-log` | `ingestion/cli.py` | | |

**Not done and not claimed:** none of the v3 changes is shown to improve accuracy. They are testable hypotheses.

## 26. Transcripts, captions and scraping: feasibility

I am not a lawyer; this is a technical and policy reading of the primary texts, and "uncertain" is flagged where it applies.

**Policy texts read on 2026-10-10 [VERIFIED-DOC]:**
- YouTube Terms of Service, "Permissions and Restrictions", item 3: no access to the Service "using any automated means (such as robots, botnets or scrapers)" except public search engines following robots.txt, or with YouTube's prior written permission. Item 1: no accessing, reproducing or downloading Content unless the Service expressly authorizes it or with prior written permission. The ToS do not mention AI/ML training.
- YouTube API Services Developer Policies: III.E.6 (no scraping YouTube applications), III.I.14 (no technology other than the API Services to retrieve API Data), III.D.7 (access only through documented means), III.E.4.c (delete or refresh stored data after 30 days), III.E.4.h (no new derived data or metrics from API Data). The policies do not mention AI.
- `captions.download`: requires an OAuth scope and **permission to edit the video**, costs 200 quota units. I did not read the `captions.list` page, so its exact rules for third-party videos are [U]; in practice captions access is tied to OAuth and ownership.

| Method | What it gets | Limits | Cost | Accuracy | Compliance |
|---|---|---|---|---|---|
| Official `captions.download` | Caption track for videos **we own / may edit** | Not for other creators' videos | 200 quota units | Creator-quality | Compliant, but only for our own videos |
| `youtube-transcript-api` (MIT, 8.4k stars, README) | Timed transcript of any public video with captions | Uses "an undocumented part of the YouTube API ... called by the YouTube web-client"; cloud IPs are blocked; README recommends rotating residential proxies; may break at any time | Free, but proxies cost money | Only as good as the captions; auto-captions are error-prone, especially for UI names | **High risk.** Automated access outside the documented API conflicts with my reading of ToS item 3 and Developer Policies III.D.7, III.I.14, III.E.6. Using proxies to evade blocking makes it worse. The README has no ToS disclaimer. **Do not use in the product or the study** |
| User-supplied SRT/VTT or pasted transcript | Whatever the learner supplies | Learner must obtain it; some videos have none | Free | Same as the source | Lowest risk for GuideWire (the user supplies material; the proposal already lists it). How the learner obtained it is their act. **Recommended** |
| Captions on our own videos | Exact owner captions | Only our content | Free | High | Compliant |
| Audio transcription (e.g. Whisper) of YouTube audio | Needs the audio file | Requires downloading or separating audio | Compute | Good speech accuracy, no screen info | **Prohibited**: ToS item 1 and the proposal's own reading of III.I.7 |
| Local Whisper on **our own recorded screencast** | Transcript of audio we own | Only our content | Free | Good | Compliant; useful for annotation and the controlled test |
| Gemini URL input (audio + frames) with the model asked for a **timestamped narration transcript** as an intermediate field | Model's own transcript, `MM:SS` supported per Gemini audio docs [VERIFIED-DOC]; audio costs 32 tokens/s, already inside the ~96 tokens/s measured | Hallucination possible; not independent evidence; timestamps unverified | A few hundred output tokens per minute | Unknown | Same route and same open compliance questions as step extraction |
| Visual-only | Frames only | Misses narration-only steps | n/a | Strong for on-screen tools; weak for vague "click this" | n/a |

**Recommendation for the FYP.**
1. **Do not reintroduce scraping.** The exclusion in Proposal §4.f should stay. The evidence supports it. Optionally add a fourth question to the Google/YouTube letter: whether retrieving public captions through the web client is permitted for educational research. Until a written yes, the answer is no.
2. **Make user-supplied captions a first-class optional input** (already parsed and verified in code). When present they give an independent reference for what was said, a deterministic check of `evidence` quotes (flags fabricated or mistimed quotes), and a hint to the model.
3. **Gold-set ground truth never depends on captions.** Humans watch the video.
4. **Try the in-model transcript as an intermediate** only if E1 shows that narration-vs-action confusion is a major error class. It is not independent evidence and adds output tokens.
5. For our **own screencast** use local Whisper or the editor's captions to help annotate (permitted).

Approval and checks needed: written replies from YouTube/Google on the three existing questions (pending), plus the optional fourth. Until then, derived data stays under the 30-day cache rule.

## 27. Long videos: strategy comparison

Offsets for YouTube URLs are **[HYPOTHESIS]**: Google documents clipping only for uploaded files, and the token-counting page shows only uploaded files. A request containing `start_offset` proves nothing; the test is whether input tokens and content change.

| Approach | Global timestamps | No chapters / no captions | Boundary actions | Repeats | Visual-only actions | "Click this" | Coverage / unsupported content | Retries & cache |
|---|---|---|---|---|---|---|---|---|
| Whole video (baseline) | Native, but unreliable (§24) | Works | n/a | Rare | Seen if legible at low resolution | Model uses frames | Sparse; hallucination risk past the end | Retry = whole video; cache per video |
| Chapters | Needs offset + conversion (clip-relative or absolute: unknown) | Falls back to windows; chapters exist for only 3 of 16 candidates | Chapters usually clean | Carry-over summary | Same as above | Local context helps | Better focus; chapter titles are weak evidence | Per-segment retry and cache |
| Fixed overlapping windows | Same | Always available | Overlap + de-duplicate by time and goal | Needs dedupe (implemented flags) | Same | Same | Dedupe errors possible | Per-segment |
| Transcript-first + targeted vision | From cues if captions exist | Fails without captions | Cue boundaries | Transcript shows repeats | Needs vision pass | Transcript can't resolve it | Text-only misses silent actions | Cheap text pass, targeted frames |
| Audio transcription first | Good timings | Needs audio, which we cannot obtain legitimately | | | | | | **Rejected** |
| Task retrieval over an index | Via stored global times | Needs chapters or an index | | | | | Only the asked task | Cache is the point |
| Hybrid routing | Per segment | | | | Escalate low-agreement segments | Escalate | | Cheap model first, stronger on rejects |

**If offsets do not work**, a prompt-level range ("analyse only 10:00–14:00") still ingests the whole video: cost multiplies by the number of segments (a 2 h video in 30 segments at 3.6-flash prices is about 30 × 0.69M tokens × $0.75/M ≈ $15) and accuracy is unproven. Then the honest options are: URL route for videos up to roughly 10–20 minutes, learner-chosen chapter ranges with the cost shown, or user-supplied steps/transcripts for long courses. That would be a documented limitation, not a failure to hide.

**Recommended design (accuracy first):**
1. Keep whole-video as the default **only** for short tutorials and only after E1 shows the accuracy criteria are met.
2. Build the segment loop and the cache regardless (they are offline work), but enable segmentation only if E0 shows offsets change token counts and timestamps are interpretable.
3. Use the deterministic validators on every segment; retry only the failed segment; keep rejected raw outputs in the run log.
4. User-supplied captions as an optional accuracy booster.
5. Model routing only after two models have been scored on the same gold videos.

## 28. Ground truth and evaluation

### 28.1 Manual annotation (the reference)
A human watches the video and writes `GoldSet` JSON (`ingestion/eval/gold.py`). Per step: `order`, `goal`, `t_start` (second the action begins) and `tol_s` (acceptable ± error), `actions` (verb, UI element exactly as seen), `expected_state` as shared predicates, `evidence_kind` (`directly_evidenced` / `inferred` / `unverifiable`), `importance` (`core` if the tutorial result depends on it, else `optional`), `verifiable_from_state`. Rules: annotate from the video, never from model output; one entry per distinct learner action; mark narration-only steps `inferred` or `unverifiable`; tolerance 5 s for videos up to 10 min, 10 s for longer. Time: about 15–25 min for the 188 s video, about 1 h for the 11 min video.

### 28.2 Double annotation
A second person (Umaima) annotates the same video independently. Value: it measures how subjective "one step" and "core" are, which bounds what any model score can mean (a model cannot reliably beat human disagreement). Disagreements are resolved by watching together; the adjudicated version becomes the gold and both originals are kept; agreement is reported as step-level F1 between annotators plus median start-time difference. **Smallest useful subset:** the 188 s video only (or its first ten steps). It is **not a blocker**: do it before scoring E1, not before further development.

### 28.3 Controlled screencast
A 3–4 minute Blender screencast that we record with a written action script (12–15 actions: keyboard-only, menu paths, tool changes, a mode switch, a workspace switch, one deliberately vague "click this", one place where narration and screen disagree). The script is written **before** recording; after recording, timestamps come from the recording itself, and Blender's own operator log can confirm which operators ran. It gives exact ground truth, a known Blender version, and no licensing question; it needs uploading as a **public** video for URL input.
It does **not** show how the system behaves on other creators' videos (different accents, edits, music, cuts, themes, versions, add-ons). We write both the script and the prompts, so there is overfitting risk. Use it as a precision instrument and regression set, not as the headline accuracy.
**Recommendation: record one now** (about 30–45 min including the script and the annotation). It is the only source of exact, independent ground truth and the cheapest of the three activities. Defer a second screencast.

### 28.4 Metrics and what can be computed where
| Metric | Definition | Offline (existing outputs, no model) | Needs live model output |
|---|---|---|---|
| Step precision | matched predicted steps / predicted steps | code **[DONE]** | needs outputs + gold |
| Core recall | matched core gold steps / core gold steps | **[DONE]** | same |
| Timestamp accuracy | matched steps with start within tolerance / matched steps with a time; count of times past the end | **[DONE]** | same |
| Important-action coverage | core gold steps whose start falls inside a predicted span | **[DONE]** | same |
| Unsupported / incorrect rate | human-labelled predicted steps not supported by the video / labelled steps | formula **[DONE]**, labels are manual | same |
| Expected-state correctness | predicates on matched steps also in gold (precision) and gold predicates recalled | **[DONE]** | same |
| Verifiability | share of steps with an informative expected state | **[DONE]** | same |
| Duplicates, ordering | near-duplicate predicted steps; inversions among matched pairs | **[DONE]** | same |
| Cost per correct usable step | total cost of all calls (failed ones included) / matched steps with correct action and time within tolerance | **[DONE]** | needs real usage |
| First-attempt validity, retry rate, latency | from the run log | logging **[DONE]** | needs runs |
| Confidence usefulness | do low-confidence steps contain the incorrect ones (e.g. AUROC of confidence vs correctness) | not yet coded **[PROPOSED]** | needs gold + outputs |

Matching is automatic only as a first pass (time window plus word overlap, then action-only overlap); the human can override matches. This subjectivity is one reason for double annotation.

## 29. Revised experiment (not run; needs your explicit approval)

**Question.** Does a changed prompt/schema (v3) reduce timestamp failures and raise coverage without raising unsupported steps, compared with the recorded baseline (v2)? Long videos and segmentation are deliberately **not** in this experiment: there is no point optimising cost for long videos before short-video accuracy is shown.

**Videos** (all public, Creative Commons; metadata verified):
| # | Title | URL | Duration | Why |
|---|---|---|---|---|
| 1 | Object and Edit Mode – Blender 2.80 Fundamentals | [34FBeC9mktE](https://www.youtube.com/watch?v=34FBeC9mktE) | 188 s | baseline video with 8 recorded runs; no captions |
| 2 | Select & Transform – Blender 2.80 Fundamentals | [hTL6AKR8YDs](https://www.youtube.com/watch?v=hTL6AKR8YDs) | 666 s | 11 min, clear selection/transform actions; same channel as video 1, so little diversity of speaking style (accepted limitation); it has captions, but they are not used unless you supply a transcript yourself |
| S | your controlled screencast (to be recorded) | to be uploaded | ~200 s | exact ground truth |

**Stage E0 (decides the long-video design; cheap):** `count_tokens` on video 1 with and without clip offsets. The docs show video counting only for uploaded files and do not say whether `count_tokens` is billed. If it rejects YouTube URLs or its billing is unclear, use at most four `generate_content` calls with `max_output_tokens=20` (about $0.014 each on 3.6-flash for 18k input tokens).

**Stage E1:** same model for both arms (`gemini-3.6-flash`), whole video, default resolution, max 2 attempts, run log on.
| Arm | Prompt | Runs |
|---|---|---|
| A (baseline) | `v2`, current code path | video 1 ×3, video 2 ×1, S ×2 |
| B | `v3` | video 1 ×3, video 2 ×1, S ×2 |
A single model avoids confounding. The cheap-model question (flash-lite vs 3.6-flash) is deferred until the metrics exist, as you asked.

**Annotation needed first:** gold for video 1 (required), S (required, from the script), video 2 (optional, skip if time is short and score only validity/timestamps). Umaima's double annotation of video 1 is useful but does not block.

**Acceptance criteria — adopt v3 as the default only if all hold on video 1 and S, and are not contradicted on video 2:**
1. First-attempt structural validity in at least 2 of 3 runs (v2 baseline: 0 of 5 recorded content-returning runs).
2. No timestamp beyond the video end in accepted outputs, and at most one violation per rejected attempt.
3. Core recall at least 15 points above arm A and at least 0.6.
4. Unsupported/incorrect rate no higher than arm A and at most 15%.
5. Timestamp accuracy within tolerance on at least 70% of matched steps.
6. Cost per correct usable step no more than 1.25× arm A.

**Reject v3 (keep v2, change approach) if:** first-attempt validity does not improve (then timestamps are a model-grounding problem, not a format problem, and the next candidates are shorter segments, a different model, or user-supplied transcripts); or recall rises but the unsupported rate rises by more than 10 points (coverage bought with invention). **Stop and rethink** if both arms have core recall below 0.5 or timestamp accuracy below 50% on video 1: the URL route is then not accurate enough as it stands and no cost work is justified.
n = 3 per cell: results are directional; variance will be reported, not hidden.

**Budget (3.6-flash, 2026 prices, measured 96 tokens/s, output capped 8k per call incl. thinking):**
| Item | Worst-case calls | Input | Output cap | Worst-case cost |
|---|---|---|---|---|
| Video 1, 6 runs × 2 attempts | 12 | 12 × 18k = 216k | 12 × 8k = 96k | 0.162 + 0.360 = **$0.52** |
| Video 2, 2 runs × 2 attempts | 4 | 4 × 64k = 256k | 4 × 8k = 32k | 0.192 + 0.120 = **$0.31** |
| S (~200 s), 4 runs × 2 attempts | 8 | 8 × 19k = 152k | 8 × 8k = 64k | 0.114 + 0.240 = **$0.35** |
| E0 fallback | 4 | 72k | ~0 | **$0.06** |
| **Worst case** | | | | **≈ $1.25** |
**Hard cap $1.50.** Expected spend probably $0.4–0.7, since observed outputs were below 1k tokens. Thinking-token usage on 3.6-flash is unmeasured; the output cap bounds it and the worst case already assumes the cap is fully used.
**Stop conditions:** cumulative cost ≥ $1.50; any 4xx other than 429; two consecutive 429s; a pre-flight input estimate above 100k tokens; more than 4 consecutive 503s (pause, do not hammer); any attempt for which usage metadata is missing (stop and fix the ledger first). Free-tier vs paid-tier status must be known before starting (free tier: content is used to improve Google's products and an 8 h/day video cap applies).
Before running I will build (offline, tested) the small runner that enforces the ledger, the caps and the run log, and I will show you the exact commands.

## 30. Revised milestones
| Milestone | Status | Notes |
|---|---|---|
| M0/M1 contract, validator, evaluator, written path, fixtures | **done** | 71 offline tests |
| M2a offline accuracy hardening (§25) | **done this session** | v3 prompt is a candidate, not an improvement |
| M2b gold annotation of video 1; record + annotate screencast S | **you** | ~1.5 h; gates E1 |
| M2c experiment runner with ledger/caps/run log | proposed, offline | needs your approval of §29 first |
| E0 + E1 | **awaiting approval** | cap $1.50 |
| M3 SQLite cache keyed `(video_id, schema, prompt, model)` with status column and 30-day expiry | proposed, offline | independent of experiment results |
| M3b segment loop + merge | proposed | only if E0 shows offsets work |
| M3c transcript-assisted input in the UI (upload `.srt/.vtt`) | backend **done**, UI is Mehak's | |
| M4 connect step lists to guidance engine; `StepEvaluator` against adapter state | proposed | needs Umaima's observed-state format |
| FYP-2 | unchanged in intent | re-planned after E1 |

## 31. Remaining uncertainties and decisions needed
1. **Approve E0/E1 and the $1.50 cap**, or change the design.
2. **Free or paid tier?** Required before any run (§29).
3. **Annotation and screencast:** will you annotate video 1 and record the screencast first? Can Umaima double-annotate video 1 later?
4. **Compliance:** send the three pending questions; optionally add the fourth about public captions.
5. **Blender version** to pin, so the vocabulary dump can be run on that exact version (the script is untested).
6. Unknowns that only live evidence can settle: whether v3 helps; where the timestamp errors come from (T1–T4); whether clip offsets work for YouTube URLs; thinking-token cost; whether the key is paid.

## 32. Status log (continued)
| Date | Update |
|---|---|
| 2026-10-10 | Part III written. Offline accuracy hardening, transcript parser and evidence check, and the evaluation module implemented; 71 tests pass. No live calls. Experiment E0/E1 proposed. |


---

# Part IV: Free tier, user-supplied transcript, first offline check against an independent reference (2026-10-10)

No Gemini calls. New inputs from Ayesha: the Gemini key is on the **free tier** (stated by the user, not verified by me), and a timestamped transcript of video 1 (obtained by the user with a third-party browser tool). Compliance questions: approved for sending; draft in [docs/compliance/google_youtube_questions.md](compliance/google_youtube_questions.md) (**not sent**; I cannot send it, and I could not verify the right policy-question channel).

## 33. What the free tier changes

| Item | Consequence |
|---|---|
| Charges | Real charge for all runs so far and for E1 would be **$0**. The dollar figures in Parts II–III become *notional* (what a paid key would cost) and stay useful as a ledger and for planning |
| Quota | Rate limits and daily request limits are not published on the pages I read (the rate-limit page says to check AI Studio) [U]. The runner must treat 429 as a hard stop. Free-tier YouTube video input is capped at 8 hours/day [VERIFIED-DOC]; the revised E1 uses at most about 1.8 h |
| Data use | Free-tier content **is used to improve Google's products** [VERIFIED-DOC]. Fine for public tutorial URLs; **never send participant screen captures or private text through this key**. FYP-2 participant data needs a paid key |
| Reliability | Larger models returned 503 "high demand" in 3 of 8 runs; free-tier capacity is likely lower priority, so retries and pauses are expected |
| Model availability | Free-tier input and output are listed as free for 3.5-Flash-Lite, 3.6-Flash and 3.8-Flash [VERIFIED-DOC]. Eligibility may change |

## 34. The user-supplied transcript

- Provenance: auto-caption text, with times, for video 1, produced by the user with a third-party web tool. I treat it as user-supplied material. GuideWire code never fetches captions (§26). It is stored only in `local_data/` (git-ignored), converted to WebVTT for the parser, and used **only to evaluate our own outputs and to help annotation**. The product does not depend on it. How the user obtained it is the user's act; the report should say so openly. Question 4 of the draft letter covers this situation.
- Limits as a reference: it is the captioner's text, so it records what is **said**, not what is **shown**. It ends at 3:04.7 while the video is 3:08.

## 35. First offline checks against the independent reference (zero cost)

**(a) Were the model's evidence quotes real?** The deterministic check (`check_evidence`) compared every `evidence` quote in the saved R1 and R4 outputs with the transcript. **No quote was flagged**: all occur in the transcript near the claimed times. This resolves the earlier worry that the quotes might be invented (for these two outputs; the check is lenient, requiring at least 80% of words and at least 3 words). It also shows that Gemini did use the audio of the URL input.

**(b) Are the accepted timestamps accurate?** Against the narration:
| R4 step | Output range | Narration | Verdict |
|---|---|---|---|
| s01 toggle Object/Edit | 18–31 s | 17.8–31.0 s | matches |
| s02 edit multiple objects | 117–132 s | 117.6–133 s | matches |
| s03 join | 152–169 s | 154.9–166 s | within ~3 s |
| s04 separate | 170–187 s | 169.3–184.7 s | within ~2 s |

So the **accepted** outputs are well aligned with the speech. This weakens H-T1 (global timing grounding is generally poor) and points toward the overruns being **extra content past the real end** (H-T3) or a wrong sense of video length (H-T4). It is still not proven, because the rejected first attempts were never saved. The next run with the run log will settle it.

**(c) First look at completeness.** I drafted a gold list (`eval_data/gold/34FBeC9mktE.DRAFT.gold.json`, 14 steps, 9 core) from the transcript. It is labelled **DRAFT: derived from the transcript by me, not yet checked against the video by a human**. It is not Gemini output, but it is not human ground truth either, and the transcript cannot show on-screen state. Run offline through `ingestion/eval/metrics.py`:
| Output | Core steps whose start falls inside a predicted span | Core recall (auto-match) | Timestamp accuracy (auto-match) |
|---|---|---|---|
| R1 (flash-lite, 2 steps) | 2 of 9 | 0.22 | 0.5 |
| R4 (3.6-flash, 4 steps) | 6 of 9 | 0.33 | 0.33 |

**Treat these numbers as indicative only.** The automatic matcher is crude, and three effects are visible: R4's s01 merges the drop-down and the Tab alternatives into one step, so it matches only one gold step; R4's "Join" step starts 5.9 s before my chosen gold start (my choice of "when the action begins" is itself subjective, which is exactly why tolerance and double annotation exist); R1's "Explain Object Mode" matches a gold step spuriously. I will not quote 0.33 as an accuracy.

What is robust is the pattern of what was missed. The core steps no accepted output covers are the instructor's **on-screen demonstration** (about 58–85 s: transform tools on the vertices, Tab back to Object Mode, Ctrl+Z). Both outputs concentrate on narrated explanations and skip the demonstrated part. **[HYPOTHESIS]** The model summarises speech better than it tracks actions on screen, or the prompt rewards "learner goals" over demonstrated actions. This matters because demonstrated actions are exactly what GuideWire must highlight, and it is a different problem from timestamps.

## 36. Consequences for the experiment (§29), still not run

1. **Gold:** you verify the draft by watching the video at the listed times (about 20 min) and correct it; then it becomes the gold for video 1. Please keep the original draft file; record your corrections. This is faster than annotating from scratch and keeps the annotation independent of Gemini, but it is anchored on the transcript, so checking it against the *picture* is the point of your review.
2. **New metric:** report recall separately for **demonstrated** gold steps (`evidence_kind=directly_evidenced` where the action is visible) and for **narrated-only** steps, since the demonstration gap is the largest observed weakness.
3. **Budget framing:** same call/token caps; the dollar cap becomes a notional ledger. Added hard limits for the free tier: at most 30 calls in total, at most 2.5 h of video, stop on the first 429.
4. **Prompt v3 candidate:** the coverage instruction should say explicitly "include actions the instructor performs on screen even when little is said". This is a prompt edit for `v3` that I will make only when you approve E1, so the tested prompt is frozen in the run log.
5. The risk that the instructor demonstrates actions the model skips cannot be fixed by timestamps or transcripts; if E1 shows it persists in `v3`, the next candidates are shorter segments (so the model attends to each part), a different model, or a two-pass design (outline pass, then a pass that asks "what did the instructor do on screen between t0 and t1"), all of which need live evidence.

## 37. Status log (continued)
| Date | Update |
|---|---|
| 2026-10-10 | Free tier recorded. Transcript saved locally (git-ignored). Draft gold written and loaded by a test. Offline check: evidence quotes real, accepted timestamps aligned, demonstration segment missed. Compliance letter drafted, not sent. 72 offline tests pass. Awaiting explicit approval of E0/E1. |


---

# Part V: Demonstration-coverage fix and controlled experiment E1 (2026-10-10)

Status in one line: reference frozen, evaluator and runner built and tested (102 offline tests pass), prompt `v3` rewritten, experiment **run but interrupted by the free-tier daily quota (HTTP 429) after 6 of the planned cells**. The result is a small, directional, partly-complete comparison and is reported as such. Real charge: **$0** (free tier). Notional cost of everything run: **$0.121** of the $3.00 hard cap.

Corrections to earlier parts, found this session:
- Part IV's transcript-derived draft reference and my statement that the demonstration is "about 58–85 s" were **incomplete**. Watching the video shows the on-screen demonstration starts around **38 s**, and includes an earlier undo sequence (about 38–61 s) that the transcript never mentions.
- The "narrated-versus-demonstrated metrics", "experiment cache", "cost ledger" and a demonstration clause in `v3` were described as available but **did not exist in the repository**. They were built this session.
- The Part II statement that flash-lite used no billed thinking tokens does not carry over to the other model: `gemini-3.6-flash` bills **0.7–2.3k thinking tokens per call** (measured), so earlier cost estimates for that model were low.

## 38. Repository state found before changing anything
| Item | Found |
|---|---|
| Prompts | `v2` (baseline, used in all live runs). `v3` had never been run live. It had a generic `support` instruction but **no instruction to read on-screen actions** |
| Schema | `support` was single-valued (`demonstrated / narrated / inferred / unknown`); no `visual_evidence`; times were per step only |
| Validator | Never removes steps (verified by reading `sanitize_and_annotate` and by test); it can only reject a whole output |
| Evaluator | one-to-one word-overlap matching, no narrated/demonstrated split |
| Cache, runner, ledger | none |
| Provider | retried every error including 4xx; wrapped 429 as a generic failure |
| Tests | 72 offline tests |

## 39. Root cause of the demonstration gap

**Confirmed by evidence**
1. **The baseline prompt never asked for visible operations.** `v2` asks for "learner goals" and falls back to the screen only for vague phrases like "click this". Its accepted outputs contain 3–4 steps, all in stretches where the narration states a procedure (multi-object editing, join, separate).
2. **The retry deletes content instead of correcting times.** In baseline run A1, attempt 1 had 4 steps with times 197–304 s (after the 188 s video ended). Attempt 2, told the times were impossible, returned **3 steps: the "edit multiple objects" step disappeared**. The validator did not drop it; the model did, to satisfy the error message. Raw first attempts exist this time (run log), so this is observed, not inferred.
3. **The baseline's timestamps are systematically displaced, not random.** A1's attempt 1 put three real steps at 197, 232 and 250 s; the true positions are about 117, 152 and 170 s, so each was **exactly 80 s late**. A3's attempt 1 had a 121 s step right and later ones about 40–80 s late. After being told the video length, A1's retry gave 152 s and 170 s (correct). Seven of seven baseline runs that returned content were rejected on the first attempt (this includes the five earlier runs R1, R4, R6, R7 and R8; the reason for R7 was not captured).
4. **The model can read the on-screen overlays.** Arm B read "Ctrl + Z x28" (verified at 91.5 s), "Shift + A", "E" and "E x2" on the armature (verified at 98.5–107.5 s), "Ctrl + J" (166 s) and "F" (170 s). So at the default 1 fps, brief key presses are legible in this video, and **sampling rate is not the limiting factor here** (not tested at other rates).
5. **The validator and evaluator did not hide demonstrated steps.** Nothing in the pipeline removed or merged steps after generation.

**Hypotheses not settled**
- H1: Whole-video attention favours narration over visible events. Supported only weakly: one `v3` run (B1) covered 62% of the demonstration window and the other (B2) covered 0%, so instruction alone is not enough.
- H2: A shorter window would improve coverage. Untested. Clip offsets for YouTube URLs are still undocumented. The fallback is a prompt-level range, which re-sends the whole video each call.
- H3: Thinking budget affects coverage (B1 used 2,260 thinking tokens and 3,320 output tokens; B2 used 1,694 and 1,049). Not tested.

## 40. Reference annotation (frozen before any experiment output was examined)
- File: `eval_data/gold/34FBeC9mktE.reference.v1.json`, SHA-256 `f4cbd54e…c466`, frozen before the prompt change and before any run (the `.sha256` file records the time). A test fails if the file changes; the scorer refuses a changed file.
- Method: the video was played in a normal browser tab at 720p, paused and seeked to **39 specific seconds**, and each frame was read (listed in the file). The video draws key and mouse overlays in the lower-left, which were used as evidence. Narration timing comes from the user-supplied transcript.
- 24 steps: 21 **verified** (visually checked at medium or high confidence), 3 **unverified** (R05, R14, R20, low confidence: the transition or menu was not visible in any sampled frame). Unverified steps are never counted as misses.
- Evidence types: 2 narrated-only (R03, R21), 2 demonstrated-only (R14, which is unverified, and R16, the duplicate cube) and 20 both. Preconditions, before/after states, prerequisite links and annotator-defined match terms are in the file.
- **Verification status: assistant-read frames only; no human has checked it.** Limits: 2–7 s between frames (gaps at 91–95, 101–111, 131–138, 164–167), so times are accurate to about ±2–3 s and brief actions between frames may be missing. The frames were read by an AI model.
- **Known defects found after freezing** (post-hoc, from the extra frames at 91.5, 98.5, 102.5, 105, 107.5, 110, 166, 170): R14 and R15 (armature) were under-specified (really "Shift+A", then Tab, "E", "E x2", Tab, at about 98–110 s); R21 (Ctrl+J) was wrongly marked narrated-only (an overlay shows it at 166 s); a step "press F after joining" (about 170 s) was missing. These are corrected in `34FBeC9mktE.reference.v2.posthoc.json` (hash `2fa16cdf…dcde`), clearly labelled post-hoc because the checks were prompted by claims in the outputs. **v1 is the primary, pre-registered scorer; v2 is a secondary analysis.**

## 41. Changes made
| Area | Change |
|---|---|
| Prompt `v3` (rewritten; never run before) | Two sources of instruction (said and visibly done); read on-screen key/mouse overlays; "a spoken explanation must NEVER replace a concrete operation you can see"; scan in time order; group repeated identical presses; do not make steps out of hovers or incidental UI changes; `support` now `demonstrated / narrated / both / inferred`; `visual_evidence` required for demonstrated/both; "never invent a step to cover more of the video"; null instead of a guessed timestamp; `MM:SS` times; duration stated; user prompt asks "did the instructor perform an operation here?". `v2` is **byte-identical** to before (hash-locked by a test) |
| Schema 0.3 (additive) | `support` gains `both`; `Step.visual_evidence` |
| Validator | flags demonstrated/both steps with no `visual_evidence`; `both` capped like `demonstrated` |
| Evaluator (`ingestion/eval/coverage.py`, new) | deterministic matching (time overlap + annotator match terms); lenient (merged/split allowed) and strict (one-to-one) coverage; demonstrated, narrated, overall, demonstrated-only and narrated-only recall; precision; unmatched, untimed, beyond-end, broad and duplicate steps listed; expected-state recall and wrong rate; ordering and prerequisite violations; visual-claim honesty; demonstration-gap detector |
| Runner (`ingestion/experiment.py`, new) | cache keyed on prompt text, model, video, repeat and settings; cost ledger; hard cap refuses anything above $3.00; stops on 429, other 4xx, repeated 503, and call/video-second/dollar limits; frozen-reference check; cells cut short by 503/429 are kept in `runs/incomplete/` and re-run on resume |
| Provider | no retry on 4xx/429; every HTTP attempt and its status recorded; thinking tokens recorded; invalid/truncated JSON passes up so the retry counts as an attempt |
| Bug found by the new tests | a 429 was wrapped as a generic provider failure by the extraction layer, which would have made the "stop on quota" safeguard ineffective. Fixed and tested |

## 42. Offline tests
`pytest`: **102 passed** (72 before). New: reference well-formedness and hash, matching by meaning, the demonstration-gap case (narration covered, 38–92 s missed: detected; covered: not flagged), merged/split/duplicate/broad steps, unverifiable steps kept apart, visual-claim honesty, state correctness and prerequisite order, determinism, `v2` hash lock, `v3` content, cache hit makes no call, failed calls are paid for, budget/call/video-second stops, quota stop, 503 handling, no secret written to any artifact, scoring refuses a modified reference.

## 43. Experiment E1: what actually ran
Video [34FBeC9mktE](https://www.youtube.com/watch?v=34FBeC9mktE) (188 s, 187.6 s by the player). Model `gemini-3.6-flash`, same for both arms. Arm **A** = `v2` (baseline), arm **B** = `v3`. Identical video, schema, validation, token cap (16,384) and temperature (0.2). Planned: 3 repeats per arm. **Executed:**

| Cell | HTTP statuses | Extraction attempts | Result |
|---|---|---|---|
| A1 | 503, 200, 200 | 2 (first rejected: times past the end) | accepted, 3 steps |
| A2 | 503, 503, connection reset | none completed | no usable response; not cached |
| A3 | 200, 503, 503, 503 | 1 response (rejected: times past the end), then only 503s | incomplete |
| B1 | 200 | 1 | accepted, 12 steps |
| B2 | 503, 503, 200 | 1 | accepted, 5 steps |
| B3 | 429 | 0 | **stopped by quota** |

After B3 a single tiny probe over a minute later was also refused with 429, so this is almost certainly the **daily** free-tier limit (the message text I stored was truncated, so the exact quota is [U]). I stopped. Nothing was retried in a loop. The 3 interrupted cells are re-run on resume; completed cells are cached and cost nothing to re-score.

**Sample size: arm A has 1 completed run (+1 rejected first attempt), arm B has 2 completed runs. This is far too small to support any general claim.**

## 44. Results against the frozen reference (v1, primary)
Denominators: 21 verified reference steps (19 demonstrated-or-both, 20 narrated-or-both, 1 demonstrated-only, 2 narrated-only). "Lenient" lets one generated step cover several reference steps; "strict" is one-to-one. Window = 38–92 s (the demonstration).

| Metric | A1 (v2) | B1 (v3) | B2 (v3) |
|---|---|---|---|
| Steps returned (accepted) | 3 | 12 | 5 |
| Demonstrated-step recall, lenient (strict) | 0.21 (0.05) | 0.68 (0.53) | 0.37 (0.16) |
| Narrated-step recall, lenient (strict) | 0.25 (0.10) | 0.65 (0.45) | 0.35 (0.10) |
| Overall recall, lenient (strict) | 0.24 (0.10) | 0.67 (0.48) | 0.38 (0.14) |
| Demonstrated-only recall (1 step) / narrated-only recall (2 steps) | 0 / 0.5 | 1.0 / 0.5 | 1.0 / 0.5 |
| Recall inside the 38–92 s demonstration | **0.00** | **0.62** | **0.00** |
| Precision, lenient (strict) | 1.00 (1.00) | 0.92 (0.92) | 1.00 (1.00) |
| Unmatched generated steps | 0 | 1 (s10, untimed) | 0 |
| Timestamp within tolerance (median abs error) | 0.33 (5.0 s) | 0.73 (2.0 s) | 0.80 (2.0 s) |
| Expected-state recall / wrong rate (matched steps with predicates) | n/a | 0.43 / 0.50 | 1.0 / 0.0 |
| Order inversions / prerequisite violations | 0 / n/a | 0 / 0 | 0 / n/a |
| Verifiable steps | 3 of 3 | 9 of 12 | 5 of 5 |
| Broad (≥ 3 reference steps) generated steps | 1 | 2 | 1 |
| Unverified reference steps covered (reported apart) | 1 of 3 | 2 of 3 | 2 of 3 |
| First-attempt valid | **no** | **yes** | **yes** |
| Rejected extraction attempts | 1 (+ A3: 1) | 0 | 0 |
| Latency | 29 s | 25 s | 50 s |
| Tokens (prompt / output / thinking) | 36.2k / 1.5k / 1.7k (2 calls) | 18.6k / 3.3k / 2.3k | 18.6k / 1.0k / 1.7k |
| Notional cost (all calls of the cell, failed ones included) | $0.039 | $0.035 | $0.024 |
| Approx. cost per correct usable step\* | $0.039 | $0.0044 | $0.0061 |

\* matched one-to-one **and** start within tolerance; rounded from shares; the matching is automatic.
Against the post-hoc v2 reference the picture is the same (demonstrated recall A1 0.18, B1 0.68, B2 0.36; B1's "F after joining" step now matches). Files: `eval_data/results/34FBeC9mktE.e1-partial.scored-v1.json` and `...scored-v2-posthoc.json` (metrics only; raw outputs are not in the repository).

### Merged, split, unmatched and "both" steps
A step covering several reference steps (B1's s04 covers R09, R10 and R11) earns lenient credit for each and one strict credit; it is also listed as broad. Two generated steps for one reference step earn one recall credit (the second is listed as a duplicate). An unmatched generated step is **not** counted as a hallucination automatically. Steps that are both narrated and demonstrated count in both recalls; the demonstrated-only and narrated-only rows exist because "both" dilutes each. Generated steps without timestamps (B1's s10) cover nothing.

### Hallucination and correctness: hand labels
After scoring, I labelled every accepted generated step against the frames (assistant-read, post hoc, so weaker than a frozen reference). *Supported* = the action is visibly in the video at about that time; *partly* = the core action is real but a stated detail is unverified or contradicted; *unsupported* = the action does not occur.
| Run | Supported | Partly supported | Unsupported |
|---|---|---|---|
| A1 | 1 (separate) | 2 (A1's s01 says Tab is pressed, but the overlay at about 28 s reads "Left Mouse"; s02 says Object > Join is clicked, only Ctrl+J is visible) | 0 |
| B1 | 8 (s04–s10, s12; s10 is real but untimed) | 4 (s01, s02, s03: dropdown/face-selection details; s11: F after the join is real, but "connected with an edge" is not visible, and B1 missed the **failing** F demonstration at 136–157 s) | 0 |
| B2 | 3 | 2 | 0 |
So **no step of either arm was found to be an invented action**. The baseline's invention was in *time*: its rejected first attempts placed real steps after the end of the video. The hand labels are not a hallucination rate: the reference has gaps, and claims inside unsampled gaps were checked only where an output made a specific claim.

## 45. Is the 00:58–01:25 demonstration now covered?
The demonstration actually spans about **38–91 s**.
| Reference step | Time | A1 | B1 | B2 |
|---|---|---|---|---|
| R04 move (G) in Edit Mode | 38–47 | no | **s02/s03** (32–44) | no |
| R06 Ctrl+Z ×2 restores the cube | 49–53 | no | **no** | no |
| R07 Tab to Object Mode | 54–56.5 | no | **no** | no |
| R08 Ctrl+Z back into Edit Mode | 56.5–61 | no | **no** | no |
| R09 select vertices, move/rotate | 62–72 | no | **s04** (60–77, merged) | no |
| R10 Tab to Object Mode | 72–74.5 | no | **s04** (merged) | no |
| R11 rotate in Object Mode | 74.5–83 | no | **s04** (merged) | no |
| R12 Ctrl+Z repeatedly (×28) | 83–91 | no | **s05** (82–88) | no |
Answer: **partly, in one of two `v3` runs.** B1 recovered 5 of 8 of these (R09–R11 only as one merged step), including the Ctrl+Z ×28 undo, but missed the 49–61 s undo/Tab/undo sequence. B2 skipped the entire window; the baseline skipped it too. Whether a step covers its reference was decided by the deterministic rules, not by me.

## 46. New problems and regressions
- **`v3` is not consistent.** Same prompt and model: 12 steps and 62% window coverage in B1, 5 steps and 0% in B2. That variance is as large as the effect being measured.
- **`support` carries no information.** Every step of both arms (v3 and v2) says `both`, including steps nobody mentions in speech (Shift+D duplicate, armature). The composite confidence is therefore capped at 0.9 for all of them and still does not separate good from weak steps.
- **Expected-state quality is weak.** B1's undo step expects `OBJECT` where the reference says `EDIT_MESH` (flagged as non-informative by the validator), and two steps share identical start/expected states. State wrong-rate on B1's matched steps was 0.50 (a few predicates).
- **An untimed step** (B1 s10) is unusable for seeking the player; this is the intended "null instead of guess", but it makes the step unmatched.
- **Cost per run is similar, tokens are not.** `v3` spent more output and thinking tokens in B1 but less in B2; both cost about the same as the baseline's two-call run.
- **The reference had defects** (see §40), found only because outputs made claims in unsampled gaps. A frozen reference built from sparse frames can under-count real actions and so understate precision.

## 47. Cost, actual versus estimated
| Item | Value |
|---|---|
| Real charge | **$0** (free tier) |
| Notional cost of E1 as run (from recorded usage × listed prices; thinking tokens included) | **$0.121** (A1 $0.039, A3's one response $0.023, B1 $0.035, B2 $0.024; 429 and 503-only calls $0) |
| Calls | 15 HTTP attempts, 940 video-seconds |
| Budget used | 4% of the $3.00 hard cap (the run's own cap was $2.50 notional) |
| Pre-run worst-case estimate for these 6 cells | about $0.93 (16,384-token output cap) |
| Not measured | whether 503/429 responses are billed on a paid key; the exact free-tier quota that was exceeded |

## 48. Does the evidence support keeping the improved approach?
**Not yet adopted, but worth keeping as the working candidate.** Evidence for: first-attempt validity 2 of 2 (v3) against 0 of 7 recorded v2 runs that returned content; timestamps within tolerance 0.73–0.80 against 0.33; far more demonstrated actions recovered in B1; no invented action found among 20 hand-labelled steps; similar cost. Evidence against adopting: n = 1 vs 2; recall variance as large as the gain; B2 missed the whole demonstration, so the pre-set criterion "core recall ≥ 0.6" was met by 1 of 2 runs; `support` does not discriminate. The causal story (what exactly fixed the timestamps) is untested: `v3` changed the time format, the duration phrasing, the null-instead-of-guess rule and the coverage instructions together, so I cannot attribute the gain to any one of them.

## 49. Limitations
One video; 3 completed cells; the reference is assistant-read and unverified by a human; the reference has sampling gaps and known defects; matching terms are mine and were fixed before the run but are crude; hand labels are post hoc; no run-to-run variance estimate for arm A; free-tier capacity and quota limited the experiment; the second video and a segment arm were not run.

## 50. Next experiment (needs the quota back; ≤ about $0.5 notional)
1. **Resume** the same command after the daily quota resets: `python -m ingestion.experiment run --video 34FBeC9mktE --arms A,B --repeats 3`. Completed cells are cached; it re-runs A2, A3, B3 only (about 3 cells, about $0.12 notional) and stops on any 429.
2. **Then add arm C: window prompting on top of `v3`** (e.g. four 60 s windows with the exact range in the prompt) to test H2 and the B2 failure. Each window call re-sends the whole video (about 18k tokens), so a run costs about 4 × $0.03 notional; offsets for YouTube URLs remain unverified, and this is the cheapest way to test them.
3. **A human check of the reference** (about 20 minutes, with frames at the sampling gaps) before scoring more outputs; then score everything against a v3 reference built by a person.
4. A second video with a reference (the 11-minute [hTL6AKR8YDs](https://www.youtube.com/watch?v=hTL6AKR8YDs) is the candidate) only after step 1 gives at least 3 completed cells per arm.
If billing is enabled the quota problem goes away; that is your decision, and it changes how participant data may be handled (§33).

## 51. Status log (continued)
| Date | Update |
|---|---|
| 2026-10-10 | Reference v1 frozen; evaluator, runner, v3 prompt and schema 0.3 built; 102 offline tests pass. E1 run interrupted by the free-tier daily quota after 6 cells (3 completed). Partial, directional results recorded. Reference v2 (post-hoc) created. Resume pending quota. |

## 52. Resume attempt and the exact free-tier limit (2026-10-10, later)
- A tiny probe passed, so I cleared the ledger's quota stop (recorded in `runs/ledger.json` history) and re-ran the same command. Cached cells A1 and B1 were reused with no call. The first new cell (A2) was refused with HTTP 429, so nothing new completed and the experiment results in §44 are unchanged.
- I then made one direct request to capture the full error text (a refused call costs nothing). It names the quota: **`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, limit 20 requests per day per model, for `gemini-3.6-flash`**, with a retry delay of about 5 h 29 min. The earlier tiny probe was not representative: the limit counts requests, not tokens, and 503 responses very likely count towards it (E1 made 15 HTTP attempts, 8 of them 503s, 1 a connection reset).
- Consequences: (1) the daily budget for this model is about 20 requests, so a full 3 × 3 comparison with the current 503 rate needs more than one day; (2) the runner's `--max-calls` should be kept at or below 18 per day on a free key; (3) changing to another model to escape the limit would change the variable under test and is not done; (4) enabling billing removes this limit (the user will do so later).
- Resume (after the reset, around 5.5 h after this entry): `python -m ingestion.experiment run --video 34FBeC9mktE --arms A,B --repeats 3 --max-calls 18`. Only A2, A3 and B3 are missing; the ledger stop must be cleared once after the reset (see history entry).
