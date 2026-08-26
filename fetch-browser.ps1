$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Venv = Join-Path $Backend ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"

Write-Host ""
Write-Host "=== TAI LAI CAMOUFOX BROWSER ===" -ForegroundColor Cyan

if (-not (Test-Path $VenvPython)) {
    throw "Chua co venv. Chay install.bat truoc."
}

$env:PYTHONIOENCODING = "utf-8"
& $VenvPython -m camoufox fetch
if ($LASTEXITCODE -ne 0) { throw "camoufox fetch that bai" }

Write-Host ""
Write-Host "  Xong! Chay build.bat de dong goi vao installer." -ForegroundColor Green
Write-Host ""
