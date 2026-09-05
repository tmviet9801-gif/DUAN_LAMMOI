# Quy Tắc Điều Khiển & Tìm Bàn Game (HitClub)

## 1. ĐIỀU CẤM TUYỆT ĐỐI (CRITICAL FORBIDDEN ACTIONS)
- **TUYỆT ĐỐI KHÔNG BẤM NÚT "TẠO BÀN"**:
  - Lý do: Bàn tự tạo trong game bắt buộc phải đặt mật khẩu (pass). Người chơi khác muốn vào phải có pass và game không hỗ trợ tính năng mời người chơi ngoài vào bàn tự tạo.
  - Hậu quả: Khách lạ (người chơi khác) hoàn toàn không thể tham gia vào bàn này, làm sai hoàn toàn mục đích của tool (xả bài, đối đầu với khách lạ).
- **CHỈ ĐƯỢC PHÉP**:
  1. Vào qua danh sách bàn công khai có sẵn (Bàn có ID số cụ thể).
  2. Hoặc ghép bàn Chống Vây tự động (bàn cược công khai để khách lạ có thể vào chơi).

## 2. QUY TRÌNH GHÉP VÀO BÀN CỦA ACCOUNT 1 VÀ ACCOUNT 2
- **Trường hợp Bàn Chống Vây (Cược nhanh 100)**:
  - Account 1 vào bàn trống (hoặc bàn có 1 người).
  - Tức thì (<2ms) Extension gửi tín hiệu về Backend Hub, bắn lệnh sang Account 2 gửi packet `[3, "Simms", -1, ""]` để cướp ghế trống trước khi khách lạ tràn vào.
  - Nếu Account 1 thấy đã có khách lạ chiếm đủ ghế: Tự động out bàn để tìm lượt khác.
- **Trường hợp Bàn có ID từ danh sách**:
  - Account 1 chọn bàn có ID công khai `rid`.
  - Account 2 inject packet `[3, "Simms", 1, "<rid>"]` để nhảy thẳng vào cùng bàn.
