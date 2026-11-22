GuideWire integrations (optional, read-only)
=============================================

GuideWire works without these. They let it read exact information from your 3D application (the active tool, what you selected, where its tools and menus
are), so highlights are exact and steps can be checked more reliably. They only READ: they never click, type or change your scene. They talk to GuideWire
on this computer only (127.0.0.1, with a one-time password); nothing leaves your machine.

Blender 5.2   integrations\blender\guidewire_probe.py
              Blender > Edit > Preferences > Add-ons > Install from Disk, choose that file, then switch "GuideWire Probe" on.

Maya 2027     integrations\probes\maya_probe.py  (+ probe_core.py in the same folder)
              Open Maya's Script Editor (Python tab), run:
                  import sys; sys.path.append(r"<this folder>\integrations\probes")
                  import maya_probe; maya_probe.register()
              Use the folder you installed GuideWire into. maya_probe.unregister() stops it.

Houdini 22    integrations\probes\houdini_probe.py  (+ probe_core.py in the same folder)
              Same idea in Houdini's Python Shell (prototype: not yet verified on a licensed Houdini).

AI features (answering questions, turning videos into steps) need an API key. Copy .env.example to
    %LOCALAPPDATA%\GuideWire\.env
and fill in GEMINI_API_KEY (and YOUTUBE_API_KEY for searching). Without keys GuideWire still works with its built-in knowledge.

Logs and crash reports are in %LOCALAPPDATA%\GuideWire\logs and never leave your computer.
