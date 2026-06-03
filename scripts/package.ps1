$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$EntryPoint = Join-Path $ProjectRoot "app\main.py"

if (-not (Test-Path $Python)) {
    throw "Virtual environment Python was not found at $Python"
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name ScheduleHelper `
    --paths $ProjectRoot `
    $EntryPoint

