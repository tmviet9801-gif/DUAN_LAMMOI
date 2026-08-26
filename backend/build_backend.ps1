$ErrorActionPreference = "Stop"
$Backend = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $Backend ".venv\Scripts\python.exe"
$VenvPip = Join-Path $Backend ".venv\Scripts\pip.exe"
$ReleaseBrowser = Join-Path $Backend "dist\browser"

function Get-CamoufoxInstallDir {
    if ($env:LOCALAPPDATA) {
        $cand = Join-Path $env:LOCALAPPDATA "camoufox\camoufox"
        if (Test-Path $cand) { return $cand }
    }
    return $null
}

Write-Host "=== Build backend.exe (PyInstaller) ===" -ForegroundColor Cyan

if (-not (Test-Path $VenvPython)) {
    Write-Host "[1/4] Tao venv..." -ForegroundColor Yellow
    python -m venv (Join-Path $Backend ".venv")
}

Write-Host "[1/4] Cai pyinstaller..." -ForegroundColor Yellow
& $VenvPython -m pip install --disable-pip-version-check -q pyinstaller

Write-Host "[2/4] Build backend (co the mat 3-8 phut)..." -ForegroundColor Yellow
Push-Location $Backend
try {
    & $VenvPython -m PyInstaller --noconfirm --clean backend.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller that bai" }
} finally {
    Pop-Location
}

$exe = Join-Path $Backend "dist\tab-manager-backend.exe"
if (-not (Test-Path $exe)) { throw "Khong tim thay backend.exe" }
Write-Host "[3/4] Hoan tat backend.exe: $exe" -ForegroundColor Green

Write-Host "[4/4] Dong goi Camoufox browser vao installer..." -ForegroundColor Yellow
$installDir = Get-CamoufoxInstallDir
$browsersSrc = if ($installDir) { Join-Path $installDir "browsers" } else { $null }

if ($browsersSrc -and (Test-Path $browsersSrc)) {
    if (Test-Path $ReleaseBrowser) { Remove-Item -LiteralPath $ReleaseBrowser -Recurse -Force }
    New-Item -ItemType Directory -Path $ReleaseBrowser -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $browsersSrc "*") -Destination $ReleaseBrowser -Recurse -Force
    $size = (Get-ChildItem -LiteralPath $ReleaseBrowser -Recurse -File | Measure-Object Length -Sum).Sum
    Write-Host "  Bundled browser: $ReleaseBrowser ($([Math]::Round($size / 1MB, 1)) MB)" -ForegroundColor Green
} else {
    Write-Host "  Khong tim thay Camoufox browser da fetch ($browsersSrc)." -ForegroundColor Yellow
    Write-Host "  Chay:  .venv\Scripts\python -m camoufox fetch" -ForegroundColor Yellow
    Write-Host "  Sau do build lai de bundle browser vao installer." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== HOAN TAT ===" -ForegroundColor Green
Write-Host "  - Backend: $exe" -ForegroundColor Green
if (Test-Path $ReleaseBrowser) {
    Write-Host "  - Browser: $ReleaseBrowser" -ForegroundColor Green
}
