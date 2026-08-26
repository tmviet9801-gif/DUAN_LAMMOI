window.Licenses = (function () {
  const UI = window.UI;
  let rows = [];

  function render() {
    const q = (UI.$("#licSearch").value || "").toLowerCase().trim();
    const st = UI.$("#licStatusFilter").value;
    let list = rows;
    if (st !== "all") list = list.filter((l) => l.status === st);
    if (q) {
      list = list.filter((l) =>
        (l.key || "").toLowerCase().includes(q) ||
        (l.machine_id || "").toLowerCase().includes(q) ||
        (l.customer_name || "").toLowerCase().includes(q) ||
        (l.contact || "").toLowerCase().includes(q));
    }
    const tb = UI.$("#licTbody");
    if (!list.length) { tb.innerHTML = ""; UI.$("#licEmpty").style.display = "block"; return; }
    UI.$("#licEmpty").style.display = "none";
    tb.innerHTML = list.map((l) => `
      <tr>
        <td><b>${UI.esc(l.customer_name || "—")}</b><div class="muted small">${UI.esc(l.contact || "")}</div></td>
        <td class="mono">${UI.esc((l.key || "").slice(0, 30))}...</td>
        <td>${UI.esc(l.plan_name || "Tuy chinh")}</td>
        <td>${l.max_tabs}</td>
        <td>${UI.fmtDate(l.expires_at)}</td>
        <td>${UI.badge(l.status)}</td>
        <td class="row-actions">
          <button class="btn xs" data-act="view" data-id="${l.id}">Chi tiet</button>
          ${l.status !== "active" ? `<button class="btn xs" data-act="activate" data-id="${l.id}">Kich hoat</button>` : ""}
          <button class="btn xs" data-act="extend" data-id="${l.id}">Gia han</button>
          <button class="btn xs" data-act="reset" data-id="${l.id}">Reset</button>
          <button class="btn xs danger" data-act="revoke" data-id="${l.id}">Thu hoi</button>
          <button class="btn xs" data-act="del" data-id="${l.id}">Xoa</button>
        </td>
      </tr>`).join("");
  }

  async function load() {
    rows = await AdminAPI.get("/api/licenses");
    render();
  }

  function view(l) {
    const m = UI.modal("Chi tiet license");
    m.setActions(`<button class="btn ghost" id="mClose">Dong</button>`);
    UI.$("#mClose").onclick = UI.closeModal;
    const body = UI.$("#modalRoot .modal-body");
    body.innerHTML = `
      <div class="detail">
        <div class="field"><label>License key</label><div class="keybox" id="dKey">${UI.esc(l.key)}</div><button class="btn xs" id="dCopy">Copy</button></div>
        <div class="kv"><span>Khach</span><b>${UI.esc(l.customer_name || "—")}</b></div>
        <div class="kv"><span>Lien he</span><b>${UI.esc(l.contact || "—")}</b></div>
        <div class="kv"><span>Ma may</span><b class="mono">${UI.esc(l.machine_id)}</b></div>
        <div class="kv"><span>Goi</span><b>${UI.esc(l.plan_name || "Tuy chinh")}</b></div>
        <div class="kv"><span>So tab</span><b>${l.max_tabs}</b></div>
        <div class="kv"><span>Features</span><b>${UI.esc(l.features)}</b></div>
        <div class="kv"><span>Cap luc</span><b>${UI.fmtDate(l.created_at)}</b></div>
        <div class="kv"><span>Het han</span><b>${UI.fmtDate(l.expires_at)}</b></div>
        <div class="kv"><span>Trang thai</span><b>${UI.badge(l.status)}</b></div>
        <div class="kv"><span>Ghi chu</span><b>${UI.esc(l.note || "—")}</b></div>
        <h4 class="mt">Lich su</h4>
        <div id="dEvents" class="events">Dang tai...</div>
      </div>`;
    UI.$("#dCopy").onclick = () =>
      navigator.clipboard.writeText(l.key).then(() => UI.toast("Da copy", "success"));
    AdminAPI.get(`/api/licenses/${l.id}/events`).then((evs) => {
      UI.$("#dEvents").innerHTML = evs.length
        ? evs.map((e) =>
            `<div class="ev"><span class="badge">${UI.esc(e.action)}</span><span class="muted">${UI.fmtDate(e.created_at)}</span><span>${UI.esc(e.detail || "")}</span></div>`).join("")
        : `<div class="muted">Chua co</div>`;
    }).catch(() => {});
  }

  function extend(l) {
    const m = UI.modal("Gia han license",
      `<p>Khach: <b>${UI.esc(l.customer_name || "—")}</b> - het han <b>${UI.fmtDate(l.expires_at)}</b></p>
       <div class="field"><label>So ngay gia han</label><input id="exDays" type="number" min="1" max="3650" value="30" /></div>`);
    m.setActions(`<button class="btn ghost" id="mCancel">Huy</button><button class="btn primary" id="mOk">Gia han</button>`);
    UI.$("#mCancel").onclick = UI.closeModal;
    UI.$("#mOk").onclick = async () => {
      const days = parseInt(UI.$("#exDays").value, 10);
      if (!days || days < 1) return UI.toast("Nhap so ngay hop le", "error");
      try {
        await AdminAPI.post(`/api/licenses/${l.id}/extend`, { days });
        UI.toast("Da gia han", "success");
        UI.closeModal();
        await load();
      } catch (e) { UI.toast(e.message, "error"); }
    };
  }

  function reset(l) {
    const m = UI.modal("Reset license",
      `<p>Cap lai key moi cho may <b class="mono">${UI.esc(l.machine_id)}</b></p>
       <div class="field"><label>So ngay (trong = giu thoi han con lai)</label><input id="rsDays" type="number" min="1" max="3650" placeholder="0" /></div>
       <div class="field"><label>So tab (trong = giu nguyen)</label><input id="rsTabs" type="number" min="1" max="50" placeholder="0" /></div>
       <div class="field"><label>Ma may moi (doi may, trong = giu nguyen)</label><input id="rsMachine" placeholder="MachineGuid moi" /></div>`);
    m.setActions(`<button class="btn ghost" id="mCancel">Huy</button><button class="btn primary" id="mOk">Reset</button>`);
    UI.$("#mCancel").onclick = UI.closeModal;
    UI.$("#mOk").onclick = async () => {
      const body = {};
      const days = parseInt(UI.$("#rsDays").value, 10);
      const tabs = parseInt(UI.$("#rsTabs").value, 10);
      const machine = UI.$("#rsMachine").value.trim();
      if (days) body.days = days;
      if (tabs) body.max_tabs = tabs;
      if (machine) body.machine_id = machine;
      try {
        await AdminAPI.post(`/api/licenses/${l.id}/reset`, body);
        UI.toast("Da reset", "success");
        UI.closeModal();
        await load();
      } catch (e) { UI.toast(e.message, "error"); }
    };
  }

  function setStatus(l, status) {
    const labels = { revoked: "Thu hoi", suspended: "Treo", active: "Kich hoat" };
    const msg = status === "revoked"
      ? "Thu hoi se khiến key het han ngay (offline HMAC). Xac nhan?"
      : `Xac nhan ${labels[status].toLowerCase()} license nay?`;
    UI.confirmDialog(labels[status] + " license", msg, async () => {
      try {
        await AdminAPI.post(`/api/licenses/${l.id}/status`, { status });
        UI.toast("Da " + labels[status].toLowerCase(), "success");
        await load();
      } catch (e) { UI.toast(e.message, "error"); }
    }, labels[status]);
  }

  function remove(l) {
    UI.confirmDialog("Xoa license", "Xoa vinh vien license nay cung lich su?", async () => {
      try {
        await AdminAPI.del(`/api/licenses/${l.id}`);
        UI.toast("Da xoa", "success");
        await load();
      } catch (e) { UI.toast(e.message, "error"); }
    }, "Xoa");
  }

  async function onSubmit(e) {
    e.preventDefault();
    const machine = UI.$("#issMachine").value.trim();
    if (!machine) return UI.toast("Nhap ma may khach", "error");
    const body = {
      machine_id: machine,
      customer_name: UI.$("#issName").value.trim(),
      plan_id: UI.$("#issPlan").value || null,
      days: parseInt(UI.$("#issDays").value, 10) || 30,
      max_tabs: parseInt(UI.$("#issTabs").value, 10) || 10,
      note: UI.$("#issNote").value.trim(),
    };
    try {
      const r = await AdminAPI.post("/api/licenses", body);
      UI.$("#issueKey").textContent = r.key;
      UI.$("#issueResult").style.display = "block";
      UI.$("#issueCopy").onclick = () =>
        navigator.clipboard.writeText(r.key).then(() => UI.toast("Da copy key", "success"));
      UI.toast("Da cap license", "success");
      await load();
    } catch (err) { UI.toast(err.message, "error"); }
  }

  async function loadPlans() {
    const plans = await AdminAPI.get("/api/plans");
    const sel = UI.$("#issPlan");
    sel.innerHTML = `<option value="">--- Goi tuy chinh ---</option>` + plans
      .filter((p) => p.active)
      .map((p) =>
        `<option value="${p.id}" data-days="${p.duration_days}" data-tabs="${p.max_tabs}">${UI.esc(p.name)} - ${p.max_tabs} tab - ${UI.fmtMoney(p.price)}</option>`)
      .join("");
    return plans;
  }

  function wire() {
    UI.$("#licSearch").addEventListener("input", render);
    UI.$("#licStatusFilter").addEventListener("change", render);
    UI.$("#licTbody").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-act]");
      if (!btn) return;
      const l = rows.find((r) => r.id === btn.dataset.id);
      if (!l) return;
      const acts = {
        view: () => view(l),
        extend: () => extend(l),
        reset: () => reset(l),
        revoke: () => setStatus(l, "revoked"),
        activate: () => setStatus(l, "active"),
        del: () => remove(l),
      };
      (acts[btn.dataset.act] || (() => {}))();
    });
    UI.$("#issPlan").addEventListener("change", (e) => {
      const o = e.target.selectedOptions[0];
      if (o && o.dataset.days) {
        UI.$("#issDays").value = o.dataset.days;
        UI.$("#issTabs").value = o.dataset.tabs;
      }
    });
    UI.$("#issueForm").addEventListener("submit", onSubmit);
  }

  return { load, wire, loadPlans };
})();