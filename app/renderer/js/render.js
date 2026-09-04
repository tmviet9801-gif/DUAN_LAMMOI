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
    $("cfgMuteAll").checked = !!state.config.mute_all_sites;
    $("cfgDefaultUrl").value = state.config.default_url || "";
    if (state.antiDetect) {
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

    if ($("profileCount")) $("profileCount").textContent = total;
    const tbody = $("profileTbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="13" class="hint" style="text-align:center; padding: 20px;">Không có profile nào.</td></tr>';
    }

    const allChecked = rows.length > 0 && rows.every((a) => App.selectedProfileIds.has(a.id));
    if ($("thCheckAll")) $("thCheckAll").checked = allChecked;
    if ($("chkSelectAll")) $("chkSelectAll").checked = allChecked;

    rows.forEach((a, i) => {
      const tr = document.createElement("tr");
      const selected = App.selectedProfileIds.has(a.id);
      if (selected) tr.classList.add("row-selected");
      const proxy = a.proxy ? String(a.proxy) : "";
      const isOpen = (App.state.sessions || []).some(
        (s) => s.account && (s.account.id === a.id || s.account.name === a.name) && s.state === "ready"
      );
      const isConnected = isOpen || Boolean(a.connected);
      const balanceStr = (a.balance !== undefined && a.balance !== null && a.balance !== "" && !isNaN(Number(a.balance))) 
        ? Number(a.balance).toLocaleString() 
        : (a.balance || "--");
      const roomStr = a.room ? App.esc(String(a.room)) : "-";
      const logStr = a.log ? App.esc(String(a.log)) : (isOpen ? "Đang chạy Chrome" : "Sẵn sàng");
      const statusText = isOpen ? "Live" : (a.status || "Idle");
      const statusBadge = `<span class="${statusText === 'Live' ? 'badge-live' : 'badge-idle'}">${statusText}</span>`;

      tr.innerHTML = `
        <td style="text-align:center;"><input type="checkbox" class="row-chk" ${selected ? "checked" : ""} /></td>
        <td class="td-username cell-clickable" title="Click hoặc đúp chuột để sửa thông tin tài khoản">
          ${App.esc(a.username || a.name)} <span class="ico-edit" title="Sửa thông tin">✏️</span>
        </td>
        <td class="td-name cell-clickable" title="Click hoặc đúp chuột để sửa thông tin">${App.esc(a.name || a.username)}</td>
        <td class="td-proxy" title="${App.esc(proxy || "IP máy")}">${proxy ? App.esc(proxy) : '<span class="ip-local">IP máy</span>'}</td>
        <td class="td-balance">${balanceStr}</td>
        <td class="td-room">${roomStr}</td>
        <td class="td-log" title="${logStr}">${logStr}</td>
        <td>${statusBadge}</td>
        <td><button class="btn-tbl btn-tb cyan btn-row-find" title="Tìm phòng cho ${App.esc(a.name)}">Tìm.P</button></td>
        <td><button class="btn-tbl btn-tb red btn-row-leave" title="Thoát phòng cho ${App.esc(a.name)}">Thoát.P</button></td>
        <td>
          <select class="sel-tbl sel-row-site">
            <option value="HIT" ${(!a.site || a.site === 'HIT') ? 'selected' : ''}>HIT</option>
            <option value="SUN" ${a.site === 'SUN' ? 'selected' : ''}>SUN</option>
          </select>
        </td>
        <td><button class="btn-tbl btn-tb red-dark btn-row-stop" title="Dừng thao tác ${App.esc(a.name)}">Dừng</button></td>
        <td style="text-align:center;">
          <span class="dot-connect ${isConnected ? 'connected' : 'offline'}" title="${isConnected ? 'Connected' : 'Offline'}"></span>
        </td>
      `;

      // Checkbox event
      const chk = tr.querySelector(".row-chk");
      chk.onclick = (e) => {
        e.stopPropagation();
        toggleRowSelection(a.id);
      };

      // Mở modal sửa thông tin khi click vào Username hoặc Name
      tr.querySelector(".td-username").onclick = (e) => {
        e.stopPropagation();
        App.openEditProfile(a);
      };
      tr.querySelector(".td-name").onclick = (e) => {
        e.stopPropagation();
        App.openEditProfile(a);
      };

      // Đúp chuột vào dòng để sửa
      tr.ondblclick = (e) => {
        e.stopPropagation();
        App.openEditProfile(a);
      };

      // Tìm.P button: Chọn nick này làm Chính và kích hoạt Gom Bàn đồng bộ
      tr.querySelector(".btn-row-find").onclick = async (e) => {
        e.stopPropagation();
        if ($("gcProfileMain")) $("gcProfileMain").value = a.name;
        if ($("btnGcSyncMatch")) {
          $("btnGcSyncMatch").click();
        } else {
          App.toast(`Đã chọn ${a.name} làm Account Chính`, "info");
        }
      };

      // Thoát.P button
      tr.querySelector(".btn-row-leave").onclick = async (e) => {
        e.stopPropagation();
        App.toast(`Đang thoát phòng ${a.name}...`, "info");
        try {
          await App.api("/api/autoplay/stop", {
            method: "POST",
            body: JSON.stringify({ profile_name: a.name }),
          });
          App.toast(`Đã thoát phòng ${a.name}`, "success");
        } catch (err) {
          App.toast(`Thoát phòng ${a.name} lỗi: ${err.message}`, "error");
        }
      };

      // Site change
      tr.querySelector(".sel-row-site").onchange = (e) => {
        e.stopPropagation();
        a.site = e.target.value;
      };

      // Dừng button
      tr.querySelector(".btn-row-stop").onclick = async (e) => {
        e.stopPropagation();
        try {
          await App.api("/api/autoplay/stop", {
            method: "POST",
            body: JSON.stringify({ profile_name: a.name }),
          });
          App.toast(`Đã dừng ${a.name}`, "success");
        } catch (err) {
          App.toast(`Dừng ${a.name} lỗi: ${err.message}`, "error");
        }
      };

      tr.onclick = (e) => {
        if (e.target.tagName === 'BUTTON' || e.target.tagName === 'SELECT' || e.target.tagName === 'INPUT' || e.target.closest(".cell-clickable")) return;
        toggleRowSelection(a.id);
      };

      tbody.appendChild(tr);
    });

    if ($("pageInfo")) $("pageInfo").textContent = `${total ? start + 1 : 0}-${Math.min(start + pageSize, total)} / ${total}`;
    if ($("pagePrev")) $("pagePrev").disabled = tableState.page <= 1;
    if ($("pageNext")) $("pageNext").disabled = tableState.page >= pages;
    updateSelectionCounter();
  }
  App.renderProfilesTable = renderProfilesTable;

  function toggleRowSelection(id) {
    if (App.selectedProfileIds.has(id)) App.selectedProfileIds.delete(id);
    else App.selectedProfileIds.add(id);

    // Tự động gán cặp ghép Chính & Phụ nếu chọn từ 2 nick
    const sel = Array.from(App.selectedProfileIds);
    if (sel.length >= 2 && App.setSyncPair) {
      const a1 = (App.state.accounts || []).find((x) => x.id === sel[0]);
      const a2 = (App.state.accounts || []).find((x) => x.id === sel[1]);
      if (a1 && a2) {
        App.setSyncPair(a1.name, a2.name);
      }
    }
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
    if ($("profSearch")) {
      $("profSearch").addEventListener("input", () => {
        tableState.search = $("profSearch").value;
        tableState.page = 1;
        renderProfilesTable();
      });
      $("profSearch").addEventListener("keydown", (e) => {
        if (e.ctrlKey && e.key.toLowerCase() === "a") {
          e.preventDefault();
          selectAllProfiles();
        }
      });
    }

    if ($("profSort")) {
      $("profSort").addEventListener("change", () => {
        tableState.sort = $("profSort").value;
        tableState.page = 1;
        renderProfilesTable();
      });
    }

    const toggleAll = (checked) => {
      if (checked) selectAllProfiles();
      else clearSelection();
    };

    if ($("thCheckAll")) {
      $("thCheckAll").onchange = (e) => toggleAll(e.target.checked);
    }
    if ($("chkSelectAll")) {
      $("chkSelectAll").onchange = (e) => toggleAll(e.target.checked);
    }

    if ($("pagePrev")) {
      $("pagePrev").onclick = () => {
        if (tableState.page > 1) {
          tableState.page--;
          renderProfilesTable();
        }
      };
    }
    if ($("pageNext")) {
      $("pageNext").onclick = () => {
        const pages = Math.max(1, Math.ceil(getFilteredProfiles().length / tableState.pageSize));
        if (tableState.page < pages) {
          tableState.page++;
          renderProfilesTable();
        }
      };
    }
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
