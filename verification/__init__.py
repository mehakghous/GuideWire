"""Check a StepList against a REAL scene in Blender, Maya or Houdini, headlessly.

Two halves, so the logic is testable without any application:
  * snapshot_<app>.py run INSIDE the application (blender -b / mayapy / hython) and write a small JSON snapshot of the scene;
  * checker.py (plain Python, runs in the project venv) compares each step's `expected_state` with a snapshot.
runner.py finds the installed applications and runs the snapshot scripts.
A predicate the harness cannot read is reported `cannot_check` with the reason; it is never guessed and never counted as met.
"""
