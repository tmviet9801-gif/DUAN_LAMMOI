(function () {
  // Render - vẽ giao diện từ state
  const App = (window.App = window.App || {});
  const $ = App.$;
  const state = App.state;

  // ---- Trạng thái bảng profile (search / sort / pagination) ----
  const tableState = {
    page: 1,
    pageSize: 10,
    search: "",
    sort: "name_asc",
  };
  App.tableState = tableState;

  // ---- Profile đang chọn để mở ----
  App.selectedProfileIds = new Set();

  function fillSelect(sel, options, value, labelFn) {
    sel.innerHTML = "";
    for (const opt of options) {
      const o = document.createElement("option");
      o.value = opt;
      o.textContent = labelFn ? labelFn(opt) : opt;
      if (opt === value) o.selected = true;
      sel.appendChild(o);
    }
  }

  function renderInfo() {
    if (!state.info) return;
    $("infoProfilesDir").textContent = state.info.profiles_dir;
    $("infoDataDir").textContent = state.info.data_dir;
    if (state.version) {
      $("brandVersion").textContent = `v${state.version.version}`;
      $("infoVersion").textContent = `${state.version.app} v${state.version.version}`;
    }
  }

  function renderConfig() {
    const g = state.config.grid;
    const w = state.config.window;
    const ad = state.config.anti_detect;
    $("cfgCols").value = g.cols;
    $("cfgGap").value = g.gap;
    $("cfgMargin").value = g.margin;
    $("cfgDirection").value = state.config.open_direction || "row";
    $("cfgWinW").value = w.width || 0;
    $("cfgWinH").value = w.height || 0;
    $("cfgCount").value = state.config.default_count;
    $("cfgAutoLayout").checked = !!state.config.auto_layout;
    if (state.antiDetect) {
      const osLabels = { random: "Ngẫu nhiên", windows: "Windows", macos: "macOS", linux: "Linux" };
      fillSelect($("cfgOs"), state.antiDetect.os, ad.os, (o) => osLabels[o] || o);
      fillSelect($("cfgLocale"), state.antiDetect.locale, ad.locale, (l) =>
        l === "random" ? "Ngẫu nhiên" : l
      );
    }
  }

  // ---- Bảng profile ----
  function _byDate(a) {
    const t = a && a.created_at ? new Date(a.created_at).getTime() : 0;
    return Number.isFinite(t) ? t : 0;
  }

  function getFilteredProfiles() {
    let list = state.accounts.slice();
    const q = tableState.search.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (a) =>
          (a.name || "").toLowerCase().includes(q) ||
          (a.user_agent || a.profile_ua || "").toLowerCase().includes(q) ||
          (a.url || "").toLowerCase().includes(q)
      );
    }
    switch (tableState.sort) {
      case "name_desc":
        list.sort((a, b) => (b.name || "").localeCompare(a.name || ""));
        break;
      case "date_new":
        list.sort((a, b) => _byDate(b) - _byDate(a));
        break;
      case "date_old":
        list.sort((a, b) => _byDate(a) - _byDate(b));
        break;
      default:
        list.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    }
    return list;
  }
  App.getFilteredProfiles = getFilteredProfiles;

  function renderProfilesTable() {
    const all = getFilteredProfiles();
    const total = all.length;
    const pageSize = tableState.pageSize;
    const pages = Math.max(1, Math.ceil(total / pageSize));
    if (tableState.page > pages) tableState.page = pages;
    const start = (tableState.page - 1) * pageSize;
    const rows = all.slice(start, start + pageSize);

    $("profileCount").textContent = total;
    const tbody = $("profileTbody");
    tbody.innerHTML = "";

    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="hint">Không có profile nào.</td></tr>';
    }

    rows.forEach((a, i) => {
      const tr = document.createElement("tr");
      const selected = App.selectedProfileIds.has(a.id);
      if (selected) tr.classList.add("row-selected");
      const ua = a.user_agent || a.profile_ua || "ngẫu nhiên khi mở";
      const proxy = a.proxy ? String(a.proxy) : "";
      tr.innerHTML = `
        <td class="col-stt">${start + i + 1}</td>
        <td class="col-name" title="${App.esc(a.name)}">${App.esc(a.name)}</td>
        <td class="col-ua" title="${App.esc(ua)}">${App.esc(ua)}</td>
        <td class="col-proxy" title="${App.esc(proxy || "IP máy")}">${proxy ? App.esc(proxy) : '<span class="ip-local">IP máy</span>'}</td>
        <td class="col-actions">
          <button class="btn-open-profile primary" title="Mở profile này">Mở</button>
          <button class="btn-edit-profile" title="Sửa profile">Sửa</button>
        </td>
        <td class="col-del">
          <button class="btn-del-profile" title="Xóa profile + dữ liệu đã lưu">Xóa</button>
        </td>
      `;
      tr.querySelector(".btn-open-profile").onclick = (e) => {
        e.stopPropagation();
        App.openAccountRow(a);
      };
      tr.querySelector(".btn-edit-profile").onclick = (e) => {
        e.stopPropagation();
        App.openEditProfile(a);
      };
      tr.querySelector(".btn-del-profile").onclick = (e) => {
        e.stopPropagation();
        App.deleteAccountRow(a);
      };
      tr.onclick = () => toggleRowSelection(a.id);
      tbody.appendChild(tr);
    });

    $("pageInfo").textContent = `${total ? start + 1 : 0}-${Math.min(start + pageSize, total)} / ${total}`;
    $("pagePrev").disabled = tableState.page <= 1;
    $("pageNext").disabled = tableState.page >= pages;
    updateSelectionCounter();
  }
  App.renderProfilesTable = renderProfilesTable;

  function toggleRowSelection(id) {
    if (App.selectedProfileIds.has(id)) App.selectedProfileIds.delete(id);
    else App.selectedProfileIds.add(id);
    renderProfilesTable();
  }
  App.toggleRowSelection = toggleRowSelection;

  function selectAllProfiles() {
    getFilteredProfiles().forEach((a) => App.selectedProfileIds.add(a.id));
    renderProfilesTable();
  }
  App.selectAllProfiles = selectAllProfiles;

  function clearSelection() {
    App.selectedProfileIds.clear();
    renderProfilesTable();
  }
  App.clearSelection = clearSelection;

  function updateSelectionCounter() {
    const total = state.accounts.length;
    $("pickerBtn").textContent = `Đã chọn ${App.selectedProfileIds.size}/${total}`;
  }
  App.updateSelectionCounter = updateSelectionCounter;

  function initProfilesTableControls() {
    $("profSearch").addEventListener("input", () => {
      tableState.search = $("profSearch").value;
      tableState.page = 1;
      renderProfilesTable();
    });
    $("profSort").addEventListener("change", () => {
      tableState.sort = $("profSort").value;
      tableState.page = 1;
      renderProfilesTable();
    });
    $("pagePrev").onclick = () => {
      if (tableState.page > 1) {
        tableState.page--;
        renderProfilesTable();
      }
    };
    $("pageNext").onclick = () => {
      const pages = Math.max(1, Math.ceil(getFilteredProfiles().length / tableState.pageSize));
      if (tableState.page < pages) {
        tableState.page++;
        renderProfilesTable();
      }
    };
    $("profSearch").addEventListener("keydown", (e) => {
      if (e.ctrlKey && e.key.toLowerCase() === "a") {
        e.preventDefault();
        selectAllProfiles();
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.ctrlKey && e.key.toLowerCase() === "a") {
        const homeView = $("view-home");
        if (!homeView || homeView.classList.contains("hidden")) return;
        const active = document.activeElement;
        if (active && active.matches("input, textarea, select")) return;
        e.preventDefault();
        selectAllProfiles();
      }
    });
  }
  App.initProfilesTableControls = initProfilesTableControls;

  App.fillSelect = fillSelect;
  App.renderInfo = renderInfo;
  App.renderConfig = renderConfig;
})();
