# Manual tests: Ask GuideWire as an assistant (21 Nov 2026)

Automated tests (`tests/test_app_chat_assistant.py`) use a fake YouTube and a fake video pipeline. These check what only a real run shows: the live YouTube search, the real video model, and how the cards look. Start the app with `python -m app.ui.main_window` (needs `YOUTUBE_API_KEY` and `GEMINI_API_KEY` in `.env`), log in, open **Ask**.

| # | Do | You should see |
|---|---|---|
| C1 | Type `can you give 10 tutorials for blender after which i can make whatever i want` | A short intro saying it is an ordered path from the basics (interface, modeling, materials, lighting and rendering, animation, a whole project) and up to 10 cards, each with a `[stage]`, a clickable title, Creator / Length / Published and the link. Not one lonely video. If fewer than 10 are relevant it says so plainly. |
| C2 | Click a card's title | The video opens in your browser. |
| C3 | Type `give me 5 tutorials for rigging a leg with IK in maya`, then `give me 10 more` | 5 cards about leg IK, then more about the SAME goal, none repeated. Every title is about a leg or IK. |
| C4 | Type `give me 10 tutorials` in a fresh chat | A question asking what you want to learn. No search happens. |
| C5 | Type `which one is best for beginners` | A pick from the list above with the reason (title says beginner, a length you can follow), plus "GuideWire has not watched any of them". |
| C6 | Press **Turn into steps** on one card | The card says it is turning the video into steps; the waiting bubble shows the status. After a minute or two: "I made N steps..." with the first steps listed, a guide card, and the card says **Steps ready and saved as a tutorial**. |
| C7 | Go Home, open the tutorials list | The new tutorial is there, with its steps, like any other. |
| C8 | Back in the chat type `explain step 4` | Step 4's goal, how to do it and how to tell it worked, and the time in the video. Nothing that is not in the steps. |
| C9 | Type `what does the instructor do in step 3` and then `what is IK` | The first is answered from the steps. The second is answered as a general answer and is labelled as not from the tutorial. |
| C10 | Press **Review steps** and **Start session** on the card | The review screen / a session opens for that tutorial. Opening Ask again, the chat is in the list on the left and still has its cards and context. |
| C11 | Turn off your network (or use a private video link) and press **Turn into steps** | The card shows why it failed and offers **Retry**; nothing is saved and nothing claims success. Turn the network on and press Retry: it works. |
| C12 | In a new chat type `turn the first one into steps` | A plain message that there is no video to turn into steps yet. |
| C13 | Open a Blender tutorial that never uses the default cube (for example the leg IK one) in a session | **Before you start** offers to delete the default cube (select it, X, Delete). A tutorial that already deletes the default scene does not show it. |

Never checked on a real screen: the card layout at the smallest window size, and the real YouTube/Gemini results for C1 to C3.
