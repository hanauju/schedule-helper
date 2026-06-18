$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$EntryPoint = Join-Path $ProjectRoot "app\main.py"
$IconPath = Join-Path $ProjectRoot "app\assets\orot.ico"

if (-not (Test-Path $Python)) {
    throw "Virtual environment Python was not found at $Python"
}

if (-not (Test-Path $IconPath)) {
    throw "Application icon was not found at $IconPath"
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name ScheduleHelper `
    --icon $IconPath `
    --add-data "$IconPath;app/assets" `
    --paths $ProjectRoot `
    $EntryPoint

