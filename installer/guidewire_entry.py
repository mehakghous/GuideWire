"""Entry point of the installed app (PyInstaller builds GuideWire.exe from this file)."""
import sys

from app.ui.main_window import main

if __name__ == "__main__":
    sys.exit(main())
