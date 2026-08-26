(function () {
  // Theme toggle (light/dark) + đồng hồ thời gian thực
  const App = (window.App = window.App || {});
  const $ = App.$;
  const THEME_KEY = "autotool_theme";

  function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_KEY, theme);
    const btn = $("themeBtn");
    if (btn) btn.textContent = theme === "dark" ? "🌙" : "☀️";
  }

  function toggleTheme() {
    const cur = document.documentElement.getAttribute("data-theme") || "dark";
    setTheme(cur === "dark" ? "light" : "dark");
  }

  const saved = localStorage.getItem(THEME_KEY) || "dark";
  setTheme(saved);
  const btn = $("themeBtn");
  if (btn) btn.onclick = toggleTheme;
  App.toggleTheme = toggleTheme;

  // Đồng hồ (cập nhật mỗi giây)
  function updateClock() {
    const el = $("appClock");
    if (el) {
      el.textContent = new Date().toLocaleTimeString("vi-VN", {
        hour: "2-digit", minute: "2-digit", second: "2-digit",
      });
    }
  }
  updateClock();
  setInterval(updateClock, 1000);
})();