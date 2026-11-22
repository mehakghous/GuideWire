"""Build the Windows app folder, check it, and (if Inno Setup is installed) the installer.

    python installer/build_windows.py            # app folder + self-test
    python installer/build_windows.py --installer   # ... and GuideWire-Setup-<version>.exe

Output goes to %LOCALAPPDATA%/GuideWire-build/dist (override: GUIDEWIRE_BUILD_DIR), not into the repository.

1. PyInstaller builds <build>/dist/GuideWire/GuideWire.exe from installer/guidewire.spec.
2. The built exe runs its own `--selftest` (libraries, bundled data, database, logging, OCR, window); a failing check stops the build.
3. With --installer, Inno Setup (ISCC.exe) turns the folder into one Setup exe using installer/guidewire.iss.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.version import APP_VERSION  # noqa: E402

# Built OUTSIDE the repository by default: a repository inside OneDrive (or any synced folder) holds file locks on freshly built folders and breaks the next clean build.
BUILD_ROOT = Path(os.environ.get("GUIDEWIRE_BUILD_DIR") or (Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "GuideWire-build"))
DIST = BUILD_ROOT / "dist"
WORK = BUILD_ROOT / "work"
APP_DIR = DIST / "GuideWire"
ISCC_PATHS = [Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe", Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
              Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"]


def build_app() -> None:
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(DIST), "--workpath", str(WORK),
                    str(ROOT / "installer" / "guidewire.spec")], cwd=ROOT, check=True)


def selftest(exe: Path) -> dict:
    """Run the built exe's own self-test in a clean, throw-away user folder, and return its report."""
    with tempfile.TemporaryDirectory() as home:
        out = Path(home) / "report.json"
        env = dict(os.environ, GUIDEWIRE_HOME=home, LOCALAPPDATA=home, QT_QPA_PLATFORM="offscreen")
        for k in [k for k in env if k.endswith("_API_KEY")]:
            env.pop(k)                                                   # the check must not depend on, or touch, real keys
        p = subprocess.run([str(exe), "--selftest", "--selftest-out", str(out)], env=env, timeout=300, cwd=home)
        if not out.exists():
            raise SystemExit(f"the self-test wrote no report (exit code {p.returncode})")
        return json.loads(out.read_text(encoding="utf-8"))


def find_iscc() -> Path | None:
    on_path = shutil.which("ISCC")
    return Path(on_path) if on_path else next((p for p in ISCC_PATHS if p.is_file()), None)


def build_installer() -> Path:
    iscc = find_iscc()
    if iscc is None:
        raise SystemExit("Inno Setup is not installed (ISCC.exe not found). Install it (winget install JRSoftware.InnoSetup) and run again.")
    subprocess.run([str(iscc), f"/DAppVersion={APP_VERSION}", f"/DDistDir={DIST}", str(ROOT / "installer" / "guidewire.iss")], cwd=ROOT, check=True)
    return DIST / f"GuideWire-Setup-{APP_VERSION}.exe"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--installer", action="store_true", help="also build the Setup exe with Inno Setup")
    ap.add_argument("--skip-build", action="store_true", help="reuse dist/GuideWire (only self-test / installer)")
    args = ap.parse_args()
    if not args.skip_build:
        build_app()
    exe = APP_DIR / "GuideWire.exe"
    report = selftest(exe)
    for r in report["results"]:
        print(("PASS " if r["ok"] else "FAIL ") + f"{r['check']:22} {r['detail']}")
    if not report["passed"]:
        return 1
    size = sum(f.stat().st_size for f in APP_DIR.rglob("*") if f.is_file()) / 1e6
    print(f"\nbuilt {exe} ({size:.0f} MB on disk), version {report['version']}, self-test passed")
    if args.installer:
        print(f"installer: {build_installer()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
