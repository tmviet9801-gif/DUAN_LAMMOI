# Tab Manager - Quản lý đa profile trình duyệt

Ứng dụng desktop quản lý nhiều tài khoản/profile trên các nền tảng: mở nhiều cửa sổ Camoufox cùng lúc, xếp lưới trên màn hình, mỗi profile có fingerprint riêng (UA Chrome, OS, locale) và lưu session đăng nhập riêng.

## Tính năng

- Mở đồng thời nhiều cửa sổ trình duyệt, xếp lưới tự động (cấu hình cột, khoảng cách, lề)
- Kích thước cửa sổ cố định hoặc tự chia đều màn hình; hướng sắp xếp theo hàng/cột
- Mỗi profile có fingerprint riêng: User-Agent Chrome desktop ngẫu nhiên (Windows/macOS/Linux), locale
- Lưu session riêng cho từng profile (cookies, localStorage) — đăng nhập 1 lần, lần sau mở lại không cần login
- Hiển thị tên profile ngay trên tab trình duyệt để nhận biết
- Auto-update: tự kiểm tra bản mới, thông báo và cài đặt 1 nút bấm

## Cài đặt

Tải installer từ GitHub Releases: `Tab Manager-Setup-x.x.x.exe`

## Phát triển

```powershell
# Backend (Python 3.12+)
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m camoufox fetch   # tải browser lần đầu

# Chạy dev
start.bat                  # setup + chạy backend & Electron
```

## Build app.exe

```powershell
build.bat                  # backend.exe -> installer trong app\release\
```

## Phát hành bản mới

1. Sửa `version` trong `app/package.json` và `APP_VERSION` trong `backend/config.py`
2. Chạy `build.bat`
3. Tạo GitHub Release (tag `vX.X.X`), upload `Tab Manager-Setup-x.x.x.exe` + `latest.yml`

## Cấu trúc

```
backend/     FastAPI + Camoufox (đóng gói thành backend.exe)
app/         Electron desktop app
```

## Lưu ý

- Profile/data được lưu tại `%APPDATA%\TabManager\data` (bản cài đặt)
- Camoufox browser (~500MB) tự tải lần đầu sử dụng
