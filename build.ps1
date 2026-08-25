$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$App = Join-Path $Root "app"

Write-Host ""
Write-Host "=== BUILD TAB MANAGER (app.exe) ===" -ForegroundColor Cyan

Write-Host ""
Write-Host "[1/4] Build backend.exe..." -ForegroundColor Yellow
& (Join-Path $Backend "build_backend.ps1")
if ($LASTEXITCODE -ne 0) { throw "Build backend that bai" }

Write-Host ""
Write-Host "[2/4] Cai dependencies Electron (npm install)..." -ForegroundColor Yellow
Push-Location $App
try {
    if (-not (Test-Path "node_modules")) { npm install }
    else { Write-Host "  node_modules da co san" -ForegroundColor Green }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "[3/4] Build installer (electron-builder)..." -ForegroundColor Yellow
Write-Host "  Ban co the mat 3-10 phut (tai Electron + NSIS lan dau)." -ForegroundColor DarkGray
Push-Location $App
try {
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "electron-builder that bai" }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "[4/4] HOAN TAT!" -ForegroundColor Green
$release = Join-Path $App "release"
if (Test-Path $release) {
    Get-ChildItem -Path $release -Filter "*.exe" | ForEach-Object {
        Write-Host "  Installer: $($_.FullName) ($([Math]::Round($_.Length / 1MB, 1)) MB)" -ForegroundColor Green
    }
}
Write-Host ""
