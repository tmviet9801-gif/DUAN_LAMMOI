window.UI = (function () {
  const $ = (s, p) => (p || document).querySelector(s);
  const $$ = (s, p) => Array.from((p || document).querySelectorAll(s));

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function toast(msg, type) {
    const el = document.createElement("div");
    el.className = "toast " + (type || "info");
    el.textContent = msg;
    $("#toastWrap").appendChild(el);
    setTimeout(() => el.classList.add("show"), 10);
    setTimeout(() => { el.classList.remove("show"); setTimeout(() => el.remove(), 300); }, 3200);
  }

  function fmtDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d)) return "—";
    return d.toLocaleString("vi-VN", {
      day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
    });
  }

  function fmtMoney(n) {
    return Number(n || 0).toLocaleString("vi-VN") + " d";
  }

  function badge(status) {
    const map = { active: "ok", revoked: "bad", suspended: "warn", expired: "muted" };
    return `<span class="badge ${map[status] || ""}">${esc(status || "")}</span>`;
  }

  function modal(title, contentHtml) {
    $("#modalRoot").innerHTML = `
      <div class="modal-overlay" id="modalOverlay">
        <div class="modal">
          <div class="modal-head"><h3>${esc(title)}</h3><button class="modal-close" id="modalClose">&times;</button></div>
          <div class="modal-body">${contentHtml}</div>
          <div class="modal-actions" id="modalActions"></div>
        </div>
      </div>`;
    const ov = $("#modalOverlay");
    ov.addEventListener("click", (e) => { if (e.target === ov) closeModal(); });
    $("#modalClose").onclick = closeModal;
    return {
      setActions: (html) => { $("#modalActions").innerHTML = html; },
    };
  }

  function closeModal() { $("#modalRoot").innerHTML = ""; }

  function confirmDialog(title, msg, onOk, okLabel) {
    const m = modal(title, `<p>${esc(msg)}</p>`);
    m.setActions(`<button class="btn ghost" id="mCancel">Huy</button>
      <button class="btn danger" id="mOk">${esc(okLabel || "Xac nhan")}</button>`);
    $("#mCancel").onclick = closeModal;
    $("#mOk").onclick = () => { closeModal(); onOk(); };
  }

  return { $, $$, esc, toast, fmtDate, fmtMoney, badge, modal, closeModal, confirmDialog };
})();