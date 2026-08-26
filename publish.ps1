param(
    [string]$Version = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$App = Join-Path $Root "app"
$Release = Join-Path $App "release"
$Owner = "tmviet9801-gif"
$Repo = "DUAN_LAMMOI"

function Get-GitHubToken {
    if ($env:GH_TOKEN) { return $env:GH_TOKEN }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "git"
    $psi.Arguments = "credential fill"
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $p = [System.Diagnostics.Process]::Start($psi)
    $p.StandardInput.Write("protocol=https`nhost=github.com`n")
    $p.StandardInput.Close()
    $out = $p.StandardOutput.ReadToEnd()
    $p.WaitForExit()
    $m = [regex]::Match($out, "password=(.+)")
    if (-not $m.Success) { throw "Khong lay duoc GitHub token. Dua GH_TOKEN hoac chay 'git push' 1 lan." }
    return $m.Groups[1].Value
}

function Get-CurrentVersion {
    $pkg = Get-Content (Join-Path $App "package.json") -Raw | ConvertFrom-Json
    return $pkg.version
}

function Set-Version($v) {
    $pkgPath = Join-Path $App "package.json"
    $pkg = Get-Content $pkgPath -Raw | ConvertFrom-Json
    $pkg.version = $v
    $pkg | ConvertTo-Json -Depth 5 | Set-Content $pkgPath -Encoding UTF8

    $cfgPath = Join-Path $Backend "models\config_model.py"
    $cfg = Get-Content $cfgPath -Raw
    $cfg = [regex]::Replace($cfg, 'APP_VERSION = "[\d.]+"', "APP_VERSION = `"$v`"")
    Set-Content $cfgPath $cfg -Encoding UTF8
    Write-Host "  Version: $v" -ForegroundColor Green
}

$token = Get-GitHubToken
$headers = @{ Authorization = "token $token"; "User-Agent" = "AutoTool" }

$current = Get-CurrentVersion
if ($Version) {
    $new = $Version
} else {
    $parts = $current.Split(".")
    $new = "$($parts[0]).$($parts[1]).$([int]$parts[2] + 1)"
}

Write-Host ""
Write-Host "=== PUBLISH Auto Tool: $current -> $new ===" -ForegroundColor Cyan

if ($new -ne $current) {
    Set-Version $new
    git -C $Root add app/package.json backend/config.py
    git -C $Root commit -m "Release v$new"
    git -C $Root push origin main
} else {
    Write-Host "  (Version giu nguyen: $new)" -ForegroundColor DarkGray
}

if (-not $SkipBuild) {
    Write-Host "[1/3] Build backend.exe..." -ForegroundColor Yellow
    & (Join-Path $Backend "build_backend.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Build backend that bai" }

    Write-Host "[2/3] Build installer..." -ForegroundColor Yellow
    Push-Location $App
    try {
        & "C:\Program Files\nodejs\npx.cmd" electron-builder --win --publish never
        if ($LASTEXITCODE -ne 0) { throw "electron-builder that bai" }
    } finally {
        Pop-Location
    }
}

$installer = Get-ChildItem -Path $Release -Filter "Auto-Tool-Setup-$new.exe" | Select-Object -First 1
if (-not $installer) {
    $installer = Get-ChildItem -Path $Release -Filter "*Setup-$new.exe" | Select-Object -First 1
}
$blockmap = Join-Path $Release "$($installer.BaseName).exe.blockmap"
$latestYml = Join-Path $Release "latest.yml"

$assetName = "Auto-Tool-Setup-$new.exe"
$assetBlockmap = "Auto-Tool-Setup-$new.exe.blockmap"

# Don dep cac file release cu (chi giu ban moi nhat)
Get-ChildItem -Path $Release -File -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -notlike "*$new*" -and $_.Name -ne "latest.yml"
} | Remove-Item -Force -ErrorAction SilentlyContinue

Write-Host "[3/3] Tao GitHub Release v$new + upload assets..." -ForegroundColor Yellow

$tag = "v$new"
$existing = $null
try {
    $existing = Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repo/releases/tags/$tag" -Headers $headers
} catch { }

if (-not $existing) {
    $body = @{
        tag_name = $tag
        name = "Auto Tool v$new"
        body = "Ban phat hanh Auto Tool v$new"
        draft = $false
        prerelease = $false
    } | ConvertTo-Json
    $release = Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$Owner/$Repo/releases" -Headers $headers -Body $body
    Write-Host "  Release tao thanh cong: $($release.html_url)" -ForegroundColor Green
} else {
    $release = $existing
    Write-Host "  Release da ton tai, cap nhat assets..." -ForegroundColor Yellow
}

function Upload-Asset($releaseId, $filePath, $assetName) {
    $uploadHeaders = @{
        Authorization = "token $token"
        "User-Agent" = "AutoTool"
        "Content-Type" = "application/octet-stream"
    }
    # Xoa asset cu trung ten truoc khi upload de tranh loi 422
    try {
        $assets = Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repo/releases/$releaseId/assets" -Headers $headers
        foreach ($a in $assets) {
            if ($a.name -eq $assetName) {
                Invoke-RestMethod -Method Delete -Uri "https://api.github.com/repos/$Owner/$Repo/releases/assets/$($a.id)" -Headers $headers
                Write-Host "  Xoa asset cu: $assetName" -ForegroundColor Yellow
            }
        }
    } catch { }
    try {
        $resp = Invoke-RestMethod -Method Post `
            -Uri "https://uploads.github.com/repos/$Owner/$Repo/releases/$releaseId/assets?name=$assetName" `
            -Headers $uploadHeaders -InFile $filePath
        Write-Host "  Uploaded: $assetName ($([Math]::Round((Get-Item $filePath).Length / 1MB, 1)) MB)" -ForegroundColor Green
    } catch {
        Write-Host "  Upload $assetName that bai: $($_.Exception.Message)" -ForegroundColor Red
    }
}

Upload-Asset $release.id $installer.FullName $assetName
if (Test-Path $blockmap) {
    Upload-Asset $release.id $blockmap $assetBlockmap
}
if (Test-Path $latestYml) {
    Upload-Asset $release.id $latestYml "latest.yml"
}

Write-Host "  Xoa cac release cu (chi giu ban moi nhat $tag)..." -ForegroundColor Yellow
$allReleases = Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repo/releases" -Headers $headers
foreach ($old in $allReleases) {
    if ($old.tag_name -ne $tag) {
        Invoke-RestMethod -Method Delete -Uri "https://api.github.com/repos/$Owner/$Repo/releases/$($old.id)" -Headers $headers
        Write-Host "  Da xoa release cu: $($old.tag_name)" -ForegroundColor Green
    }
}
# Xoa tag cu di kem
$tags = Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repo/tags" -Headers $headers
foreach ($t in $tags) {
    if ($t.name -ne $tag -and $t.name -match "^v\d") {
        try {
            Invoke-RestMethod -Method Delete -Uri "https://api.github.com/repos/$Owner/$Repo/git/refs/tags/$($t.name)" -Headers $headers
            Write-Host "  Da xoa tag cu: $($t.name)" -ForegroundColor Green
        } catch { }
    }
}

Write-Host ""
Write-Host "HOAN TAT! Nguoi dung o cac may da cai se nhan thong bao update tu dong." -ForegroundColor Green
Write-Host "Release: https://github.com/$Owner/$Repo/releases/tag/$tag" -ForegroundColor Cyan
