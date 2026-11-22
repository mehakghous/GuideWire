# Windows installer

GuideWire ships as one file, `GuideWire-Setup-<version>.exe` (about 74 MB), built with PyInstaller (the app) and Inno Setup (the installer).

## For the learner
Run the Setup file. It installs **for you only, with no administrator rights**, into `%LOCALAPPDATA%\Programs\GuideWire` (run it as administrator and the
wizard also offers "for all users"). It adds Start Menu shortcuts (the app, the integration files for Blender / Maya / Houdini, an uninstaller) and an optional desktop
shortcut, and registers an uninstall entry in Settings > Apps.

Windows may show a blue "Windows protected your PC" (SmartScreen) page the first time, because the Setup file is **not code-signed** (a signing certificate costs
money and was out of scope for the FYP). Choose "More info" then "Run anyway". The installer was built from this repository by `installer/build_windows.py`.

Your work (saved tutorials, progress, keys, logs) is kept in `%LOCALAPPDATA%\GuideWire`, outside the install folder, so an upgrade or reinstall never loses it. Uninstalling
asks whether to delete that folder too (default: keep); a silent uninstall always keeps it.

AI features need an API key: copy `.env.example` (installed next to the app) to `%LOCALAPPDATA%\GuideWire\.env` and fill in `GEMINI_API_KEY` (and `YOUTUBE_API_KEY` for search).
Without keys the app still runs with its built-in knowledge. Keys are never put in the installer.

## For a developer: build and test
    python installer/build_windows.py --installer
1. PyInstaller builds the app folder from `installer/guidewire.spec` into `%LOCALAPPDATA%\GuideWire-build\dist` (outside the repository on purpose: a repository inside OneDrive
   holds file locks on freshly built folders; override with `GUIDEWIRE_BUILD_DIR`).
2. The **built exe runs its own self-test** (`GuideWire.exe --selftest --selftest-out report.json`): libraries, bundled data files, a writable folder, the database, logging,
   the Windows OCR engine (it draws text and reads it back) and the main window. Any failing check stops the build.
3. Inno Setup (`ISCC.exe`, `winget install JRSoftware.InnoSetup`) compiles `installer/guidewire.iss` into the Setup file.

Checked on this machine with the real build: silent install (23 s, 264 MB on disk), the installed exe's self-test (passes), the real window starting and writing its log,
database and crash marker under the user's folder, and a silent uninstall that removed the install folder, shortcuts and registry entry and kept the user data.

## How the installed app finds its files (`shared/paths.py`)
- Read-only data (knowledge, examples, menu data, toolbar data) is bundled and found relative to each module, exactly as in the source tree.
- Everything the app WRITES goes to `%LOCALAPPDATA%\GuideWire`: the build sets that folder as the working directory, so the many relative paths (`local_data/`, `runs/`) land there,
  and the `.env` and the discovery cache are read and written there. From the repository nothing changes.
- `GUIDEWIRE_HOME` overrides the folder (portable use, tests); `GUIDEWIRE_LOG_DIR` the log folder (see `docs/diagnostics.md`).

## Releasing
1. Bump `APP_VERSION` in `shared/version.py` and the default `AppVersion` in `installer/guidewire.iss` (a test checks they match).
2. Build, then install the Setup file once on a machine and run the app.
3. The version is in every log start line and crash report.

## Known limits
- Not code-signed (SmartScreen warning, above).
- Tested on this Windows 11 machine only. A fresh PC that lacks the Microsoft Visual C++ runtime may need it installed (`vc_redist.x64.exe`); the installer does not bundle it.
- The app folder is large (264 MB installed) because OpenCV (112 MB) and Qt (70 MB) are bundled whole.
- The Maya and Houdini probes are shipped as files for the learner to load; there is no one-click installer for them yet.
- Windows only (the screen guidance uses Windows APIs).
