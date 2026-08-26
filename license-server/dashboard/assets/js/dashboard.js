window.Dashboard = (function () {
  let charts = {};

  function card(label, value, cls) {
    return `<div class="card ${cls || ""}"><div class="card-value">${value}</div><div class="card-label">${label}</div></div>`;
  }

  async function load() {
    const s = await AdminAPI.get("/api/stats");
    const UI = window.UI;

    UI.$("#statCards").innerHTML =
      card("Dang hoat dong", s.active, "accent") +
      card("Sap het han (7 ngay)", s.expiring_soon, "warn") +
      card("Qua han", s.het_han_active, "danger") +
      card("Tong license", s.total) +
      card("Da thu hoi", s.revoked, "muted") +
      card("Doanh thu/thang (VND)", s.revenue_monthly.toLocaleString("vi-VN"), "accent");

    // doughnut: license theo goi
    const pieLabels = s.plans.map((p) => p.name);
    const pieData = s.plans.map((p) => p.count);
    const colors = ["#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4", "#a855f7", "#84cc16"];
    if (!charts.plans) {
      charts.plans = new Chart(UI.$("#chartPlans"), {
        type: "doughnut",
        data: { labels: pieLabels, datasets: [{ data: pieData, backgroundColor: colors }] },
        options: { plugins: { legend: { position: "bottom" } } },
      });
    } else {
      charts.plans.data.labels = pieLabels;
      charts.plans.data.datasets[0].data = pieData;
      charts.plans.data.datasets[0].backgroundColor = colors;
      charts.plans.update();
    }

    // line: cap theo ngay
    if (!charts.issued) {
      charts.issued = new Chart(UI.$("#chartIssued"), {
        type: "line",
        data: {
          labels: s.issued_by_day.labels,
          datasets: [{
            label: "So license cap",
            data: s.issued_by_day.data,
            borderColor: "#6366f1",
            fill: true,
            backgroundColor: "rgba(99,102,241,.15)",
            tension: 0.3,
          }],
        },
        options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } },
      });
    } else {
      charts.issued.data.labels = s.issued_by_day.labels;
      charts.issued.data.datasets[0].data = s.issued_by_day.data;
      charts.issued.update();
    }

    // bar: doanh thu theo thang
    if (!charts.rev) {
      charts.rev = new Chart(UI.$("#chartRevenue"), {
        type: "bar",
        data: {
          labels: s.revenue_by_month.labels,
          datasets: [{ label: "VND", data: s.revenue_by_month.data, backgroundColor: "#22c55e" }],
        },
        options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
      });
    } else {
      charts.rev.data.labels = s.revenue_by_month.labels;
      charts.rev.data.datasets[0].data = s.revenue_by_month.data;
      charts.rev.update();
    }

    // top khach
    UI.$("#topCustomers").innerHTML =
      `<thead><tr><th>Khach</th><th>So license</th></tr></thead><tbody>` +
      s.top_customers.map((c) => `<tr><td>${UI.esc(c.name)}</td><td>${c.count}</td></tr>`).join("") +
      `</tbody>`;

    // sap het han
    const all = await AdminAPI.get("/api/licenses?status=active");
    const now = Date.now();
    const soon = all
      .filter((l) => { const t = new Date(l.expires_at).getTime(); return t > now && t - now <= 7 * 864e5; })
      .sort((a, b) => new Date(a.expires_at) - new Date(b.expires_at));
    UI.$("#expiringTable").innerHTML =
      `<thead><tr><th>Khach</th><th>May</th><th>Het han</th><th>Tab</th></tr></thead><tbody>` +
      (soon.length
        ? soon.map((l) => `<tr><td>${UI.esc(l.customer_name || "—")}</td><td class="mono">${UI.esc((l.machine_id || "").slice(0, 20))}</td><td>${UI.fmtDate(l.expires_at)}</td><td>${l.max_tabs}</td></tr>`).join("")
        : `<tr><td colspan="4" class="muted">Khong co</td></tr>`) +
      `</tbody>`;
  }

  return { load };
})();