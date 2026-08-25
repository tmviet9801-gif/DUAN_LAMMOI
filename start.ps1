$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$App = Join-Path $Root "app"
$Venv = Join-Path $Backend ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$VenvPip = Join-Path $Venv "Scripts\pip.exe"

Write-Host ""
Write-Host "=== TAB MANAGER ===" -ForegroundColor Cyan

if (-not (Test-Path $VenvPython)) {
    Write-Host "[1/4] Tao Python venv..." -ForegroundColor Yellow
    python -m venv $Venv
    if (-not (Test-Path $VenvPython)) { throw "Khong tao duoc venv. Kiem tra Python da cai chua." }
} else {
    Write-Host "[1/4] Venv da co san" -ForegroundColor Green
}

Write-Host "[2/4] Cai dependencies backend..." -ForegroundColor Yellow
& $VenvPip install --disable-pip-version-check -q -r (Join-Path $Backend "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install that bai" }

Write-Host "[3/4] Kiem tra browser Camoufox..." -ForegroundColor Yellow
$env:PYTHONIOENCODING = "utf-8"
& $VenvPython -m camoufox fetch
if ($LASTEXITCODE -ne 0) { throw "camoufox fetch that bai" }

if (-not (Test-Path (Join-Path $App "node_modules"))) {
    Write-Host "[3.5/4] Cai dependencies Electron..." -ForegroundColor Yellow
    Push-Location $App
    try { npm install } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "npm install that bai" }
} else {
    Write-Host "[3.5/4] node_modules da co san" -ForegroundColor Green
}

Write-Host "[4/4] Khoi dong ung dung (backend + Electron)...\n" -ForegroundColor Yellow
Push-Location $App
try {
    npm start
} finally {
    Pop-Location
}
