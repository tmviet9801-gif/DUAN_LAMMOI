/**
 * vai_tro_ban.js — phân định vai trò ANCHOR / SUB trong một lượt gom bàn.
 *
 * VÌ SAO TÁCH RA
 *
 * "Ai rời bàn trước sau khi xả xong" trong dự án này KHÔNG phải một cuộc bầu
 * chọn phân tán như công cụ Sunwin làm (máy nào đang giữ lượt lúc mặt bàn
 * trống thì tự nhận vai người ra trước). Bên mình đã có trọng tài tập trung:
 * một tiến trình Python duy nhất ấn định `__AUTOTOOL_MATCH_ROLE` cho từng
 * trang TRƯỚC khi vào ván (matching.py). Cách của Sunwin không có trọng tài
 * nên vừa kẹt được (không ai nhận) vừa trùng được (hai máy cùng nhận) — port
 * sang chỉ là nhập khẩu cả hai lỗi đó.
 *
 * Lỗ hổng thật nằm ở ĐƯỜNG DỰ PHÒNG: khi thiếu vai trò, bản cũ đoán theo hình
 * dạng tên profile — `includes("1")` là chính, `includes("2")` là phụ. Với tên
 * thật của người dùng (`nicktestxxabai1`, `nicktestxxabai2`) thì:
 *   - `Account 12` thoả CẢ HAI  -> vừa là chính vừa là phụ;
 *   - tên không có chữ số nào   -> KHÔNG AI là phụ, nên không ai rời bàn.
 * Đúng hai triệu chứng mà cơ chế của Sunwin cũng mắc, nhưng ở đây sửa được
 * dứt điểm vì đã có trọng tài.
 *
 * Vì vậy: vai trò CHỈ đọc từ giá trị do Python đặt. Không tên, không suy đoán.
 *
 * Module thuần — không đụng window/document/localStorage/cc/Date — nên nạp và
 * kiểm thử được bằng node với dữ liệu thật, giống card_logic.js và partner_id.js.
 */
(function (root) {
  "use strict";

  /** Chuẩn hoá về đúng một trong ba: "anchor" | "sub" | "".
   *
   * Mọi giá trị lạ (null, số, object, "dump", "winner", "sub2"…) đều thành ""
   * — tức "chưa biết". Hỏng theo hướng AN TOÀN: chưa biết thì không tự rời bàn.
   */
  function chuanHoaVaiTro(v) {
    if (typeof v !== "string") return "";
    const t = v.trim().toLowerCase();
    return (t === "anchor" || t === "sub") ? t : "";
  }

  /** Có phải nick PHỤ không — nick phụ là nick tự rời bàn sau khi xả xong. */
  function laVaiPhu(v) {
    return chuanHoaVaiTro(v) === "sub";
  }

  /** Có phải nick CHÍNH không — nick chính ở lại giữ bàn.
   *
   * `laNguoiKhoiXuong` là cờ `__is_hunt_initiator`, cũng do Python đặt chứ
   * không suy từ tên, nên giữ làm đường dự phòng là hợp lệ. Nhưng khi Python
   * đã nói "sub" thì cờ đó KHÔNG được lật ngược lại.
   */
  function laVaiChinh(v, laNguoiKhoiXuong) {
    const t = chuanHoaVaiTro(v);
    if (t === "anchor") return true;
    if (t === "sub") return false;
    return !!laNguoiKhoiXuong;
  }

  const api = {
    chuanHoaVaiTro: chuanHoaVaiTro,
    laVaiPhu: laVaiPhu,
    laVaiChinh: laVaiChinh,
  };

  root.AutoToolVaiTro = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
