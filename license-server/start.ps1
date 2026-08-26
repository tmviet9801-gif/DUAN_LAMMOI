$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
if (-not (Test-Path ".venv")) {
    Write-Host "Tao venv..."
    python -m venv .venv
    & ".venv\Scripts\python.exe" -m pip install --upgrade pip
    & ".venv\Scripts\python.exe" -m pip install -r requirements.txt
}
& ".venv\Scripts\python.exe" -m uvicorn server:app --host 0.0.0.0 --port 8001 --reload