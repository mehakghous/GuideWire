# GuideWire

AI-powered interactive desktop tutorial and task assistance system for character rigging and animation in Blender, Maya and Houdini.
GuideWire turns YouTube tutorials, written instructions or direct questions into guided on-screen sessions: it watches the application window,
highlights the tool for each step, and checks whether the step was completed. It only observes; the learner performs every action.

FAST University, Karachi Campus. Department of SE. FYP 2026-27.

## Team

| Member | Area | Folder |
|---|---|---|
| Ayesha Raza | Tutorial understanding, step generation, AI gateway | `/ingestion`, `/gateway` |
| Umaima Fatima | Screen capture, UI detection and overlay | `/vision` |
| Mehak | App UI, accounts, session engine | `/app` |

## Project structure

```
/ingestion   tutorial understanding and step generation (Ayesha)
/gateway     AI Gateway: the only service that holds provider keys (Ayesha)
/vision      screen capture, grounding, overlay (Umaima)
/app         UI, accounts, session engine (Mehak)
/shared      shared step format (shared/step_record.py, schema 0.7)
/docs        SRS, SDS and diagrams
/tests       tests for all components
```

## Required versions

- Python 3.11
- Blender: write the exact version here (everyone uses the same one)
- Blender layout: default layout, screen at 1920x1080 (or the same display scaling), so screenshots are comparable across team members

## Setup

1. Clone the repo.
2. Create and activate a virtual environment (Windows):
   ```
   py -3.11 -m venv venv
   venv\Scripts\activate
   ```
3. Install dependencies: `pip install -r requirements.txt` (add `ruff` for linting).
4. Copy `.env.example` to `.env` and fill in your keys. **Never commit `.env`.**

## Run and test

```
python -m pytest -q          # offline tests; live API tests are deselected
ruff check .                 # lint
python -m ingestion.cli --help
python -m ingestion.cli purge   # delete YouTube-derived run logs and caches older than 30 days
python -m ingestion.cli ask --app maya "Create joints down the arm\nCreate an IK handle on the leg"   # written rigging steps -> validated step list
python -m ingestion.cli features steps.json   # which features a step list teaches, and what it assumes
python -m ingestion.cli find --app maya "make the legs move properly" [--live] [--recency off|low|normal|high]   # plain-language goal -> ranked tutorials
python -m ingestion.cli score steps.json --rubric tests/fixtures/rubrics/maya_fkik_leg.json   # actionability rubric (structure only)
python -m ingestion.cli instructions steps.json   # add how-to / check lines from a step list own evidence
python -m ingestion.cli chain steps.json [-o out.json]   # fill missing expected states from the knowledge base; check each step starts from what earlier steps made
python -m ingestion.cli ask --app maya "my knee flips when I move the ik handle"   # a described problem -> sourced cause and fix (route rigging_knowledge)
python -m ingestion.cli captions VIDEO_ID --app maya --duration SECONDS   # DEV ONLY (unofficial endpoint): a real tutorial transcript -> steps
python -m ingestion.cli review show steps.json   # then: review edit ... / review promote steps.json --by YOU --request "<text>"
```

AI Gateway (needs `GATEWAY_TOKENS` and the provider keys in `.env`; one worker only, see `gateway/app.py`):

```
python -c "from gateway.app import main; main()"
```

Endpoints: `POST /v1/extract`, `POST /v1/answer`, `GET /v1/youtube/metadata`, `GET /v1/youtube/search`. Every request needs
`Authorization: Bearer <token>`; `/v1/extract` also needs an `Idempotency-Key` header (1 to 128 characters).

## Git rules

- Nobody pushes directly to `main`.
- Each person works on their own branch, named `yourname/short-task-name`.
- Open a pull request for every change. Another team member reviews it before it is merged.
- Pull `main` before starting a new branch.

## Documents

SRS, SDS and diagrams are kept in `/docs`. Log every change in the Document History table.
