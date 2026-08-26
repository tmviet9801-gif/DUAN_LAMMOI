# AutoTool License Server

Quản lý license cho thuê — Supabase DB + FastAPI + admin dashboard SPA.

**Kiến trúc:** offline HMAC (server sinh key, app tự xác thực bằng chữ ký).  
Key giống hệt scheme `backend/license.py` — **SECRET phải khớp** để key dùng được trong app.

---

## Yêu cầu

- Python 3.11+
- Supabase project (PostgreSQL free tier đủ dùng)

## Cài đặt

### 1. Tạo Supabase project

1. Vào [supabase.com](https://supabase.com) → New Project
2. Vào **SQL Editor** → chạy `schema.sql` → chạy `seed.sql`
3. Vào **Project Settings → API**: copy `Project URL` + `service_role key`

### 2. Cấu hình

```bash
cd license-server
cp .env.example .env
# Sửa .env:
#   SUPABASE_URL = https://your-project.supabase.co
#   SUPABASE_SERVICE_KEY = eyJ...
#   ADMIN_PASSWORD = mat-khau-admin
#   LICENSE_SECRET = phai-giong-backend-license.py-SECRET
```

### 3. Chạy

```bash
start.bat
# hoặc
start.ps1
# mở http://localhost:8001
```

---

## API endpoints

| Method | Path | Auth | Mô tả |
|--------|------|------|-------|
| POST | `/api/admin/login` | — | Nhận mật khẩu → trả token |
| GET | `/api/stats` | Bearer | Dashboard thống kê |
| GET | `/api/licenses` | Bearer | Danh sách license (filter `?status=active`) |
| POST | `/api/licenses` | Bearer | Cấp license mới |
| PATCH | `/api/licenses/:id` | Bearer | Cập nhật (ghi chú, tên...) |
| POST | `/api/licenses/:id/extend` | Bearer | Gia hạn + ngày |
| POST | `/api/licenses/:id/reset` | Bearer | Reset (cấp lại key, đổi máy/tab) |
| POST | `/api/licenses/:id/status` | Bearer | Đổi trạng thái (revoke/suspend/active) |
| DELETE | `/api/licenses/:id` | Bearer | Xóa license + lịch sử |
| GET | `/api/licenses/:id/events` | Bearer | Lịch sử thay đổi |
| GET | `/api/plans` | Bearer | Danh sách gói |
| POST | `/api/plans` | Bearer | Thêm gói |
| PATCH | `/api/plans/:id` | Bearer | Sửa gói |
| DELETE | `/api/plans/:id` | Bearer | Xóa gói |
| POST | `/api/public/verify` | — | App gọi online kiểm tra license (tùy chọn) |

---

## Cấu trúc DB (Supabase)

- **plans**: gói thuê (tên, tab tối đa, giá, số ngày mặc định)
- **licenses**: license key + machine_id + khách + thời hạn + trạng thái
- **license_events**: audit log (issue/extend/reset/revoke...)

---

## Kết nối với app desktop

Không cần sửa app. Chỉ cần:
1. `LICENSE_SECRET` trong `.env` **giống hệt** `SECRET` trong `backend/license.py`
2. Key sinh từ server → nhập vào app → app xác thực offline thành công

Muốn app tự động gọi online verify: sửa `backend/license.py` gọi `POST /api/public/verify` — đây là bước optional.

---

## Các gói mẫu (seed)

| Gói | Tab | Giá/tháng | Ngày |
|-----|-----|-----------|------|
| Dùng thử | 3 | 0 | 7 |
| Cơ bản 10 tab | 10 | 200.000 | 30 |
| Pro 20 tab | 20 | 350.000 | 30 |
| Vô hạn 50 tab | 50 | 600.000 | 30 |