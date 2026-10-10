# Draft: written questions to YouTube / Google (for Ayesha to send)

Status: **DRAFT, not sent.** I cannot send it for you. Replace the bracketed fields, send it from the Google account that owns the API project, and keep the reply (with date) in `docs/compliance/` so it can be cited in the SRS and the final report.

Where to send: I could not verify a current policy-question channel. The YouTube API support page I checked (developers.google.com/youtube/v3/support, 2026-10-10) lists only an issue tracker for bugs and feature requests, which is the wrong place. Look for the YouTube API Services contact / compliance form linked from the Developer Policies page or from the API project in Google Cloud Console, and use the Gemini API support route for question 3. If neither works, ask FAST's supervisor whether the university has a Google contact.

---

**Subject:** Policy clarification requested: educational research project using YouTube Data API metadata and Gemini URL video input

Hello,

We are three final-year students at FAST-NUCES Karachi (project "GuideWire", supervisor: [name]). GuideWire is a non-commercial research prototype that helps a learner follow a Blender tutorial: it turns a tutorial into a list of steps and highlights the matching tool on the learner's own screen. Our API project is [project name / number].

What we do and do not do:
- We call the YouTube Data API (`videos.list`, and `search.list` within the default quota) for title, duration, licence, embeddability, privacy status and chapters in the description.
- We play videos only in the YouTube embedded player.
- For step extraction we pass the video's public URL to the Gemini API as video input. We do not download, store or process video, audio or frames ourselves, and we do not scrape captions or transcripts.
- We store only the resulting step lists (text, with the video ID and timestamps), never media, and we treat YouTube-derived data as a cache refreshed or deleted within 30 days until we hear back.

Questions (we would like written answers so we can cite them in our report):

1. Does a step list generated from a public video by a model given only the video URL count as "new or derived data or metrics" under Developer Policies III.E.4.h?
2. May we keep step structures keyed to a video ID, with no media, for longer than 30 days (for example for the duration of an academic study)? If not, is deleting or refreshing them every 30 days sufficient?
3. Are outputs of Gemini API video analysis of a public YouTube URL subject to any additional YouTube terms or restrictions (for example on storage, redistribution or display)?
4. Is it permitted for an application to retrieve the public caption track of a video it does not own, by any method other than `captions.download` (which requires edit permission)? If not, is it permitted for a learner to paste or upload a transcript or subtitle file that they obtained themselves, to be used only as a reference for the same learner's session?

We would also welcome any guidance on keeping a small evaluation set of about 5 public videos, Creative Commons where possible, for the duration of our project.

Thank you,
[Name], [reg. no.], [university email]
On behalf of Umaima Fatima, Ayesha Raza and Mehak (FAST-NUCES Karachi, Department of SE)

---

Until written answers arrive, the plan assumes the safest reading: all four answers "no / not permitted", i.e. 30-day cache, no caption retrieval, user-supplied transcripts only. See section 26 of `docs/ingestion-technical-plan.md`.
