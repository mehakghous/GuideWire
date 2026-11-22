# PyInstaller recipe for GuideWire.exe.   Build:   python installer/build_windows.py     (or: pyinstaller installer/guidewire.spec)
# Result: dist/GuideWire/GuideWire.exe plus its libraries (a folder, not one big file: it starts faster and antivirus tools trust it more).
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent

# Read-only data the app reads at run time, placed at the same relative paths the source tree uses (modules find them relative to their own location).
datas = [
    (str(ROOT / "knowledge"), "knowledge"),
    (str(ROOT / "shared" / "examples"), "shared/examples"),
    (str(ROOT / "demo" / "data"), "demo/data"),
    (str(ROOT / "vision" / "toolbars.json"), "vision"),
    # Files the learner installs INTO Blender / Maya / Houdini (the read-only probes). Shipped next to the app, with a short guide.
    (str(ROOT / "vision" / "blender_addon"), "integrations/blender"),
    (str(ROOT / "vision" / "probes"), "integrations/probes"),
    (str(ROOT / "installer" / "README-integrations.txt"), "integrations"),
    (str(ROOT / ".env.example"), "."),
]
if (ROOT / "shared" / "menus").exists():                                  # the exact-menu-path data, once that feature is part of this branch
    datas.append((str(ROOT / "shared" / "menus"), "shared/menus"))

hiddenimports = (collect_submodules("winrt")                              # Windows OCR (the winrt-* packages are namespace packages PyInstaller cannot follow on its own)
                 + ["winrt.windows.media.ocr", "winrt.windows.graphics.imaging", "winrt.windows.storage.streams",
                    "winrt.windows.globalization", "winrt.windows.foundation", "winrt.windows.foundation.collections"])

a = Analysis(
    [str(ROOT / "installer" / "guidewire_entry.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "matplotlib", "IPython", "notebook", "tests", "fastapi", "uvicorn", "scipy", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="GuideWire",
    console=False,                                                        # a windowed app: no black console window
    icon=str(ROOT / "installer" / "guidewire.ico") if (ROOT / "installer" / "guidewire.ico").exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="GuideWire")
