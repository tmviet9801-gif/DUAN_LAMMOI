$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$VenvPython = Join-Path $Backend ".venv\Scripts\python.exe"

Write-Host ""
Write-Host "=== RUN TESTS ===" -ForegroundColor Cyan

if (-not (Test-Path $VenvPython)) {
    throw "Chua co venv. Chay install.bat truoc."
}

Write-Host "[1/2] Cai test dependencies (pytest, httpx)..." -ForegroundColor Yellow
& $VenvPython -m pip install --disable-pip-version-check -q -r (Join-Path $Backend "requirements-test.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install that bai" }

Write-Host "[2/2] Chay pytest..." -ForegroundColor Yellow
Push-Location $Backend
try {
    & $VenvPython -m pytest tests -v --tb=short
    if ($LASTEXITCODE -ne 0) { throw "CO TEST THAT BAI" }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "HOAN TAT! Tat ca tests PASS." -ForegroundColor Green
Write-Host ""
