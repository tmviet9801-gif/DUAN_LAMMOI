// Background Service Worker — Cầu nối API tin cậy cho Extension
const BACKEND_BASE = "http://127.0.0.1:8000";
const BACKEND_FALLBACK = "http://localhost:8000";

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "API_CALL") {
    handleApiCall(message)
      .then((res) => sendResponse({ ok: true, data: res }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true; // Giữ channel mở cho async sendResponse
  }

  if (message.type === "CHECK_HEALTH") {
    checkHealth()
      .then((status) => sendResponse({ ok: status }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }
});

async function checkHealth() {
  try {
    const res = await fetch(`${BACKEND_BASE}/health`, { signal: AbortSignal.timeout(2500) });
    if (res.ok) return true;
  } catch (_) {}

  try {
    const res2 = await fetch(`${BACKEND_FALLBACK}/health`, { signal: AbortSignal.timeout(2500) });
    return res2.ok;
  } catch (_) {
    return false;
  }
}

async function handleApiCall({ path, method = "GET", body = null }) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body && method !== "GET") {
    opts.body = typeof body === "string" ? body : JSON.stringify(body);
  }

  try {
    const res = await fetch(`${BACKEND_BASE}${path}`, opts);
    return await res.json();
  } catch (err) {
    // Thử fallback sang localhost nếu 127.0.0.1 lỗi
    const res2 = await fetch(`${BACKEND_FALLBACK}${path}`, opts);
    return await res2.json();
  }
}
