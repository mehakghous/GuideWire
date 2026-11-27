# Manual tests: the small guide stays when GuideWire is minimized (28 Nov 2026)

**What was wrong.** Minimizing GuideWire (the title bar, or "Minimize GuideWire" in the session) to open Blender made the small guide disappear for good. The window system hides a minimized window before the main window records that it was minimized, so the hide was taken for leaving the session: the session was paused, a paused session is not watched, and the guide was hidden and never came back.

**What changed.** A hide sent by the window system (a minimize) no longer pauses the session or hides the guide. Leaving the session page (Back, the sidebar, logging out, closing) still pauses it where it is, as before.

Setup: Command Prompt, from the repository folder, with Blender open and the GuideWire probe add-on enabled:

```
python -m app.ui.main_window
```

1. Log in, open a Blender tutorial and start a session with "Watch my screen" on. Expected: the small guide shows at the side with the step.
2. Minimize GuideWire with the title-bar button. Expected: the small guide stays on screen and the highlight keeps following Blender.
3. Click GuideWire in the taskbar to restore it. Expected: the session is still on the same step and not paused; the small guide is still there.
4. Press "Minimize GuideWire" in the session screen (shown while watching). Expected: the same as step 2.
5. Do a step in Blender while GuideWire is minimized. Expected: the step completes by itself when Blender shows it done; restore GuideWire and it is on the next step.
6. With the session open press Back (or choose Home in the sidebar). Expected: the guide disappears and History shows the session as paused at that step; Continue brings it back.
