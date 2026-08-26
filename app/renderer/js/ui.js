(function () {
  // UI helpers - DOM, toast, confirm, logger
  const App = (window.App = window.App || {});

  App.$ = (id) => document.getElementById(id);

  App.esc = (s) =>
    String(s ?? "").replace(
      /[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

  App.log = {
    debug: (...a) => console.debug("[App]", ...a),
    info: (...a) => console.info("[App]", ...a),
    warn: (...a) => console.warn("[App]", ...a),
    error: (...a) => console.error("[App]", ...a),
  };

  App.toast = function toast(msg, type = "info") {
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.textContent = msg;
    App.$("toastContainer").appendChild(el);
    setTimeout(() => el.remove(), 4000);
  };

  App.confirmDialog = function confirmDialog(title, message, onOk, okLabel = "Xác nhận") {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal">
        <h3>${App.esc(title)}</h3>
        <p>${App.esc(message)}</p>
        <div class="actions">
          <button class="modal-cancel">Hủy</button>
          <button class="primary modal-ok">${App.esc(okLabel)}</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    overlay.querySelector(".modal-cancel").onclick = close;
    overlay.querySelector(".modal-ok").onclick = () => {
      close();
      onOk();
    };
    overlay.onclick = (e) => {
      if (e.target === overlay) close();
    };
  };

  App.setBackend = function setBackend(ok) {
    App.$("backendDot").className = "dot " + (ok ? "ok" : "err");
    App.$("backendText").textContent = ok ? "Backend sẵn sàng" : "Mất kết nối";
  };
})();
