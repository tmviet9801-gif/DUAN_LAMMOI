# Capture template join cmd=308 THẬT từ profile đang mở.
# Dùng khi auto "Tìm & xả" vẫn không join được: bạn tự join 1 bàn bằng tay
# 1 lần để bắt đúng format lệnh join, rồi dán kết quả cho dev.
#
# Cách dùng:
#   1. Mở app, mở profile (vd Account01) và ĐĂNG NHẬP xong.
#   2. Chạy:  tools\capture_join.bat   (hoặc capture_join.ps1)
#   3. Script sẽ reload profile + bật WS hook.
#   4. Trong cửa sổ profile, tự BẤM VÀO 1 BÀN để join (như chơi thật).
#   5. Quay lại script bấm Enter -> script lấy template join + room id.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Root   # lên project root

Write-Host ""
Write-Host "=== CAPTURE JOIN TEMPLATE (HITCLUB) ===" -ForegroundColor Cyan
$profile = Read-Host "Ten profile (mặc định Account01)" 
if (-not $profile) { $profile = "Account01" }

# 1) kiểm tra backend
try {
    Invoke-RestMethod -Uri "http://127.0.0.1:17832/health" -TimeoutSec 5 | Out-Null
} catch {
    Write-Host "Backend KHONG chay (port 17832). Hay mo app truoc." -ForegroundColor Red
    exit 1
}

# 2) bật hook + reload (capture từ đầu)
$body = @{ profile_name = $profile; reload = $true } | ConvertTo-Json
$r = Invoke-RestMethod -Uri "http://127.0.0.1:17832/api/autoplay/debug-ws-hook" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 30
Write-Host "Hook da bat cho $profile (reload)." -ForegroundColor Green

Write-Host ""
Write-Host ">>> Trong cua so profile $profile, hay TU BAM VAO 1 BAN de JOIN (nhu choi that)." -ForegroundColor Yellow
Write-Host ">>> Khi da vao duoc phong (thay ban choi), quay lai day va bam Enter..." -ForegroundColor Yellow
Read-Host ""

# 3) đọc capture
$uri = "http://127.0.0.1:17832/api/autoplay/join-capture?profile_name=$([uri]::EscapeDataString($profile))"
$cap = Invoke-RestMethod -Uri $uri -TimeoutSec 20

Write-Host ""
Write-Host "=== KET QUA ===" -ForegroundColor Cyan
Write-Host "Messages: $($cap.message_count)"
Write-Host "Last room id: $($cap.last_room_id)"
Write-Host ""
Write-Host "Ban (rid/rn/uC/b/gid/Mu):" -ForegroundColor Green
$cap.rooms | ForEach-Object { Write-Host "  rid=$($_.rid) rn=$($_.rn) uC=$($_.uC) b=$($_.b) gid=$($_.gid) Mu=$($_.Mu)" }
Write-Host ""
Write-Host "JOIN TEMPLATE (dung template nay de B join cung ban A):" -ForegroundColor Green
if ($cap.has_template) {
    Write-Host $cap.join_template
} else {
    Write-Host "  (chua bat duoc cmd=308 SEND — co the ban chua JOIN duoc, thu lai.)" -ForegroundColor Red
}
Write-Host ""
