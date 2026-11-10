# GuideWire live demo: set it up and run it yourself

For the supervisor demo (moved to **Nov 12**). Everything below was run on your machine setup before writing it. Commands are for **PowerShell**, from the repo folder `C:\dev\GuideWire`.

## The 60-second map
GuideWire turns a tutorial into steps a learner follows, and watches the screen to guide and check them. It **only observes**: the learner does every action. Three parts, one per person:

| Part | Whose | What you show | Needs |
|---|---|---|---|
| **A. The app** | Mehak | create an account, tutorials, ask questions, add a video link, review and edit steps, run a session | nothing: any new account works |
| **B. The brain** | Ayesha | a real video turned into steps, "where do I start", questions with and without a tutorial | offline works; the model needs your Gemini key |
| **C. The eyes** | Umaima | find Blender's panels, highlight a menu item live | Blender 5.2 open; her branch; OCR packages |

## 1. Set up once (about 5 minutes)

```powershell
cd C:\dev\GuideWire
venv\Scripts\activate
python scripts/demo_check.py
```

- `demo_check.py` is your **preflight**. `[ok]` is ready, `[!!]` means fix it first (it prints the fix), `[--]` is optional. Run it again right before you present. It ends with **READY** or **NOT READY**.
- It proves the journey of a **brand-new account** works (create the account, add demo tutorials, ask where to start, save the steps, review, start a session), off-screen, without opening a window.
- The AI features (a video link, the "Use the AI model" box) need `GEMINI_API_KEY` in the `.env` file, and **Find a tutorial** needs `YOUTUBE_API_KEY` (both are set on your machine). Without a key the app says so and falls back: questions use the rules, discovery uses GuideWire's small local list of 8 tutorials.

## 2. Part A: the app. A new account works from nothing

Anyone can open the app and make their own account, your professor included. Start it:

```powershell
python -m app.ui.main_window
```

| Screen | What to do | What to say |
|---|---|---|
| **Login** | type an email, a password (at least 8 characters) and a name, click **Create account** | accounts are real: passwords are hashed, each account sees only its own tutorials |
| **Home, empty** | the welcome box lists four ways to get content | a new account starts empty, so the app tells you what to do |
| | click **Add demo tutorials** | six real video tutorials (Blender, Maya, Houdini) and three starter plans appear in the list. Clicking twice adds nothing |
| **Find a tutorial** (flow 1: ask for a tutorial, get suggestions) | click it, leave the application on *(from my words)*, type `I am a beginner and want to rig a leg with IK in Maya`, click **Find tutorials** | up to 3 real YouTube videos, ranked, with channel, length and year. It is judged from the title, channel and length only: GuideWire has not watched them, and the screen says so. About 5 seconds and 200 units of the free daily YouTube search quota, no money; asking the same again today is free (saved). Click **Open in browser**, or **Turn this video into steps** (it fills the link in New tutorial; you click **Create steps**). A vague request such as `rig something` makes it ask which application instead of guessing |
| **Ask GuideWire** (flow 3: direct questions, sometimes steps) | click it, choose *maya*, type `where do i start rigging in maya`, press Enter | it answers with a 12-stage plan from our knowledge base. Then click **Save these 21 steps as a tutorial** and go **Back** |
| | tick **Use the AI model** and ask `why do we parent the mesh with automatic weights`, after choosing the Blender tutorial in the **About** list | with a tutorial chosen, answers come from that tutorial's steps; the model adds a real explanation and labels general knowledge |
| **Review steps** | select a tutorial in the list, click **Review steps**, click a step | the detail shows **Part of: <group>**, whether GuideWire can check it, and warnings. Try **Edit text**, **Move up/down**, **Add step**. Do not click **Save** unless you want the change |
| **Start session** | select a tutorial, click **Start session**, then **Start**, **Done**, **Skip**, **Previous step** | progress is saved after every click. **Ask about this tutorial** opens the Ask screen on it |
| **Ask GuideWire**, typing `recommend a tutorial for rigging a leg in maya` | with no tutorial chosen | the same suggestions appear in the chat |
| **New from text or video link** (flow 2: your own tutorial; flow 4: pasted steps) | paste the three lines below and click **Create steps**; or paste a YouTube link | text: no AI, instant. A **link**: the AI watches the video (about **1 minute and 7 cents**, with progress messages), then groups the steps, then they open in the editor |
| **History**, **Profile** | click them | every session; theme, password |

Text to paste (no AI needed):
```
Press Tab to enter Edit Mode
Select the cube
Move it with G
```

A video link that works: `https://www.youtube.com/watch?v=EBgHRd5tJfE` (the Blender armature tutorial). Videos must be public and up to 25 minutes. If the AI is not set up, the app says so and nothing breaks.

**Be honest about:** the highlight on screen is Umaima's part and is not yet wired into the session screen; the app reads steps by itself, it does not yet check them against Blender; the AI parts call Google's model directly on this computer (the proposal's plan is to route them through our own gateway so the keys never sit on a learner's machine).

### Optional: a pre-made account
`python scripts/demo_setup.py --reset` makes a local database with an account `demo@guidewire.test` (password `guidewire-demo-2026`) that already holds the nine tutorials. To use it, start the app with `$env:GUIDEWIRE_DB = "C:\dev\GuideWire\local_data\demo.sqlite"` first. You never need it: any new account can click **Add demo tutorials**.

## 3. Part B: the brain (your part), in the terminal

**3a. A real video turned into steps** (offline, instant):
```powershell
python scripts/demo_show.py demo/data/blender_armature_EBgHRd5tJfE.json
python scripts/demo_show.py demo/data/blender_armature_EBgHRd5tJfE.json --step s02
```
Say: "This came from a 4-minute YouTube tutorial. Gemini 3.6 Flash watched it and wrote 18 small steps, grouped into 8 goals. Each step has the time in the video, the menu to click and a check the system can verify. 61% of steps can be both pointed at and auto-checked; all have a target." The other tutorials are in `demo/data/`.

**3b. "Where do I start?" and steps on request** (offline, no model):
```powershell
python -m ingestion.cli chat --script demo/chat_script.txt
```
Say: "No model was called. A beginner asks where to start in Maya and gets a 12-stage plan from our knowledge base; asked for steps to bind the mesh it writes them out; asked why the knee flips it answers from sourced troubleshooting. Every answer says it comes from the knowledge base, and says what the knowledge base does not cover yet."

**3c. Questions about a loaded tutorial: rules versus the model**
```powershell
python -m ingestion.cli chat --script demo/chat_tutorial.txt
python -m ingestion.cli chat --model-tier iterate --script demo/chat_tutorial.txt
```
The first runs offline. Look at the last question, "why do we parent the mesh with automatic weights": the rules say *the source does not say why, I will not guess*; the second (the model, about 0.1 cent a question) gives a real explanation. Say: "Progress commands such as 'done' and 'what's next' stay rule-based so the model can never move the learner. Everything the model says is labelled when it is general knowledge."

To type your own questions instead of a script, run `python -m ingestion.cli chat --model-tier iterate` and use `/app blender`, then `/load steps demo/data/blender_armature_EBgHRd5tJfE.json`.

**3d. The real pipeline, live** (this video is already in the cache on your machine, so it takes about 5 seconds and costs nothing):
```powershell
python -m ingestion.cli video https://www.youtube.com/watch?v=EBgHRd5tJfE --app blender --rigging --duration 267 -o local_data/live_demo.json
python scripts/demo_show.py local_data/live_demo.json
python -m ingestion.cli group local_data/live_demo.json -o local_data/live_demo_grouped.json
python scripts/demo_show.py local_data/live_demo_grouped.json
```
Say: "That is the real pipeline: the video link goes in, Gemini watches it, steps come out. The last two lines add the display groups with one cheap text call (about a tenth of a cent)." The output says which model and which prompt made it (`gemini-3.6-flash`, `v10-preds`, the measured default).

A **new** video costs up to about 9 cents and takes 1 to 2 minutes, and needs the Gemini key; a repeat of the same video is free. Do a new one only if you have run it before the demo. If anything fails (quota, network), use 3a.

## 4. Part C: the eyes (Umaima's part)

Her live guide is on her branch, `umaima/vision-guide-probe`, not on `main` yet. Open it in a **second folder** so your work is untouched:

```powershell
cd C:\dev\GuideWire
git fetch origin
git worktree add C:\dev\GuideWire-vision origin/umaima/vision-guide-probe
cd C:\dev\GuideWire-vision
C:\dev\GuideWire\venv\Scripts\python.exe -m pip install winrt-runtime winrt-Windows.Media.Ocr winrt-Windows.Graphics.Imaging winrt-Windows.Storage.Streams winrt-Windows.Globalization winrt-Windows.Foundation winrt-Windows.Foundation.Collections
```
The `pip` line installs Windows text reading (OCR), which her guide needs; it is in her branch's requirements. Then, with **Blender 5.2 open in front, default layout**:

```powershell
C:\dev\GuideWire\venv\Scripts\python.exe -m vision.demo --delay 5
C:\dev\GuideWire\venv\Scripts\python.exe -m vision.demo --locate "Add > Mesh > Cylinder"
C:\dev\GuideWire\venv\Scripts\python.exe -m vision.demo --guide "Add > Mesh > Cylinder" --recordable
```
Say: "That menu path is not typed by hand: it is step s02 of the tutorial in Part B. The vision part finds that item on the real screen and highlights it, and the guide ends when the learner clicks it." Then the bridge: "Joining step lists to this guide, so the session screen highlights the current step, is the next integration task." Another real path from the other Blender tutorial: `Add > Armature > Single Bone`.

Her notes (docs/vision.md on her branch): tested on Blender 5.2.3, English UI, default theme, 1920x1080 at 150% scaling. It finds Blender's panels and menu items by reading the screen; it does not yet find every icon-only control, and Maya and Houdini are not started. When finished: `cd C:\dev\GuideWire` then `git worktree remove C:\dev\GuideWire-vision`.

## 5. A 15-minute running order

| Minutes | Do | Who |
|---|---|---|
| 0 to 1 | the problem and the map above | you |
| 1 to 4 | Part A: login, tutorials, review a step list, run a session | you or Mehak |
| 4 to 7 | 3a: a real video as steps; 3d if you pre-ran it | you |
| 7 to 10 | 3b and 3c: where to start, steps, rules versus model | you |
| 10 to 13 | Part C: panels, then the menu item from step s02 | Umaima |
| 13 to 15 | results and limits below, next steps | you |

## 6. The numbers you can quote (all from `docs/evaluation_report_2026-11-09.md`)
- **Step extraction** (6 real videos, 3 repeats each, Gemini 3.6 Flash, about 7 cents a video): about **79% precision** and **37 to 41% one-to-one recall** against hand-labelled actions; **86 to 88% of the labelled actions are found** when matching by meaning; **54 to 61%** of steps can be both pointed at and auto-checked. Houdini is the weakest (33% recall).
- **Questions** (independent grader: a different AI family, 30 fresh questions): **73% useful** (and all 3 requests for a tutorial recommendation were handled correctly: it asks your goal and level and names no video); the video recheck found the right answer **89%** of the time when given a time, and answered "not shown" to **36 of 36** unanswerable questions.
- **Cost**: a video about 7 cents, a question about 0.1 cent.

## 7. What is NOT ready (say it before you are asked)
- The app does not yet highlight on screen or check steps against the running application; its AI parts call the model directly from this computer, not through our gateway.
- Vision finds panels and menu items on Blender only; it cannot yet check Maya or Houdini, or read every icon.
- Extraction is far from perfect: about 4 in 10 labelled actions get their own step.
- All measurements are on 6 videos and one person's labels; Q&A grading is mostly by a model.
- The knowledge base has gaps (units, importing the mesh, the Blender armature step) and the answers say so.

## 8. If something goes wrong
| Problem | Do this |
|---|---|
| `demo_check.py` shows `[!!]` | follow its `fix:` line, then run it again |
| You do not see the demo tutorials | click **Add demo tutorials** on Home (a new account starts empty) |
| Login fails | create a new account, or use the optional pre-made one in part 2 |
| A video link or the AI box says the model is not set up | put `GEMINI_API_KEY` in `.env`, restart the app; or use the offline features |
| A model call fails (key, quota, network) | use the offline commands (3a, 3b and the first command of 3c); they need nothing |
| The vision part does not find the menu | check Blender is in front at the default layout; use `--delay 5` to switch to it; fall back to `--save frame.png` and show the picture |
| Windows asks about the firewall or an overlay blocks clicks | cancel and continue; the overlay only draws, it never takes clicks |
