window.Plans = (function () {
  const UI = window.UI;
  let rows = [];

  function render() {
    UI.$("#planTbody").innerHTML = rows.map((p) => `
      <tr>
        <td><b>${UI.esc(p.name)}</b></td>
        <td>${p.max_tabs}</td>
        <td>${UI.fmtMoney(p.price)}</td>
        <td>${p.duration_days}</td>
        <td class="mono">${UI.esc(p.features)}</td>
        <td>${p.active ? UI.badge("active") : UI.badge("suspended")}</td>
        <td class="row-actions">
          <button class="btn xs" data-act="edit" data-id="${p.id}">Sua</button>
          <button class="btn xs danger" data-act="del" data-id="${p.id}">Xoa</button>
        </td>
      </tr>`).join("");
  }

  async function load() {
    rows = await AdminAPI.get("/api/plans");
    render();
    return rows;
  }

  function open(plan) {
    const isEdit = !!plan;
    const m = UI.modal(isEdit ? "Sua goi" : "Them goi", `
      <div class="field"><label>Ten goi</label><input id="pName" value="${isEdit ? UI.esc(plan.name) : ""}" /></div>
      <div class="field"><label>Tab toi da</label><input id="pTabs" type="number" min="1" max="50" value="${isEdit ? plan.max_tabs : 10}" /></div>
      <div class="field"><label>Gia / thang (VND)</label><input id="pPrice" type="number" min="0" value="${isEdit ? plan.price : 0}" /></div>
      <div class="field"><label>Ngay mac dinh</label><input id="pDays" type="number" min="1" max="3650" value="${isEdit ? plan.duration_days : 30}" /></div>
      <div class="field"><label>Features</label><input id="pFeatures" value="${isEdit ? UI.esc(plan.features) : "game"}" /></div>
      <label class="check"><input type="checkbox" id="pActive" ${(!isEdit || plan.active) ? "checked" : ""} /> Kich hoat</label>`);
    m.setActions(`<button class="btn ghost" id="mCancel">Huy</button><button class="btn primary" id="mOk">Luu</button>`);
    UI.$("#mCancel").onclick = UI.closeModal;
    UI.$("#mOk").onclick = async () => {
      const body = {
        name: UI.$("#pName").value.trim(),
        max_tabs: parseInt(UI.$("#pTabs").value, 10) || 10,
        price: parseFloat(UI.$("#pPrice").value) || 0,
        duration_days: parseInt(UI.$("#pDays").value, 10) || 30,
        features: UI.$("#pFeatures").value.trim() || "game",
        active: UI.$("#pActive").checked,
      };
      if (!body.name) return UI.toast("Nhap ten goi", "error");
      try {
        if (isEdit) await AdminAPI.patch(`/api/plans/${plan.id}`, body);
        else await AdminAPI.post("/api/plans", body);
        UI.toast("Da luu", "success");
        UI.closeModal();
        await load();
      } catch (e) { UI.toast(e.message, "error"); }
    };
  }

  function remove(p) {
    UI.confirmDialog("Xoa goi", `Xoa goi "${p.name}"? License cu giu nguyen (khong lien ket goi).`, async () => {
      try {
        await AdminAPI.del(`/api/plans/${p.id}`);
        UI.toast("Da xoa", "success");
        await load();
      } catch (e) { UI.toast(e.message, "error"); }
    }, "Xoa");
  }

  function wire() {
    UI.$("#addPlanBtn").onclick = () => open(null);
    UI.$("#planTbody").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-act]");
      if (!btn) return;
      const p = rows.find((r) => r.id === btn.dataset.id);
      if (!p) return;
      if (btn.dataset.act === "edit") open(p);
      if (btn.dataset.act === "del") remove(p);
    });
  }

  return { load, wire };
})();