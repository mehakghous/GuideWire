"""What the installed app depends on: where it reads and writes, the self-test, and the installer files staying in step with the app (no Windows installer is built here)."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

from shared import paths
from shared.version import APP_VERSION

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("GUIDEWIRE_HOME", raising=False)
    for k in ("GEMINI_API_KEY", "YOUTUBE_API_KEY"):
        monkeypatch.delenv(k, raising=False)


# ---------------------------------------------------------------------------------------------- where things live
def test_in_development_everything_stays_in_the_repository(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert not paths.is_frozen()
    assert paths.writable_root() == paths.repo_root() == paths.resource_root() == ROOT
    before = Path.cwd()
    assert paths.prepare_runtime() is None and Path.cwd() == before          # no folder is created, the working directory is not changed


def test_an_installed_build_reads_from_its_bundle_and_writes_to_the_users_folder(monkeypatch, tmp_path):
    local = tmp_path / "Local"
    bundle = tmp_path / "bundle"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    assert paths.is_frozen() and paths.resource_root() == bundle
    assert paths.writable_root() == local / "GuideWire" and paths.env_file() == local / "GuideWire" / ".env"
    monkeypatch.chdir(tmp_path)
    assert paths.prepare_runtime() == local / "GuideWire"
    assert Path.cwd() == local / "GuideWire"                                   # relative paths such as local_data/ and runs/ now land somewhere writable
    monkeypatch.chdir(tmp_path)


def test_guidewire_home_overrides_the_writable_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("GUIDEWIRE_HOME", str(tmp_path / "portable"))
    assert paths.writable_root() == tmp_path / "portable"


def test_the_env_file_is_loaded_without_overriding_what_is_already_set(monkeypatch, tmp_path):
    monkeypatch.setenv("GUIDEWIRE_HOME", str(tmp_path))
    (tmp_path / ".env").write_text("GEMINI_API_KEY=from-file\nYOUTUBE_API_KEY=also-from-file\n", encoding="utf-8")
    monkeypatch.setenv("YOUTUBE_API_KEY", "already-set")
    assert paths.load_env() is True
    assert os.environ["GEMINI_API_KEY"] == "from-file" and os.environ["YOUTUBE_API_KEY"] == "already-set"


def test_the_discovery_cache_follows_the_writable_folder():
    from app.discovery import CACHE_PATH
    assert CACHE_PATH == paths.writable_root() / "local_data" / "discovery_cache.json"


# ---------------------------------------------------------------------------------------------- the self-test
def test_the_selftest_reports_json_and_a_failing_check_does_not_hide_the_others(tmp_path, monkeypatch):
    pytest.importorskip("PyQt6")
    from app import selftest
    monkeypatch.setenv("GUIDEWIRE_HOME", str(tmp_path / "home"))
    ran = []
    monkeypatch.setattr(selftest, "CHECKS", [("first", lambda: ran.append("first") or "fine"), ("second", lambda: 1 / 0), ("third", lambda: ran.append("third") or "also fine")])
    out = tmp_path / "report.json"
    assert selftest.run(str(out)) == 1                                         # one failure: a non-zero exit code
    report = json.loads(out.read_text(encoding="utf-8"))
    assert ran == ["first", "third"] and report["passed"] is False and report["version"] == APP_VERSION
    assert [(r["check"], r["ok"]) for r in report["results"]] == [("first", True), ("second", False), ("third", True)]
    assert "ZeroDivisionError" in report["results"][1]["detail"]


def test_the_real_selftest_passes_from_the_source_tree(tmp_path, monkeypatch):
    pytest.importorskip("PyQt6")
    pytest.importorskip("cv2")
    from app import selftest
    monkeypatch.setenv("GUIDEWIRE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    skip = () if sys.platform == "win32" else ("screen reading (OCR)",)       # the Windows OCR engine only exists on Windows
    out = tmp_path / "report.json"
    code = selftest.run(str(out), skip=skip)
    report = json.loads(out.read_text(encoding="utf-8"))
    assert code == 0 and report["passed"], [r for r in report["results"] if not r["ok"]]


def test_main_handles_selftest_without_opening_a_window(monkeypatch, tmp_path):
    pytest.importorskip("PyQt6")
    from app import selftest
    from app.ui import main_window
    called = {}
    monkeypatch.setattr(selftest, "run", lambda out=None, skip=(): called.update(out=out) or 0)
    assert main_window.main(["--selftest", "--selftest-out", str(tmp_path / "r.json")]) == 0
    assert called["out"] == str(tmp_path / "r.json")


# ---------------------------------------------------------------------------------------------- the installer files agree with the app
def test_the_installer_script_has_the_apps_version_and_a_stable_id():
    iss = (ROOT / "installer" / "guidewire.iss").read_text(encoding="utf-8")
    assert re.search(r'#define AppVersion "' + re.escape(APP_VERSION) + '"', iss), "bump the default AppVersion in installer/guidewire.iss with shared/version.py"
    assert "PrivilegesRequired=lowest" in iss                                   # installs without administrator rights
    assert "{localappdata}\\GuideWire" in iss and "UninstallSilent" in iss      # asks before deleting user data, never in a silent uninstall
    assert "Excludes: \"__pycache__" in iss


def test_the_pyinstaller_recipe_bundles_the_data_the_app_reads():
    spec = (ROOT / "installer" / "guidewire.spec").read_text(encoding="utf-8")
    for needle in ("knowledge", "shared\" / \"examples", "toolbars.json", "blender_addon", "probes", ".env.example", "winrt", "console=False"):
        assert needle in spec, needle
    for rel in ("knowledge", "shared/examples", "vision/toolbars.json", "vision/blender_addon", "vision/probes", "installer/README-integrations.txt", ".env.example", "installer/guidewire_entry.py"):
        assert (ROOT / rel).exists(), rel
