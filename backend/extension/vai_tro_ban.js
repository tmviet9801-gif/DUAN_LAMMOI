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

  // ---------------------------------------------------------------------
  // GIỮ BÀN / TỰ ĐÁNH: mình là CHỦ BÀN hay KHÁCH, và lúc này phải làm gì.
  //
  // Sau ván gom bàn, nick chính ở lại bàn (GIỮ BÀN) và luôn là chủ bàn vì nó
  // vào bàn trước. Nút TỰ ĐÁNH cho người dùng tự vào một bàn bất kỳ — có thể
  // là bàn người khác đã ngồi sẵn, khi đó mình là KHÁCH: phải gửi Sẵn sàng,
  // còn Bắt đầu là việc của chủ bàn. Gửi Bắt đầu từ ghế khách thì server bỏ
  // qua, và tool ngồi "chờ khách Sẵn sàng" mãi trong khi chính mình là khách.
  //
  // Dữ liệu thật (bản bắt WS 10/09/2026, khung cmd 202 `ps[]`):
  //   ngồi một mình:            {dn:"nicktestxxabai1", C:true,  r:false, sit:0}
  //   vào bàn đã có chủ:        {dn:"khanh1112221960", C:true,  r:true }
  //                             {dn:"nicktestxxabai1", C:false, r:false}
  // `C` = chủ bàn; `r` = đã Sẵn sàng. Server KHÔNG phát khung 363/aRd cho
  // người khác (75.517 khung bắt được, không khung nhận nào chứa aRd): ai bấm
  // Sẵn sàng/Bắt đầu thì mọi người nhận [5,{uid,dn,cmd:5}], và content_main.js
  // ghi cờ `r` vào danh sách người chơi từ khung đó. `aRd` chỉ còn là cờ tool
  // tự đặt cho chính mình.
  // ---------------------------------------------------------------------

  function laDung(v) {
    return v === true || v === "true" || v === 1;
  }

  /** Người chơi này đã bấm Sẵn sàng chưa. Chỉ nhận true/"true"/1 — mọi thứ
   * khác là CHƯA (hỏng an toàn về phía "không tự làm gì"). */
  function daSanSang(x) {
    if (!x || typeof x !== "object") return false;
    return laDung(x.aRd) || laDung(x.r) || laDung(x.ss) || laDung(x.ready);
  }

  /** Mình có phải CHỦ BÀN không.
   *
   * Ưu tiên cờ `C` của chính mình; rồi cờ `C` của người khác; thiếu hết thì:
   * ngồi một mình -> chủ; có ghế `sit` -> ghế nhỏ nhất là chủ; không có gì để
   * dựa -> coi là CHỦ (đúng hành vi GIỮ BÀN đã chạy thật: chờ khách SS).
   */
  function laChuBan(me, players) {
    const ds = (Array.isArray(players) ? players : []).filter((x) => x && typeof x === "object");
    if (me && typeof me === "object") {
      if (me.C === true || me.C === "true") return true;
      if (me.C === false || me.C === "false") return false;
    }
    if (ds.some((x) => x !== me && (x.C === true || x.C === "true"))) return false;
    if (ds.length <= 1) return true;
    if (!me || typeof me.sit !== "number") return true;
    return ds.every((x) => typeof x.sit !== "number" || x.sit >= me.sit);
  }

  /** Lúc này phải làm gì với bàn đang ngồi (GIỮ BÀN / TỰ ĐÁNH).
   *
   * Trả về một trong:
   *   "dang_van"  ván đang chạy, bộ xả đang lo — không đụng gì;
   *   "cho"       chưa có gì để làm (một mình, khách chưa SS, hoặc tắt tự bắt tay);
   *   "san_sang"  mình là KHÁCH trong bàn người khác và chưa SS -> gửi Sẵn sàng;
   *   "bat_dau"   mình là CHỦ và khách đã SS -> Bắt đầu.
   *
   * `tuBatTay` là ô "Bắt đầu nếu khách SS": tắt thì tool KHÔNG tự Sẵn sàng /
   * Bắt đầu, chỉ tự đánh khi ván đã chạy — người dùng giữ quyền mở ván.
   */
  function hanhDongGiuBan(t) {
    t = t || {};
    if (t.dangVan) return "dang_van";
    if (!t.coKhach) return "cho";
    if (!t.tuBatTay) return "cho";
    if (!t.laChu) return t.minhSS ? "cho" : "san_sang";
    return t.khachSS ? "bat_dau" : "cho";
  }

  const api = {
    chuanHoaVaiTro: chuanHoaVaiTro,
    laVaiPhu: laVaiPhu,
    laVaiChinh: laVaiChinh,
    daSanSang: daSanSang,
    laChuBan: laChuBan,
    hanhDongGiuBan: hanhDongGiuBan,
  };

  root.AutoToolVaiTro = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
