(function () {
  // Quản lý proxy: lưu, kiểm tra 1/all, áp dụng cho profile
  const App = (window.App = window.App || {});
  const $ = App.$;

  function _clean() {
    return $("proxyText").value.split("\n").map((s) => s.trim()).filter(Boolean);
  }

  async function load() {
    try {
      const r = await App.api("/api/proxies");
      $("proxyText").value = r.proxies.join("\n");
    } catch (e) {
      App.log.warn("load proxies fail:", e.message);
    }
  }

  async function save() {
    const proxies = _clean();
    try {
      const r = await App.api("/api/proxies", { method: "POST", body: JSON.stringify({ proxies }) });
      App.toast(`Đã lưu ${r.count} proxy`, "success");
    } catch (e) {
      App.toast("Lưu proxy thất bại: " + e.message, "error");
    }
  }

  async function checkAll() {
    const proxies = _clean();
    if (!proxies.length) {
      App.toast("Chưa có proxy", "warn");
      return;
    }
    const resEl = $("proxyResults");
    resEl.innerHTML = '<div class="hint">Đang kiểm tra…</div>';
    $("proxyStatus").textContent = "Đang kiểm tra…";
    // Kiểm tra tất cả song song
    const results = await Promise.all(
      proxies.map(async (proxy) => {
        try {
          const r = await App.api("/api/check-proxy", { method: "POST", body: JSON.stringify({ proxy }) });
          return { proxy, ok: r.ok, ip: r.ip || "", latency: r.latency_ms || 0, error: r.error || "" };
        } catch (e) {
          return { proxy, ok: false, error: e.message };
        }
      })
    );
    const alive = results.filter((r) => r.ok);
    const dead = results.filter((r) => !r.ok);
    $("proxyStatus").textContent = `Kiểm tra xong: ${alive.length} sống, ${dead.length} chết`;
    renderResults(results);
    App._aliveProxies = alive.map((r) => r.proxy);
  }

  function renderResults(results) {
    const el = $("proxyResults");
    el.innerHTML = "";
    for (const r of results) {
      const row = document.createElement("div");
      row.className = "gs-event";
      const status = r.ok ? "✓" : "✗";
      const cls = r.ok ? "success" : "error";
      const detail = r.ok
        ? `${r.ip} (${r.latency}ms)`
        : `${r.error}`;
      row.innerHTML = `<span class="badge ${cls}">${status}</span> <span class="meta">${App.esc(r.proxy.slice(0, 60))}</span> <span class="meta" style="color:var(--${cls})">${App.esc(detail)}</span>`;
      // Nút check riêng
      const checkBtn = document.createElement("button");
      checkBtn.textContent = "Kiểm tra";
      checkBtn.className = "ghost";
      checkBtn.onclick = async () => {
        checkBtn.disabled = true;
        try {
          const res = await App.api("/api/check-proxy", { method: "POST", body: JSON.stringify({ proxy: r.proxy }) });
          if (res.ok) {
            row.innerHTML = `<span class="badge success">✓</span> <span class="meta">${App.esc(r.proxy.slice(0, 60))}</span> <span class="meta" style="color:var(--ok)">${res.ip} (${res.latency_ms}ms)</span>`;
          } else {
            row.innerHTML = `<span class="badge error">✗</span> <span class="meta">${App.esc(r.proxy.slice(0, 60))}</span> <span class="meta" style="color:var(--danger)">${App.esc(res.error)}</span>`;
          }
        } catch (e) {
          row.innerHTML = `<span class="badge error">✗</span> <span class="meta">${App.esc(r.proxy.slice(0, 60))}</span> <span class="meta" style="color:var(--danger)">${App.esc(e.message)}</span>`;
        }
      };
      row.appendChild(checkBtn);
      el.appendChild(row);
    }
  }

  async function applyAlive() {
    const alive = App._aliveProxies;
    if (!alive || !alive.length) {
      App.toast("Chạy 'Kiểm tra tất cả' trước để có proxy sống", "warn");
      return;
    }
    try {
      const r = await App.api("/api/proxies/apply", { method: "POST", body: JSON.stringify({ proxies: alive }) });
      App.toast(`Đã áp ${r.applied} proxy cho ${r.free_profiles} profile trống`, "success");
      $("proxyStatus").textContent = `Đã áp ${r.applied} proxy sống cho profile chưa có proxy.`;
    } catch (e) {
      App.toast("Áp proxy thất bại: " + e.message, "error");
    }
  }

  $("proxySave").onclick = save;
  $("proxyCheckAll").onclick = checkAll;
  $("proxyApply").onclick = applyAlive;
  App.proxyLoad = load;
  load();
})();