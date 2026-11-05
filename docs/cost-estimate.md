# GuideWire: what opening billing would cost (estimate, 2026-10-16)

Everything below is an ESTIMATE built from three measured numbers and clearly marked assumptions. Prices were checked on Google's pricing page on 2026-10-16 and change on **2027-01-01**.

## What was measured

| Measured | Value |
|---|---|
| Model used for video | `gemini-3.6-flash` |
| Price through 2026-12-31 | 0.75 USD input and 3.75 USD output per 1M tokens (thinking tokens count as output) |
| Price from 2027-01-01 | 1.50 USD input and 7.50 USD output per 1M tokens (twice as much) |
| Video input | 108,268 and 108,686 prompt tokens for a 1,151 s video = about **94 tokens per second of video** (about 5,640 per minute) |
| Output + thinking | 2,830 tokens (v4 run) and 3,927 tokens (v5 run) for that video |
| Cost of one 19-minute extraction | **0.092 USD** (v4) and **0.096 USD** (v5) at 2026 prices; **0.18 to 0.19 USD** at 2027 prices |
| Latency | 28 s for the successful v5 call (503 "high demand" failures cost nothing) |

Rule of thumb: **about 0.005 USD per minute of video in 2026, 0.010 USD per minute from 2027.** A 10-minute tutorial is about 0.05 USD, 30 minutes about 0.15 USD, 60 minutes about 0.30 USD (0.60 USD in 2027).

## Things that cost no money
- YouTube Data API: free, limited by quota (10,000 units a day). The searches in this project cost about 402 units so far.
- Everything that runs offline: the transcript reader, the knowledge base, the instruction composer, the scoring, all 600+ tests.
- The captions adapter (unofficial, development only).
- Supabase and a small gateway host: free tiers exist; nothing is deployed yet.

## Scenarios
| Phase | What is spent | Estimate |
|---|---|---|
| Spent so far on live model calls this month | 2 successful video extractions | about **0.19 USD** |
| Rest of development and tests in 2026 (FYP-1) | about 25 more live extractions of about 20 min, some repeated after prompt changes | **2 to 10 USD** (at 2026 prices) |
| FYP-2 evaluation, 2027 prices | 60 tutorials x 30 min x 3 repeats = 5,400 video-minutes | **about 54 USD**; 20 to 60 depending on how many repeats |
| FYP-2 development iterations, 2027 prices | about 100 more extractions of about 20 min | **about 20 USD** |
| Usability study, 12 to 16 beginners, 2027 prices | each session extracts one tutorial (cached after the first person) plus screen-grounding calls | extraction **5 to 15 USD**; grounding **10 to 40 USD** (see assumption below) |
| **Whole project, billing opened for the model only** | | **roughly 50 to 150 USD**, most of it in 2027 |

Assumption that is NOT measured (it belongs to the vision part): one screen-grounding call (one 1080p frame plus a short question) is taken as about 1,500 input and 200 output tokens, about 0.002 USD in 2026 and 0.004 USD in 2027. A session that sends 100 to 300 frames would cost 0.2 to 1.2 USD. Measure it before relying on it.

## How to keep it from running away
- `Limits.max_usd` (default 2.50 per experiment run) already stops an experiment run; the gateway has a per-user daily cap on paid calls (a count, not dollars, yet).
- Set a **Google Cloud billing budget with alert emails** (for example 20 USD) on the project that owns the API key. Do not rely on code alone.
- Extractions are cached per video (the experiment cache key, and the gateway idempotency key), so the same tutorial is paid for once, not once per learner.
- A 60-minute tutorial costs 3 times a 20-minute one. Prefer extracting the chapter a learner needs; chapters are already read from the video description.
- Cheaper model: `gemini-3.5-flash-lite` lists 0.30 USD input and 2.50 USD output per 1M tokens. Earlier runs found it weaker for steps; check quality before switching.
- Lower video resolution reduces tokens per frame; the size of that saving has not been measured here.

## Other cost notes
- Opening billing may or may not reduce the 503 "high demand" errors seen on the current key; that is not something this project can verify from here.
- To my knowledge Google treats free-tier and paid-tier content differently for model improvement; read the current terms before the consent text (SEC-11) is finalised.
- Prices change. Re-check https://ai.google.dev/gemini-api/docs/pricing before any large run; `ingestion/experiment.py` holds the price table and the 2027 switch.
