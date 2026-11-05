# Real Gemini outputs (post-validation only)

These two files are the ACCEPTED outputs of live runs R1 and R4 on video 34FBeC9mktE
(188 s, "Object and Edit Mode - Blender 2.80 Fundamentals"), as produced by the pipeline of
2026-10-10 (schema 0.1, prompt v1/v2). They are real model outputs after validation.

The raw responses and the rejected first attempts were NOT saved and are not reconstructed here.
They are used only as regression inputs for the semantic checks in ingestion/validate.py.
Nobody has compared their content with the video.


## R5: Maya character rigging Part 9 (2026-10-16)

`R5_maya_part9_v4_raw.json` is the RAW accepted response of one live run (prompt v4, gemini-3.6-flash, 108,268 prompt tokens) on video dc3iRo0hb3g
(19 min, "Maya Character Rigging - Part 9. create FK, IK and Skin leg joint"). Unlike R1/R4 it is the raw model output, not the validated step list.
It is the "before" case for the actionability work: the model put menu paths, settings and values into `evidence` and `visual_evidence` and left `actions`, times
and `expected_state` empty. Nobody has compared its content with the video; the details are what the model says it saw.
