# Start Blender or Maya for hands-on testing of the screen guidance, with GuideWire's read-only probe loaded.
#
#   powershell -ExecutionPolicy Bypass -File scripts\start_for_testing.ps1 blender
#   powershell -ExecutionPolicy Bypass -File scripts\start_for_testing.ps1 maya
#
# Blender: opens with the probe add-on registered (scripts/blender_test_harness.py), default layout.
# Maya:    opens with the probe registered through a small MEL file. (Overriding MAYA_SCRIPT_PATH stops Maya from starting, so it is not used.)
# Close the Blender splash screen after it opens, then start the app: python -m app.ui.main_window
param([Parameter(Mandatory = $true)][ValidateSet("blender", "maya")][string]$App)

$repo = Split-Path -Parent $PSScriptRoot
$repoFwd = $repo -replace "\\", "/"

if ($App -eq "blender") {
    $exe = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
    if (-not (Test-Path $exe)) { throw "Blender 5.2 not found at $exe" }
    New-Item -ItemType Directory -Force -Path (Join-Path $env:TEMP "blenderrun") | Out-Null
    Start-Process -FilePath $exe -ArgumentList "--factory-startup", "--python", "`"$repo\scripts\blender_test_harness.py`""
    "Blender started. Close the splash screen; keep the Layout workspace in Object Mode."
}
else {
    $exe = "C:\Program Files\Autodesk\Maya2027\bin\maya.exe"
    if (-not (Test-Path $exe)) { throw "Maya 2027 not found at $exe" }
    $dir = Join-Path $env:TEMP "guidewire_maya"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $py = @"
import sys
sys.path.insert(0, "$repoFwd")
sys.path.insert(0, "$repoFwd/vision/probes")
import maya.utils
def go():
    import maya_probe
    maya_probe.register()
maya.utils.executeDeferred(go)
"@
    Set-Content -Path "$dir\gw_probe_start.py" -Value $py -Encoding ascii
    $mel = 'evalDeferred("python(\"exec(open(r''' + ($dir -replace "\\", "/") + '/gw_probe_start.py'').read())\")");'
    Set-Content -Path "$dir\gw_probe_start.mel" -Value $mel -Encoding ascii
    Start-Process -FilePath $exe -ArgumentList "-script", ("`"" + ($dir -replace "\\", "/") + "/gw_probe_start.mel`"")
    "Maya started (it takes 1-2 minutes). The probe registers by itself once it is up."
}
