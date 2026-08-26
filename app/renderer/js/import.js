(function () {
  // Import tài khoản từ file txt / paste (nick|password mỗi dòng)
  const App = (window.App = window.App || {});
  const $ = App.$;

  function parseContent(text) {
    const out = [];
    for (const line of String(text || "").split("\n")) {
      const s = line.trim();
      if (!s) continue;
      // hỗ trợ dấu phân cách | : ; tab
      const parts = s.split(/[|:;\t]/);
      if (parts.length >= 1 && parts[0].trim()) {
        out.push({ username: parts[0].trim(), password: (parts[1] || "").trim() });
      }
    }
    return out;
  }

  function updatePreview() {
    const text = $("impFile").files && $("impFile").files[0]
      ? $("impFile").files[0].name + " (đã chọn)"
      : "";
    const parsed = parseContent($("impText").value);
    const n = parsed.length;
    $("impPreview").textContent = text
      ? `${text} — nhận diện ${n} tài khoản`
      : n ? `Nhận diện ${n} tài khoản` : "Nhập nick|password, mỗi dòng 1 tài khoản.";
  }

  function openImport() {
    $("importModal").classList.remove("hidden");
    $("impText").value = "";
    $("impFile").value = "";
    updatePreview();
  }
  App.openImport = openImport;

  function closeImport() {
    $("importModal").classList.add("hidden");
  }

  // Đọc file nếu chọn
  $("impFile").onchange = () => {
    const file = $("impFile").files && $("impFile").files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      $("impText").value = String(reader.result || "");
      updatePreview();
    };
    reader.readAsText(file);
  };
  $("impText").addEventListener("input", updatePreview);
  $("impCancel").onclick = closeImport;
  $("importModal").onclick = (e) => {
    if (e.target === $("importModal")) closeImport();
  };

  $("impSubmit").onclick = async () => {
    const parsed = parseContent($("impText").value);
    if (!parsed.length) {
      App.toast("Chưa có tài khoản hợp lệ", "warn");
      return;
    }
    const btn = $("impSubmit");
    btn.disabled = true;
    try {
      const r = await App.api("/api/accounts/import", {
        method: "POST",
        body: JSON.stringify({ accounts: parsed }),
      });
      App.toast(`Đã import ${r.imported} tài khoản (gán ${r.assigned}, tạo mới ${r.created})`, "success");
      closeImport();
      App.refresh();
    } catch (e) {
      App.toast("Import thất bại: " + e.message, "error");
    } finally {
      btn.disabled = false;
    }
  };
})();