(function () {
  // Cấu hình nhóm cho Game Test (main + support)
  const App = (window.App = window.App || {});
  const $ = App.$;
  let accounts = [];
  let addCounter = 0;

  async function load() {
    try {
      const acc = await App.api("/api/accounts");
      accounts = acc.map((a) => a.name).filter(Boolean);
      render(["A"]);
    } catch (e) {
      App.log.warn("load groups failed:", e.message);
    }
  }

  function render(groupNames) {
    const el = $("groupEditor");
    el.innerHTML = "";
    if (!accounts.length) {
      el.innerHTML = '<div class="hint">Chưa có profile nào. Vào Trang chủ để thêm profile trước.</div>';
      return;
    }
    if (!groupNames.length) groupNames = ["A"];
    groupNames.forEach((g) => addRow(el, g));
    $("groupsSaveMsg").textContent = "";
  }

  function addRow(el, gname) {
    const row = document.createElement("div");
    row.className = "group-row";
    const mainOptions = accounts
      .map((a) => `<option value="${App.esc(a)}">${App.esc(a)}</option>`)
      .join("");
    const chips = accounts
      .map((a) => `<button type="button" class="chip" data-acc="${App.esc(a)}">${App.esc(a)}</button>`)
      .join("");
    row.innerHTML = `
      <div class="group-row-head">
        <input class="gname" value="${App.esc(gname)}" placeholder="Tên nhóm (vd: A)" />
        <button type="button" class="ghost gdel" title="Xóa nhóm">✕</button>
      </div>
      <div class="group-row-body">
        <div class="field">
          <label>Tài khoản chính (main)</label>
          <select class="gmain">${mainOptions}</select>
        </div>
        <div class="field">
          <label>Tài khoản phụ (support) — bấm để chọn/bỏ chọn</label>
          <div class="chips">${chips}</div>
        </div>
      </div>
    `;
    // default main = profile đầu
    row.querySelector(".gmain").value = accounts[0] || "";
    row.querySelector(".gdel").onclick = () => row.remove();
    row.querySelector(".gmain").onchange = () => {
      // không cho support trùng main
      const m = row.querySelector(".gmain").value;
      row.querySelectorAll(".chip").forEach((c) => {
        if (c.dataset.acc === m) c.classList.remove("on");
      });
    };
    row.querySelectorAll(".chip").forEach((c) => {
      c.onclick = () => {
        const mainVal = row.querySelector(".gmain").value;
        if (c.dataset.acc === mainVal) return; // main không được làm support
        c.classList.toggle("on");
      };
    });
    el.appendChild(row);
  }

  async function save() {
    const rows = document.querySelectorAll("#groupEditor .group-row");
    const groups = {};
    rows.forEach((row) => {
      const name = row.querySelector(".gname").value.trim();
      if (!name) return;
      const main = row.querySelector(".gmain").value;
      const supports = Array.from(row.querySelectorAll(".chip.on")).map((c) => c.dataset.acc);
      groups[name] = { main, supports };
    });
    if (!Object.keys(groups).length) {
      App.toast("Chưa có nhóm nào để lưu", "warn");
      return;
    }
    try {
      await App.api("/api/gamesim/config", {
        method: "POST",
        body: JSON.stringify({ groups }),
      });
      $("groupsSaveMsg").textContent = "✓ Đã lưu cấu hình nhóm — Game Test sẽ dùng các nhóm này.";
      $("groupsSaveMsg").className = "hint success";
      App.toast("Đã lưu cấu hình nhóm", "success");
    } catch (e) {
      App.toast("Lưu thất bại: " + e.message, "error");
    }
  }

  $("btnSaveGroups").onclick = save;
  $("btnAddGroup").onclick = () => {
    addCounter += 1;
    addRow($("groupEditor"), `Group${addCounter}`);
  };

  App.groupsLoad = load;
  load();
})();