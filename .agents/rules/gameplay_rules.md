# Quy Tắc Điều Khiển & Tìm Bàn Game (HitClub)

## 1. ĐIỀU CẤM TUYỆT ĐỐI (CRITICAL FORBIDDEN ACTIONS)
- **TUYỆT ĐỐI KHÔNG BẤM NÚT "TẠO BÀN"**:
  - Lý do: Bàn tự tạo trong game bắt buộc phải đặt mật khẩu (pass). Người chơi khác muốn vào phải có pass và game không hỗ trợ tính năng mời người chơi ngoài vào bàn tự tạo.
  - Hậu quả: Khách lạ (người chơi khác) hoàn toàn không thể tham gia vào bàn này, làm sai hoàn toàn mục đích của tool (xả bài, đối đầu với khách lạ).
- **KHÔNG CLICK TOẠ ĐỘ CANVAS ĐỂ CHỌN MỨC CƯỢC**: node mang nhãn "100" có thể
  thuộc UI khác, và Cocos vẫn giữ mức cược đã chọn ở phiên trước → dễ lọt vào
  bàn $500. Không bắt được socket game thì **báo lỗi / thử lại**, tuyệt đối
  không click mù.
- **CHỈ ĐƯỢC PHÉP**: vào bàn công khai đã có RID xác minh trong bảng
  `FIXED_TABLE_RIDS`.

## 2. FRAME JOIN CHUẨN

Join bàn cố định dùng **một dạng frame duy nhất**:

```
[3, "Simms", <rid>, ""]
```

- `rid` bắt buộc là số **> 0** lấy từ `FIXED_TABLE_RIDS`. Code từ chối mọi
  `rid <= 0` (kể cả `-1`) để không rơi vào auto-join theo state cược cũ.
- Bảng RID xác minh trực tiếp từ gói `cmd 300`:
  `$100 Solo = 2`, `$100 bốn người = 1`, `$500 Solo = 4`, `$500 bốn người = 3`.
  Bảng đầy đủ 28 mức nằm ở `backend/controllers/auto_flow_controller/constants.py`.
- Có chống flood: bỏ qua lệnh join nếu cách lần trước dưới 2.5s.

### `cmd 308` dùng ở đâu

`cmd 308` **vẫn tồn tại**, nhưng không còn dùng để *khởi tạo* join trong luồng
gom bàn tự động:

| Nơi dùng | Vai trò |
|---|---|
| RECV `cmd 308` | Frame server báo **join thành công** — extension lắng nghe để lấy `ri.rid` |
| `POST /api/autoplay/join-rid` | Route **debug thủ công**, gửi 308 kèm `rid`/`b`/`Mu` tường minh |
| Luồng gom bàn tự động | **KHÔNG dùng** — auto-join theo `b`/`Mu` đã bị bỏ vì server có thể lấy mức cược cũ và đưa vào $500 |

Bằng chứng từ `ws_capture`: gửi 308 khi còn đang ngồi trong bàn cũ → server trả
`[4,false,...,102]` (từ chối). Spam 18 lần trong 2s càng làm kẹt vĩnh viễn. Vì
vậy phải qua **cổng xác nhận sảnh** trước khi gửi bất kỳ lệnh join nào.

## 3. QUY TRÌNH GHÉP BÀN (Account chính + nick phụ)

Vai trò do **backend gán** theo profile người dùng chọn trên UI, không suy đoán
theo tên nick: `profile_a` = anchor (chủ bàn), còn lại = sub.

1. **Preflight** — tắt engine săn bàn cũ, gửi lệnh rời bàn, đưa *tất cả* profile
   về sảnh Tiến Lên Đếm Lá **song song**. Anchor không được gửi lệnh join cho
   tới khi mọi nick phụ xác nhận đã đứng đúng sảnh.
2. **Cổng xác nhận sảnh** — tối đa 6 lần kiểm tra `__autotool_is_inside_table()`
   (đọc thẳng scene Cocos, không dựa vào biến nhớ vừa reset). Còn kẹt bàn cũ thì
   LEAVE trước rồi mới join.
3. **Anchor join** bằng `[3,"Simms",<rid>,""]` với RID cố định theo mức cược.
4. **Xác minh bàn** — phải trống (`player_count <= 1`, không có khách lạ) và `b`
   trong gói `cmd 202` phải **đúng bằng** mức cược đã cấu hình. Lệch bất kỳ điều
   kiện nào → out về sảnh, nghỉ 3.5s chống flood, quét lại.
5. **Cổng trước khi mời** — ngay trước khi cấp vé, kiểm lại anchor vẫn đúng
   `rid`, đúng `bet`, và **vẫn ngồi một mình**. Khách lạ chen vào → huỷ mời.
6. **Vé join dùng một lần** — anchor cấp `__AUTOTOOL_SUB_JOIN_TICKET`
   (`rid`/`bet`/`mu`/`anchor`, hết hạn sau 8s). Nick phụ **không có quyền tự
   join**; không có vé hợp lệ thì từ chối. Hub cũng không được tự forward
   RID/mức cược — chỉ controller được phép mời.
7. **Xác minh 2 chiều** — chỉ coi là ghép thành công khi **cả hai bên cùng nhìn
   thấy nhau** trong `__room_players` (so theo `dn` / `u` / `uid`). Tuyệt đối
   không dùng "trùng RID" hay "đếm số người >= 2".
8. **Ready → Start** — phụ bấm SẴN SÀNG, anchor bấm BẮT ĐẦU, mỗi bên chỉ dùng
   helper đúng vai trò. Không gửi Ready/Start cho bàn có khách lạ.
9. **Sau ván** — nick phụ luôn out về sảnh chọn bàn. Account chính chỉ out khi
   bật `auto_leave_after`. Quá 45s chưa xác nhận kết thúc ván → giữ nguyên trạng
   thái và cảnh báo, **không** tự out nick phụ.

## 4. Rời bàn

Lệnh rời bàn dùng `cmd 203` / `[4,"Simms",-1]`. **Không bao giờ** gửi `cmd 308`
trong luồng rời bàn — payload 308 thiếu `b`/`Mu` bị game đưa về bàn mặc định
$500. Có test chặn điều này (`test_leave_command_never_rejoins_default_bet_table`).
