$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$App = Join-Path $Root "app"
$Venv = Join-Path $Backend ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"

function Step($i, $total, $msg) {
    Write-Host ""
    Write-Host "[$i/$total] $msg" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== INSTALL MOI TRUONG DEV (lan dau / doi may) ===" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Khong tim thay Python trong PATH. Cai Python 3.11+ tu https://python.org"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "Khong tim thay npm trong PATH. Cai Node.js 18+ tu https://nodejs.org"
}

Step 1 5 "Tao Python venv..."
if (-not (Test-Path $VenvPython)) {
    python -m venv $Venv
    if (-not (Test-Path $VenvPython)) { throw "Khong tao duoc venv" }
    Write-Host "  Da tao venv" -ForegroundColor Green
} else {
    Write-Host "  Venv da co san" -ForegroundColor Green
}

Step 2 5 "Cai Python packages (fastapi, patchright, pyinstaller...)"
& $VenvPython -m pip install --disable-pip-version-check -q --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade that bai" }
& $VenvPython -m pip install --disable-pip-version-check -q -r (Join-Path $Backend "requirements.txt")
& $VenvPython -m pip install --disable-pip-version-check -q pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install that bai" }
Write-Host "  Da cai xong Python packages" -ForegroundColor Green

Step 3 5 "Tai Chromium browser (de bundle vao installer)..."
$env:PYTHONIOENCODING = "utf-8"
& $VenvPython -m patchright install chromium
if ($LASTEXITCODE -ne 0) { throw "patchright install chromium that bai" }
Write-Host "  Chromium browser da san sang" -ForegroundColor Green

Step 4 5 "Cai Node packages (electron, electron-builder)..."
Push-Location $App
try {
    if (-not (Test-Path "node_modules")) { npm install }
    else { Write-Host "  node_modules da co san" -ForegroundColor Green }
} finally {
    Pop-Location
}
if ($LASTEXITCODE -ne 0) { throw "npm install that bai" }

Step 5 5 "HOAN TAT!"
Write-Host ""
Write-Host "Cac lenh tiep theo co the dung:" -ForegroundColor Cyan
Write-Host "  start.bat         - chay dev (backend + electron)" -ForegroundColor Gray
Write-Host "  build.bat         - build installer (se bundle browser vao)" -ForegroundColor Gray
Write-Host "  fetch-browser.bat - tai lai Chromium browser khi co phien ban moi" -ForegroundColor Gray
Write-Host ""
