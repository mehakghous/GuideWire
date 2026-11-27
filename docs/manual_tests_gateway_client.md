# Manual tests: the app uses the AI gateway

Setup: in one terminal start the gateway with `GATEWAY_TOKENS=abc123:me`, `GEMINI_API_KEY` and `YOUTUBE_API_KEY` set (`python -c "from gateway.app import main; main()"`). In the app's terminal set
`GUIDEWIRE_GATEWAY_URL=http://127.0.0.1:8000` and `GUIDEWIRE_GATEWAY_TOKEN=abc123`, and **remove** `GEMINI_API_KEY` and `YOUTUBE_API_KEY` from the app's `.env`. Start `python -m app.ui.main_window`.

1. **Video link, no key in the app.** New tutorial, paste a short public Blender video link, Turn into steps. Expect: steps appear with groups; the gateway terminal logs the request. No "put GEMINI_API_KEY in the .env file" message.
2. **Question in Ask.** Ask "what does Edit Mode do?". Expect an answer with sources, and a request in the gateway log.
3. **Find a tutorial.** Find tab, search "rig a leg in Blender". Expect suggestions with titles and lengths.
4. **Wrong token.** Change `GUIDEWIRE_GATEWAY_TOKEN` to `nope`, restart, ask a question. Expect a plain sentence about the sign-in not being accepted; no "401", no class names.
5. **Gateway off.** Stop the gateway, paste a video link. Expect "The GuideWire service could not be reached. Check your internet connection and try again." and nothing else technical.
6. **Daily cap.** Start the gateway with a small `paid_per_day` (or repeat step 1 until the cap) and expect "You have used today's share of video reading..." as a plain sentence.
7. **Unset variables.** Unset both, put the keys back in `.env`, restart: everything works as before (local keys).
