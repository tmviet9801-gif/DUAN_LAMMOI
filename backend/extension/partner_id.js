/* partner_id.js — xác định AI LÀ ĐỒNG ĐỘI, tách riêng để kiểm thử được bằng node.
 *
 * Vì sao tách: hàm này quyết định `findBestPlay(..., isPartnerActor)` — tức có
 * cố tình đánh nhẹ / bỏ lượt để người kia ăn hay không. Nhận nhầm một người
 * chơi lạ thành đồng đội = nạp bài cho họ. Đây là hàm đắt nhất trong dự án khi
 * sai, nên nó phải kiểm thử được ngoài trình duyệt.
 *
 * NGUYÊN TẮC: chỉ khớp CHÍNH XÁC trên danh tính ĐÃ XÁC MINH (dn / u / uid).
 *
 * Bản trước đoán theo HÌNH DẠNG TÊN: cắt số đuôi, gộp ký tự lặp, rồi so chuỗi
 * con hai chiều. Với tên in-game `nicktestxxabai1` (gốc `nicktestxabai`), mọi
 * người chơi tên `ai2`, `i3`, `nick9`, `bai3`, `test5`… đều thành "đồng đội",
 * vì gốc của họ là chuỗi con của gốc tôi và số đuôi khác. Đo thực tế: 10/15
 * tên thử bị nhận nhầm.
 *
 * Tên profile ("Account 01") KHÔNG phải danh tính trong game và không bao giờ
 * được đem so mờ với tên in-game — đó chính là cầu nối sai đã sinh ra lỗi trên.
 * Nay khoá đối chiếu là `character_name` lấy từ database (Check Live đọc về).
 *
 * Hỏng theo hướng AN TOÀN: thiếu danh tính đã xác minh thì trả false. Hậu quả
 * là mất phối hợp (đánh như người thường), không phải nạp bài cho khách lạ.
 */
(function (root) {
  "use strict";

  function chuanHoa(s) {
    return String(s === undefined || s === null ? "" : s).trim().toLowerCase();
  }

  function chiSo(s) {
    return String(s === undefined || s === null ? "" : s).replace(/\D/g, "");
  }

  /** Gom mọi định danh của một mục đồng đội về ba tập khớp-chính-xác. */
  function tachDinhDanh(pt) {
    const dn = new Set();
    const u = new Set();
    const uid = new Set();
    if (!pt) return { dn: dn, u: u, uid: uid };

    if (typeof pt === "string") {
      // Chuỗi trần: có thể là dn hoặc u — chấp nhận cả hai, nhưng CHÍNH XÁC.
      const s = chuanHoa(pt);
      if (s) { dn.add(s); u.add(s); }
      // Chuỗi KHÔNG có chữ cái coi là uid. Extension đẩy `anchor_uid` vào
      // danh sách dưới dạng chuỗi trần, mà uid của game có dạng
      // `1_643156061` — có gạch dưới, nên phép thử "toàn chữ số" trượt và
      // mất luôn đường khớp uid.
      const n = chiSo(pt);
      if (n && !/[a-z]/.test(s)) uid.add(n);
      return { dn: dn, u: u, uid: uid };
    }

    if (typeof pt === "object") {
      const d = chuanHoa(pt.dn);
      const uu = chuanHoa(pt.u);
      const ui = chiSo(pt.uid);
      if (d) dn.add(d);
      if (uu) u.add(uu);
      if (ui) uid.add(ui);
      // character_name là tên in-game đã xác minh trong database -> tương đương dn
      const cn = chuanHoa(pt.character_name);
      if (cn) dn.add(cn);
      // profile_name là tên hiển thị trong app, KHÔNG phải danh tính trong game.
      // Chỉ chấp nhận khi trùng KHÍT — không so chuỗi con, không gộp ký tự.
      const pn = chuanHoa(pt.profile_name);
      if (pn) { dn.add(pn); u.add(pn); }
    }
    return { dn: dn, u: u, uid: uid };
  }

  function gopDinhDanh(danh_sach) {
    const dn = new Set();
    const u = new Set();
    const uid = new Set();
    for (const pt of danh_sach || []) {
      const t = tachDinhDanh(pt);
      t.dn.forEach((x) => dn.add(x));
      t.u.forEach((x) => u.add(x));
      t.uid.forEach((x) => uid.add(x));
    }
    return { dn: dn, u: u, uid: uid };
  }

  /** Người chơi `x` có nằm trong tập định danh `tap` không (khớp chính xác)? */
  function khop(x, tap) {
    if (!x || !tap) return false;
    const uid = chiSo(x.uid);
    if (uid && tap.uid.has(uid)) return true;
    const dn = chuanHoa(x.dn);
    if (dn && (tap.dn.has(dn) || tap.u.has(dn))) return true;
    const u = chuanHoa(x.u);
    if (u && (tap.u.has(u) || tap.dn.has(u))) return true;
    return false;
  }

  /**
   * `x` có phải đồng đội không.
   *
   * ctx = {
   *   partners: [...],                       // danh sách controller đồng bộ xuống
   *   expected: {dn, u, uid} | null,         // anchor đang chờ ghép bàn
   *   invite:   {anchor_uid, anchor_dn, anchor_u, ts} | null,
   *   now:      <ms>,                        // để kiểm thử được, mặc định Date.now()
   *   inviteTTL:<ms>,                        // hạn dùng của lời mời
   * }
   */
  function laDongDoi(x, ctx) {
    if (!x) return false;
    ctx = ctx || {};

    // Anchor đang chờ: danh tính do controller cấp, đã xác minh.
    const exp = ctx.expected;
    if (exp && khop(x, gopDinhDanh([exp]))) return true;

    // Lời mời còn hạn.
    const inv = ctx.invite;
    if (inv) {
      const now = typeof ctx.now === "number" ? ctx.now : Date.now();
      const ttl = typeof ctx.inviteTTL === "number" ? ctx.inviteTTL : 20000;
      if (typeof inv.ts !== "number" || (now - inv.ts) < ttl) {
        const tap = gopDinhDanh([{
          uid: inv.anchor_uid, dn: inv.anchor_dn, u: inv.anchor_u,
        }]);
        if (khop(x, tap)) return true;
      }
    }

    // Danh sách đồng đội.
    if (khop(x, gopDinhDanh(ctx.partners))) return true;

    return false;
  }

  const api = {
    chuanHoa: chuanHoa,
    chiSo: chiSo,
    tachDinhDanh: tachDinhDanh,
    gopDinhDanh: gopDinhDanh,
    khop: khop,
    laDongDoi: laDongDoi,
  };

  root.AutoToolPartner = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
