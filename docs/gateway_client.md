# The app talks to the AI gateway (audit H-2)

**What changed (2026-11-28).** With `GUIDEWIRE_GATEWAY_URL` and `GUIDEWIRE_GATEWAY_TOKEN` set, the app needs no provider key on the learner's computer:

| Feature | Before | With the gateway |
|---|---|---|
| Video link to steps | Gemini called from the app | `POST /v1/extract` (first pass, gap pass, label repair and grouping all run on the gateway) |
| Questions in Ask and in a session | Gemini called from the app | `POST /v1/answer` (`model=true`, with the tutorial and the current step) |
| Find a tutorial | YouTube API called from the app | `GET /v1/youtube/search` and the new `GET /v1/youtube/videos?ids=a,b` |

With neither variable set, nothing changes: the app uses the keys in `.env` (development).

**Where the code is.** `ingestion/gateway_client.py` (the client: idempotency key per request, 503 retried, 429 never, plain messages for 401/502/no network), `app/remote.py` (the app adapters), `app/pipeline.py` (`video_steps(..., gateway=)`),
`app/ui/main_window.py` (`main()` chooses gateway or local keys), `gateway/app.py` (`read_video`, `/v1/youtube/videos`).

**Not done yet (stated, not hidden).**
- The token is still a shared secret in `.env` (`GATEWAY_TOKENS` on the gateway). The audit asks for the learner's Supabase access token instead, verified by the gateway (signature, expiry, audience). That needs the Supabase JWT secret on the gateway and a token refresh in the app: next step.
- "Is this tutorial a good fit" (the model watching the first two minutes of each suggestion) has no gateway endpoint yet, so with the gateway the fit check is skipped and suggestions come from the YouTube results and the built-in list only.
- Counters, tokens and idempotency are in the gateway's memory (one worker), as before.
