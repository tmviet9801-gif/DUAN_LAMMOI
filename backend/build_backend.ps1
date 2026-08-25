$ErrorActionPreference = "Stop"
$Backend = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $Backend ".venv\Scripts\python.exe"
$VenvPip = Join-Path $Backend ".venv\Scripts\pip.exe"

Write-Host "=== Build backend.exe (PyInstaller) ===" -ForegroundColor Cyan

if (-not (Test-Path $VenvPython)) {
    Write-Host "[1/3] Tao venv..." -ForegroundColor Yellow
    python -m venv (Join-Path $Backend ".venv")
}

Write-Host "[1/3] Cai pyinstaller..." -ForegroundColor Yellow
& $VenvPip install --disable-pip-version-check -q pyinstaller

Write-Host "[2/3] Build backend (co the mat 3-8 phut)..." -ForegroundColor Yellow
Push-Location $Backend
try {
    & $VenvPython -m PyInstaller --noconfirm --clean backend.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller that bai" }
} finally {
    Pop-Location
}

$exe = Join-Path $Backend "dist\tab-manager-backend.exe"
if (-not (Test-Path $exe)) { throw "Khong tim thay backend.exe" }

Write-Host "[3/3] Hoan tat: $exe" -ForegroundColor Green
Write-Host "($(([Math]::Round((Get-Item $exe).Length / 1MB, 1))) MB)" -ForegroundColor Green
