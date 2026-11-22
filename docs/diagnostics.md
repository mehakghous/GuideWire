# Logging and crash reports

Everything here is **local**. GuideWire never sends a log or a crash report anywhere: the project rule is that only AI-gateway data
leaves the app. The learner decides whether to share a file.

## Where the files are
`%LOCALAPPDATA%\GuideWire\logs\` (override with `GUIDEWIRE_LOG_DIR`). Profile > "Problems and logs" opens the folder and the latest report.

| File | What |
|---|---|
| `guidewire.log` (+ `.1` to `.5`) | The log. Rotates at 1 MB, five old files kept. Level `INFO` (override: `GUIDEWIRE_LOG_LEVEL=DEBUG`) |
| `crashes\crash-<time>.txt` | One report per unhandled error (the newest 20 are kept): traceback, versions, context, last 200 log lines |
| `crashes\crash-<time>-native.txt` | A crash with no Python error (a native crash, a killed process), made at the next start from Python's crash handler |
| `native-crash.log` | Python's raw crash output. It holds real paths, so it is turned into a redacted report at the next start and emptied |
| `running.marker` | Exists while the app runs; if it is still there at the next start, the last run ended unexpectedly and the learner is told |

## What is logged
Logger names: `guidewire.app` (start-up, version), `guidewire.session` (a session started, each step done or skipped and by whom, going back),
`guidewire.vision` (screen guidance unavailable and why, a look that failed, the application window not visible, a step that was already true when it started,
a step completed because the screen saw it happen, no probe answering), `guidewire.worker` (a background task failed), `guidewire.qt` (Qt warnings),
`guidewire.crash`. Repeating conditions (a window that is not visible, a failing look) are written at most once a minute (`log_every`).

## What is never written
A redaction filter runs on every line, every traceback and every crash report, and on the text shown in the crash dialog:
- API keys and tokens (Google `AIza...`, `sk-...`, `Bearer ...`, `key=...`, `token=...`, the probe's `X-GuideWire-Token`), passwords, and the **value** of any environment variable whose name says
  key / token / secret / password;
- e-mail addresses;
- the Windows user name in paths (`C:\Users\<user>\...`).
Tutorial text, questions asked, screenshots and the database are never logged.

## What a crash does
1. The error is logged, a report is written, and the learner sees one short notice: "GuideWire hit a problem. You can keep working, and your steps and progress are saved",
   with Open folder, Copy path and Continue. Errors on any thread are caught (Qt slots, background workers, unraisable ones).
2. Several errors in a row show at most one notice per 8 seconds and three per run; all are still logged and reported.
3. If the process dies without an error, the next start says "GuideWire did not close normally last time" and builds the report from Python's crash output.

## For the installer
Use the same folder. Show `APP_VERSION` (`shared/version.py`) in the installer and bump it per release; it is in every log start line and report.

## Code
`shared/diagnostics.py` (Qt-free: redaction, log setup, reports, hooks, marker), `app/crash_ui.py` (the notices, Qt messages, `install(app, window)` called from
`app/ui/main_window.py:main()`), tests `tests/test_diagnostics.py`, `tests/test_crash_ui.py`. Checked live: an error in a Qt slot, an error in a thread, and a hard crash of the
process in the middle of a run, followed by a restart (the notice appears, the native report is redacted, the raw file emptied, and a third clean start shows nothing).
