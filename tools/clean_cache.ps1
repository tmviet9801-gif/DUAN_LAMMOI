# Script dọn dẹp bộ nhớ đệm cache và rác dự án
# Giữ nguyên 100% tài khoản, phiên đăng nhập, cookie và cấu hình

$baseDir = Split-Path -Parent $PSScriptRoot
$profilesDir = Join-Path $baseDir "backend\data\profiles"
$debugDir = Join-Path $baseDir "backend\data\game_sim_debug"
$testViewDir = Join-Path $baseDir "backend\data\test_view"
$scratchDir1 = Join-Path $baseDir "scratch"
$scratchDir2 = Join-Path $baseDir "backend\scratch"

Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "   DỌN DẸP BỘ NHỚ ĐỆM & TỐI ƯU DUNG LƯỢNG DỰ ÁN" -ForegroundColor Yellow
Write-Host "=================================================" -ForegroundColor Cyan

# 1. Dọn dẹp Cache trình duyệt Chrome (Giữ lại Cookies & LocalStorage)
if (Test-Path $profilesDir) {
    Write-Host "[1/4] Đang dọn dẹp Web Cache / Shader / GPU Cache các profile..." -ForegroundColor Green
    $cacheDirs = @("Cache", "Code Cache", "GPUCache", "DawnGraphiteCache", "DawnWebGPUCache", "Crashpad", "BrowserMetrics", "GrShaderCache", "ShaderCache")
    Get-ChildItem $profilesDir -Directory | ForEach-Object {
        $p = $_.FullName
        foreach ($c in $cacheDirs) {
            $t1 = Join-Path $p $c
            if (Test-Path $t1) { Remove-Item $t1 -Recurse -Force -ErrorAction SilentlyContinue }
            $t2 = Join-Path $p "Default\$c"
            if (Test-Path $t2) { Remove-Item $t2 -Recurse -Force -ErrorAction SilentlyContinue }
        }
        $sw = Join-Path $p "Default\Service Worker\CacheStorage"
        if (Test-Path $sw) { Remove-Item $sw -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

# 2. Xóa ảnh chụp debug & profile test cũ
Write-Host "[2/4] Đang dọn dẹp ảnh chụp debug và thư mục test tạm..." -ForegroundColor Green
if (Test-Path $debugDir) { Remove-Item "$debugDir\*" -Recurse -Force -ErrorAction SilentlyContinue }
if (Test-Path $testViewDir) { Remove-Item $testViewDir -Recurse -Force -ErrorAction SilentlyContinue }

# 3. Dọn thư mục scratch
Write-Host "[3/4] Đang dọn dẹp các tệp nháp tạm thời..." -ForegroundColor Green
if (Test-Path $scratchDir1) { Remove-Item "$scratchDir1\*" -Recurse -Force -ErrorAction SilentlyContinue }
if (Test-Path $scratchDir2) { Remove-Item "$scratchDir2\*" -Recurse -Force -ErrorAction SilentlyContinue }

# 4. Dọn Python cache
Write-Host "[4/4] Đang dọn dẹp Python cache (__pycache__, .pytest_cache)..." -ForegroundColor Green
Get-ChildItem $baseDir -Recurse -Filter "__pycache__" -Directory -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem $baseDir -Recurse -Filter ".pytest_cache" -Directory -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "  DỌN DẸP HOÀN TẤT! DỰ ÁN ĐÃ ĐƯỢC TỐI ƯU NHẸ BÉN!" -ForegroundColor Yellow
Write-Host "=================================================" -ForegroundColor Cyan
