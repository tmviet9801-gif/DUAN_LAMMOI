"""License Server + Admin Dashboard — quản lý license cho thuê AutoTool.

- DB: Supabase (Postgres) qua REST (service role key).
- Cấp / gia hạn / reset / thu hồi / treo license.
- Key sinh theo đúng scheme offline-HMAC của backend/license.py
  (config.LICENSE_SECRET phải khớp với SECRET trong backend).
- Admin dashboard SPA tại / (cần đăng nhập).
"""
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import auth
import license_keys as lk
from config import ADMIN_PASSWORD, PORT, SESSION_TTL, SUPABASE_SERVICE_KEY, SUPABASE_URL
from supabase_client import SupabaseClient

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("license-server")

app = FastAPI(title="AutoTool License Server")

sb = SupabaseClient(SUPABASE_URL, SUPABASE_SERVICE_KEY)

DASHBOARD_DIR = Path(__file__).resolve().parent / "dashboard"


# ---------- helpers ----------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_iso(s) -> datetime:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return _now()


def _require_admin(request: Request):
    token = request.headers.get("Authorization", "")
    if token.startswith("Bearer "):
        token = token[7:]
    if not token or not auth.verify_session(token):
        raise HTTPException(status_code=401, detail="Chưa đăng nhập hoặc hết phiên")


def _get_license(lid: str) -> dict:
    lic = sb.get_one("licenses", {"id": f"eq.{lid}"})
    if not lic:
        raise HTTPException(status_code=404, detail="Không tìm thấy license")
    return lic


def _log_event(license_id: str, action: str, detail: str = ""):
    try:
        sb.insert("license_events", {"license_id": license_id, "action": action, "detail": detail})
    except Exception:
        log.warning("log event %s thất bại", action)


def _make_new_key(lic: dict, expires_dt: datetime, max_tabs=None, features=None, machine_id=None) -> str:
    return lk.make_key(
        machine_id or lic["machine_id"],
        int(expires_dt.timestamp()),
        max_tabs if max_tabs is not None else lic["max_tabs"],
        features or lic["features"],
    )


# ---------- auth ----------
@app.post("/api/admin/login")
def admin_login(body: dict):
    if (body.get("password") or "") != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Sai mật khẩu quản trị")
    return {"token": auth.create_session(), "expires_in": SESSION_TTL}


# ---------- thống kê ----------
@app.get("/api/stats")
def stats(request: Request):
    _require_admin(request)
    rows = sb.get(
        "licenses",
        select="id,machine_id,customer_name,plan_name,price,status,expires_at,created_at",
        order="created_at.desc",
        limit=20000,
    )
    now = _now()

    total = len(rows)
    active_rows = [r for r in rows if r.get("status") == "active"]
    active = len(active_rows)
    revoked = sum(1 for r in rows if r.get("status") == "revoked")
    suspended = sum(1 for r in rows if r.get("status") == "suspended")
    expired = sum(1 for r in rows if r.get("status") == "expired")

    expiring_soon = 0
    het_han_active = 0
    revenue = 0.0
    plan_buckets: Counter = Counter()
    top = Counter()
    for r in active_rows:
        exp = _parse_iso(r.get("expires_at"))
        if exp < now:
            het_han_active += 1
        elif exp <= now + timedelta(days=7):
            expiring_soon += 1
        revenue += float(r.get("price") or 0)
        plan_buckets[(r.get("plan_name") or "Tùy chỉnh").strip() or "Tùy chỉnh"] += 1
        top[r.get("customer_name") or "—"] += 1

    day_counts: Counter = Counter()
    cutoff = now - timedelta(days=29)
    for r in rows:
        c = _parse_iso(r.get("created_at"))
        if c >= cutoff:
            day_counts[c.strftime("%Y-%m-%d")] += 1
    days30 = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29, -1, -1)]
    issued_by_day = [day_counts.get(d, 0) for d in days30]

    month_rev: dict = {}
    cutoff6 = now - timedelta(days=182)
    for r in rows:
        c = _parse_iso(r.get("created_at"))
        if c >= cutoff6:
            m = c.strftime("%Y-%m")
            month_rev[m] = month_rev.get(m, 0) + float(r.get("price") or 0)
    months6 = []
    d = now.replace(day=1)
    for _ in range(6):
        months6.insert(0, d.strftime("%Y-%m"))
        d = (d - timedelta(days=1)).replace(day=1)
    revenue_by_month = [round(month_rev.get(m, 0)) for m in months6]

    return {
        "total": total,
        "active": active,
        "revoked": revoked,
        "suspended": suspended,
        "expired": expired,
        "expiring_soon": expiring_soon,
        "het_han_active": het_han_active,
        "revenue_monthly": round(revenue),
        "plans": [{"name": n, "count": c} for n, c in plan_buckets.items()],
        "issued_by_day": {"labels": days30, "data": issued_by_day},
        "revenue_by_month": {"labels": months6, "data": revenue_by_month},
        "top_customers": [{"name": n, "count": c} for n, c in top.most_common(5)],
    }


# ---------- licenses ----------
@app.get("/api/licenses")
def list_licenses(request: Request, status: str = None):
    _require_admin(request)
    filters = {"status": f"eq.{status}"} if status and status != "all" else None
    return sb.get("licenses", select="*", filters=filters, order="created_at.desc", limit=20000)


@app.post("/api/licenses")
def create_license(request: Request, body: dict):
    _require_admin(request)
    machine_id = (body.get("machine_id") or "").strip()
    if not machine_id:
        raise HTTPException(status_code=400, detail="Thiếu mã máy (MachineGuid) của khách")
    customer_name = (body.get("customer_name") or "").strip()
    contact = (body.get("contact") or "").strip()
    note = (body.get("note") or "").strip()
    plan_id = (body.get("plan_id") or "").strip() or None
    days = int(body.get("days") or 0)
    max_tabs = int(body.get("max_tabs") or 0)
    features = (body.get("features") or "").strip()

    plan = None
    if plan_id:
        plan = sb.get_one("plans", {"id": f"eq.{plan_id}"})
    if plan:
        days = days or int(plan.get("duration_days") or 30)
        max_tabs = max_tabs or int(plan.get("max_tabs") or 10)
        features = features or (plan.get("features") or "game")
        price = float(plan.get("price") or 0)
        plan_name = plan.get("name") or ""
    else:
        days = days or 30
        max_tabs = max_tabs or 10
        features = features or "game"
        price = 0.0
        plan_name = ""

    days = max(1, min(days, 3650))
    max_tabs = max(1, min(max_tabs, 50))

    expires_dt = _now() + timedelta(days=days)
    key = lk.make_key(machine_id, int(expires_dt.timestamp()), max_tabs, features)
    row = {
        "key": key,
        "machine_id": machine_id,
        "customer_name": customer_name,
        "contact": contact,
        "plan_id": plan_id,
        "plan_name": plan_name,
        "max_tabs": max_tabs,
        "features": features,
        "price": price,
        "status": "active",
        "expires_at": _iso(expires_dt),
        "note": note,
    }
    created = sb.insert("licenses", row)
    if created:
        _log_event(created[0]["id"], "issue", f"cấp {days} ngày, {max_tabs} tab")
    return created[0] if created else row


@app.post("/api/licenses/{lid}/extend")
def extend_license(lid: str, request: Request, body: dict):
    _require_admin(request)
    days = int(body.get("days") or 0)
    if days < 1 or days > 3650:
        raise HTTPException(status_code=400, detail="Số ngày gia hạn không hợp lệ (1-3650)")
    lic = _get_license(lid)
    current_exp = _parse_iso(lic.get("expires_at"))
    base = current_exp if current_exp > _now() else _now()
    new_exp = base + timedelta(days=days)
    new_key = _make_new_key(lic, new_exp)
    updated = sb.update(
        "licenses",
        {"key": new_key, "expires_at": _iso(new_exp), "status": "active"},
        {"id": f"eq.{lid}"},
    )
    _log_event(lid, "extend", f"+{days} ngày, hết hạn {_iso(new_exp)}")
    return updated[0] if updated else {"ok": True}


@app.post("/api/licenses/{lid}/reset")
def reset_license(lid: str, request: Request, body: dict):
    _require_admin(request)
    lic = _get_license(lid)
    days = int(body.get("days") or 0)
    max_tabs = int(body.get("max_tabs") or 0)
    machine_id = (body.get("machine_id") or "").strip()
    if max_tabs and not (1 <= max_tabs <= 50):
        raise HTTPException(status_code=400, detail="Số tab không hợp lệ (1-50)")
    if days:
        if not (1 <= days <= 3650):
            raise HTTPException(status_code=400, detail="Số ngày không hợp lệ (1-3650)")
        new_exp = _now() + timedelta(days=days)
    else:
        rem = (_parse_iso(lic.get("expires_at")) - _now()).total_seconds() // 86400
        new_exp = _now() + timedelta(days=max(1, int(rem) or 1))
    new_key = _make_new_key(
        lic,
        new_exp,
        max_tabs=max_tabs or None,
        machine_id=machine_id or None,
    )
    data = {"key": new_key, "expires_at": _iso(new_exp), "status": "active"}
    if machine_id:
        data["machine_id"] = machine_id
    if max_tabs:
        data["max_tabs"] = max_tabs
    updated = sb.update("licenses", data, {"id": f"eq.{lid}"})
    _log_event(lid, "reset", f"cấp lại key (máy {machine_id or lic['machine_id']})")
    return updated[0] if updated else {"ok": True}


@app.post("/api/licenses/{lid}/status")
def set_license_status(lid: str, request: Request, body: dict):
    _require_admin(request)
    lic = _get_license(lid)
    status = (body.get("status") or "").strip()
    if status not in ("active", "revoked", "suspended", "expired"):
        raise HTTPException(status_code=400, detail="Trạng thái không hợp lệ")
    data = {"status": status}
    if status in ("revoked", "suspended"):
        # offline HMAC: đẩy expires_at về hiện tại để key chết ngay trong app
        data["expires_at"] = _iso(_now())
    elif status == "active":
        exp = _parse_iso(lic.get("expires_at"))
        if exp < _now():
            new_exp = _now() + timedelta(days=30)
            data["expires_at"] = _iso(new_exp)
            data["key"] = _make_new_key(lic, new_exp)
    updated = sb.update("licenses", data, {"id": f"eq.{lid}"})
    _log_event(lid, status, "đổi trạng thái")
    return updated[0] if updated else {"ok": True}


@app.patch("/api/licenses/{lid}")
def update_license(lid: str, request: Request, body: dict):
    _require_admin(request)
    _get_license(lid)
    allowed = {}
    for k in ("customer_name", "contact", "note", "status", "max_tabs", "features"):
        if k in body and body[k] is not None:
            allowed[k] = body[k]
    if not allowed:
        raise HTTPException(status_code=400, detail="Không có gì để cập nhật")
    updated = sb.update("licenses", allowed, {"id": f"eq.{lid}"})
    return updated[0] if updated else {"ok": True}


@app.delete("/api/licenses/{lid}")
def delete_license(lid: str, request: Request):
    _require_admin(request)
    _get_license(lid)
    sb.delete("license_events", {"license_id": f"eq.{lid}"})
    sb.delete("licenses", {"id": f"eq.{lid}"})
    return {"ok": True}


@app.get("/api/licenses/{lid}/events")
def license_events(lid: str, request: Request):
    _require_admin(request)
    return sb.get(
        "license_events",
        select="*",
        filters={"license_id": f"eq.{lid}"},
        order="created_at.desc",
        limit=200,
    )


# ---------- plans ----------
@app.get("/api/plans")
def list_plans(request: Request):
    _require_admin(request)
    return sb.get("plans", select="*", order="price.asc", limit=500)


@app.post("/api/plans")
def create_plan(request: Request, body: dict):
    _require_admin(request)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu tên gói")
    data = {
        "name": name,
        "max_tabs": int(body.get("max_tabs") or 10),
        "features": (body.get("features") or "game").strip(),
        "price": float(body.get("price") or 0),
        "duration_days": int(body.get("duration_days") or 30),
        "active": bool(body.get("active", True)),
    }
    created = sb.insert("plans", data)
    return created[0] if created else data


@app.patch("/api/plans/{pid}")
def update_plan(pid: str, request: Request, body: dict):
    _require_admin(request)
    allowed = {}
    casts = {
        "name": str,
        "max_tabs": int,
        "features": str,
        "price": float,
        "duration_days": int,
        "active": bool,
    }
    for k, cast in casts.items():
        if k in body and body[k] is not None:
            allowed[k] = cast(body[k])
    if not allowed:
        raise HTTPException(status_code=400, detail="Không có gì để cập nhật")
    updated = sb.update("plans", allowed, {"id": f"eq.{pid}"})
    return updated[0] if updated else {"ok": True}


@app.delete("/api/plans/{pid}")
def delete_plan(pid: str, request: Request):
    _require_admin(request)
    sb.delete("plans", {"id": f"eq.{pid}"})
    return {"ok": True}


# ---------- public (app có thể gọi online, tùy chọn) ----------
@app.post("/api/public/verify")
def public_verify(body: dict):
    key = (body.get("key") or "").strip()
    parsed = lk.parse_key(key) if key else None
    if not parsed:
        return {"valid": False, "reason": "invalid_key"}
    lic = sb.get_one("licenses", {"key": f"eq.{key}"})
    if not lic:
        return {"valid": False, "reason": "key_not_issued"}
    if lic.get("status") == "revoked":
        return {"valid": False, "reason": "revoked"}
    if lic.get("status") == "suspended":
        return {"valid": False, "reason": "suspended"}
    if _parse_iso(lic.get("expires_at")) < _now():
        return {"valid": False, "reason": "expired"}
    try:
        sb.update("licenses", {"last_active_at": _iso(_now())}, {"id": f"eq.{lic['id']}"})
    except Exception:
        pass
    return {"valid": True, "max_tabs": lic.get("max_tabs"), "expires_at": lic.get("expires_at")}


# ---------- dashboard SPA ----------
@app.get("/")
def root():
    return FileResponse(DASHBOARD_DIR / "index.html")


app.mount("/assets", StaticFiles(directory=DASHBOARD_DIR / "assets"), name="assets")


if __name__ == "__main__":
    import uvicorn

    from config import HOST

    uvicorn.run(app, host=HOST, port=PORT)