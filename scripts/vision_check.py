"""Watch the screen the way the app's session does, without the app: a manual check of the vision bridge against the real Blender window.

    python scripts/vision_check.py                                   # 30 s, step s02 of the Blender armature demo tutorial ("Add > Armature > Single Bone")
    python scripts/vision_check.py --seconds 60 --step s05           # start at another step of the same tutorial
    python scripts/vision_check.py --overlay                         # also draw the highlight (a click-through window over Blender)
    python scripts/vision_check.py --no-advance                      # report only; never complete a step
    python scripts/vision_check.py --file path/to/steps.json --app maya

One line per half second: the state, the message the learner would read, the screen rectangle that would be highlighted, the verdict on the step's expected state, and whether the step was
completed because the application showed it done. It only looks: it never clicks, types or moves anything. Needs Windows, the Windows OCR packages and the application open and in front
(see docs/vision_integration.md, "Test it by hand").
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_FILE = ROOT / "demo" / "data" / "blender_armature_EBgHRd5tJfE.json"


def build_session(path: Path, start_step: str):
    """An in-memory session on the steps in `path`, started at `start_step` (the earlier steps are marked done silently)."""
    from app.db import Database
    from app.session_engine import SessionEngine
    from app.step_editor import StepEditor
    db = Database(":memory:")
    uid = db.add_user("check@example.com", b"x")
    tid = StepEditor.from_json_file(path).save(db, uid)
    engine = SessionEngine.create(db, uid, tid)
    engine.start()
    while engine.current_step() is not None and engine.current_step().id != start_step:
        engine.complete()
    if engine.current_step() is None:
        raise SystemExit(f"no step {start_step!r} in {path.name}")
    return db, engine


def wait_for(future, qapp, timeout: float):
    """Wait for a look on the worker thread WITHOUT blocking this thread: Qt events keep being handled (the overlay window belongs to this thread, and the screen reader asks it questions while
    it lists windows: blocking here would deadlock them both), and Ctrl-C works. None when the look takes longer than `timeout` seconds."""
    from concurrent.futures import TimeoutError as FutureTimeout
    end = time.monotonic() + timeout
    while True:
        try:
            return future.result(timeout=0.02)
        except FutureTimeout:
            if qapp is not None:
                qapp.processEvents()
            if time.monotonic() > end:
                return None


def show_box(panel, engine, t, look, qapp, dismissed) -> None:
    """The instruction box next to the application: the step's goal and how-to lines, the hint, Done, Skip and a close button (as in the app)."""
    from app.ui.screen_guide import panel_position
    step = engine.current_step()
    if panel is None or step is None or step.id in dismissed:
        if panel is not None:
            panel.hide()
        return
    panel.set_content(f"GuideWire \u00b7 step {engine.position} of {len(engine.steps)}", step.goal, [h.text for h in step.how_to], t.hint, t.keys, t.inputs)
    scr = qapp.primaryScreen()
    a = scr.availableGeometry()
    x, y, _where = panel_position(look.window_rect, (a.x(), a.y(), a.width(), a.height()), (panel.width(), panel.height()), scr.devicePixelRatio())
    panel.put(x, y)


def format_tick(t0: float, t) -> str:
    rect = "-" if t.rect is None else f"{t.rect[0]},{t.rect[1]} {t.rect[2]}x{t.rect[3]}"
    return f"{time.monotonic() - t0:5.1f}s  {t.state:11s} verdict={t.verdict or '-':12s} highlight={rect:22s} advanced={'YES' if t.advanced else 'no ':3s} {t.hint or t.message}"


def need_the_project_python() -> None:
    """The packages (pydantic, PyQt6, the Windows OCR) live in the project's virtual environment; a plain `python` outside it does not have them."""
    try:
        import pydantic  # noqa: F401
    except ModuleNotFoundError:
        lines = [
            "This python does not have the project's packages (pydantic is missing).",
            "Run it with the project's python instead, from C:\\dev\\GuideWire:",
            "    venv\\Scripts\\activate",
            "    python scripts/vision_check.py --overlay --seconds 40",
            "or:  venv\\Scripts\\python.exe scripts/vision_check.py --overlay --seconds 40",
        ]
        raise SystemExit("\n".join(lines)) from None


def main(argv=None) -> int:
    need_the_project_python()
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--app", default="blender")
    ap.add_argument("--step", default="s02")
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--title", default=None, help="watch the window whose title contains this text (default: the application's own name); useful with two Blender windows open")
    ap.add_argument("--look-timeout", type=float, default=10, help="give up when one look at the screen takes longer than this many seconds")
    ap.add_argument("--overlay", action="store_true", help="draw the highlight over the application")
    ap.add_argument("--no-advance", action="store_true", help="report only, never complete a step")
    a = ap.parse_args(argv)
    from app.vision_bridge import VisionBridge, default_service_factory, target_of
    db, engine = build_session(a.file, a.step)
    factory, finder = default_service_factory, None
    if a.title:
        def factory(app):
            svc = default_service_factory(app)
            svc.title = a.title
            return svc

        def finder(app):
            from vision import winplatform
            w = winplatform.find_window(a.title)
            return None if w is None else (w.rect.x, w.rect.y, w.rect.w, w.rect.h)
    bridge = VisionBridge(factory, auto_advance=not a.no_advance, window_finder=finder)
    guide = None
    qapp = None
    panel = None
    dismissed: list[str] = []
    if a.overlay:
        from PyQt6.QtWidgets import QApplication

        from app.ui.screen_guide import InstructionPanel, ScreenGuide
        qapp = QApplication.instance() or QApplication([])
        guide = ScreenGuide()
        panel = InstructionPanel()
        panel.done_clicked.connect(lambda: engine.complete() if engine.current_step() is not None else None)
        panel.skip_clicked.connect(lambda: engine.skip() if engine.current_step() is not None else None)
        panel.back_clicked.connect(lambda: engine.back() if engine.current_step() is not None and engine.position > 1 else None)
        panel.closed.connect(lambda: dismissed.append(engine.current_step().id) if engine.current_step() is not None else None)
    step = engine.current_step()
    print(f"Tutorial {a.file.name}, app {a.app}. Step {step.id}: {step.goal}")
    print(f"Pointing at: {target_of(step) or '(this step names no UI path)'}.  Open {a.app.title()} in front, default layout. Ctrl-C stops.\n")
    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(1)           # the Windows OCR must not run on a Qt main thread (it hangs there); the app reads the screen on a worker thread too
    t0 = time.monotonic()
    last = None
    try:
        while time.monotonic() - t0 < a.seconds and engine.current_step() is not None:
            step = engine.current_step()
            look = wait_for(pool.submit(bridge.look, step, a.app), qapp, a.look_timeout)
            if look is None:
                print(f"{time.monotonic() - t0:5.1f}s  the screen read took more than {a.look_timeout:g} s and is stuck; stopping (Ctrl-C also works)")
                break
            t = bridge.apply(engine, look)
            line = format_tick(t0, t)
            if line.split("s ", 1)[1] != (last or ""):                # print only when something changed
                print(line)
                last = line.split("s ", 1)[1]
            if guide is not None:
                guide.show(t.rect, look.window_rect) if t.rect is not None else guide.clear()      # a box only: the overlay draws no text (see docs/vision_integration.md)
                show_box(panel, engine, t, look, qapp, dismissed)
                qapp.processEvents()
            if t.advanced and engine.current_step() is not None:
                print(f"      -> next step {engine.current_step().id}: {engine.current_step().goal}   (pointing at {target_of(engine.current_step()) or '-'})")
            pause = time.monotonic() + a.interval
            while time.monotonic() < pause:                              # wait without blocking Qt (the overlay is drawn by this thread)
                if qapp is not None:
                    qapp.processEvents()
                time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        pool.shutdown(wait=False)
        if guide is not None:
            guide.close()
        if panel is not None:
            panel.close()
        db.close()
    print("\ndone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
