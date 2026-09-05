"""Controller: quản lý tài khoản / profile."""
import json
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from models.config_model import (
    get_profiles_dir,
    load_accounts,
    load_config,
    new_account_record,
    save_accounts,
)
from platform_config import DEFAULT_PROFILE_URL
from services.account_service import bulk_names

log = logging.getLogger("account_controller")
router = APIRouter()


def _default_url() -> str:
    """URL mặc định cho profile: ưu tiên cấu hình (default_url), fallback platform."""
    url = (load_config().get("default_url") or "").strip()
    return url or DEFAULT_PROFILE_URL


class AccountIn(BaseModel):
    name: str
    url: str = ""
    user_agent: str = ""
    proxy: str = ""
    save_session: bool = True
    username: str = ""
    password: str = ""


class AccountBulkIn(BaseModel):
    prefix: str
    count: int = 1
    url: str = ""
    user_agent: str = ""
    proxy: str = ""
    save_session: bool = True
    username: str = ""
    password: str = ""


class ImportAccountsIn(BaseModel):
    accounts: list[dict] = []  # [{username, password, proxy}]
    raw_text: str = ""


class AccountUpdateIn(BaseModel):
    proxy: str | None = None
    name: str | None = None
    url: str | None = None
    user_agent: str | None = None
    username: str | None = None
    password: str | None = None


def _split_proxies(raw: str) -> list[str]:
    return [p.strip() for p in (raw or "").splitlines() if p.strip()]


@router.get("/api/accounts")
async def get_accounts(request: Request):
    manager = getattr(request.app.state, "manager", None)
    ext_hub = getattr(request.app.state, "ext_hub", None)
    sessions = manager.sessions if manager else {}
    accounts = load_accounts()

    for i, a in enumerate(accounts):
        a["index"] = i + 1
        s = None
        for sess in sessions.values():
            if sess.account and (sess.account.get("id") == a.get("id") or sess.account.get("name") == a.get("name")):
                s = sess
                break

        a["site"] = a.get("site") or "HIT"

        # Tra cứu trạng thái từ ExtensionHub nếu profile đang kết nối extension
        p_state = ext_hub.get_profile_state(a.get("name") or a.get("username") or "") if ext_hub else None
        is_ext_connected = bool(p_state and p_state.get("connected"))

        if (s and s.page) or is_ext_connected:
            a["status"] = "Live"
            a["connected"] = True
            ws_local = a.get("web_storage", {}).get("local", {})
            user_dn = ws_local.get("KEY_USER_NAME") or a.get("username") or a.get("name")
            a["username"] = user_dn

            # 1. Số dư: Ưu tiên ext_hub realtime -> a.get("balance")
            if p_state and p_state.get("balance") is not None:
                a["balance"] = p_state["balance"]
            elif "balance" not in a or a["balance"] == "--":
                a["balance"] = a.get("balance") or "--"

            # 2. Mã phòng: Ưu tiên ext_hub realtime -> session -> a.get("room")
            if p_state and p_state.get("room_id") is not None:
                a["room"] = p_state["room_id"]
            elif p_state and p_state.get("room_info") and p_state["room_info"].get("rid"):
                a["room"] = p_state["room_info"]["rid"]
            else:
                s_room = getattr(s, "room_id", None) if s else None
                if s_room and s_room != -1:
                    a["room"] = s_room
                elif "room" not in a or a["room"] is None:
                    a["room"] = -1

            # 3. Log trạng thái: Ưu tiên ext_hub -> session -> a.get("log")
            if p_state and p_state.get("log"):
                a["log"] = p_state["log"]
            else:
                s_log = getattr(s, "log", "") if s else ""
                if s_log:
                    a["log"] = s_log
                elif "log" not in a or not a["log"]:
                    a["log"] = "Đang kết nối..."
        else:
            a["status"] = "Idle"
            a["connected"] = False
            if "room" not in a:
                a["room"] = -1
            if "log" not in a:
                a["log"] = ""
            if "balance" not in a:
                a["balance"] = "--"

    return accounts


class UpdateBalanceIn(BaseModel):
    profile_name: str
    balance: int | float | str


@router.post("/api/accounts/update-balance")
async def update_account_balance(body: UpdateBalanceIn, request: Request):
    """Cập nhật số dư tài khoản từ extension hoặc luồng game."""
    p_name = body.profile_name.strip()
    try:
        val = int(float(str(body.balance).replace(",", "").replace(".", "").strip()))
    except Exception:
        val = body.balance

    accounts = load_accounts()
    updated = False
    for a in accounts:
        if a.get("name") == p_name or a.get("username") == p_name or str(a.get("id")) == p_name:
            a["balance"] = val
            updated = True
            break
    if updated:
        save_accounts(accounts)

    ext_hub = getattr(request.app.state, "ext_hub", None)
    if ext_hub:
        ext_hub.handle_message(p_name, {"type": "BALANCE_UPDATE", "balance": val})

    events = getattr(request.app.state, "events", None)
    if events:
        events.publish({"type": "accounts_updated", "profile_name": p_name, "balance": val})

    return {"ok": True, "profile_name": p_name, "balance": val}


class UpdateCardsIn(BaseModel):
    profile_name: str
    cards: list = []


@router.post("/api/accounts/update-cards")
async def update_account_cards(body: UpdateCardsIn, request: Request):
    """Cập nhật danh sách bài trên tay của tài khoản."""
    p_name = body.profile_name.strip()
    cards = body.cards or []
    accounts = load_accounts()
    updated = False
    for a in accounts:
        if _match_account(a, p_name):
            a["cards"] = cards
            updated = True
            break
    if updated:
        save_accounts(accounts)

    ext_hub = getattr(request.app.state, "ext_hub", None)
    if ext_hub:
        ext_hub.handle_message(p_name, {"type": "CARDS_DEALT", "cards": cards})

    events = getattr(request.app.state, "events", None)
    if events:
        events.publish({"type": "cards_updated", "profile_name": p_name, "cards": cards})
        events.publish({"type": "accounts_updated", "profile_name": p_name, "cards": cards})

    return {"ok": True, "profile_name": p_name, "cards": cards}


class UpdateLogIn(BaseModel):
    profile_name: str
    log: str


def _match_account(acc: dict, p_name: str) -> bool:
    if not p_name:
        return False
    name = str(acc.get("name") or "").strip().lower()
    username = str(acc.get("username") or "").strip().lower()
    acc_id = str(acc.get("id") or "").strip()
    idx = str(acc.get("index") or "").strip()
    target = p_name.strip().lower()

    if target in (name, username, acc_id, idx):
        return True

    norm_target = "".join(c for c in target if c.isalnum())
    norm_name = "".join(c for c in name if c.isalnum())
    norm_user = "".join(c for c in username if c.isalnum())

    if norm_target and (norm_target == norm_name or norm_target == norm_user):
        return True

    # Khớp chính xác theo hậu tố số 1 hoặc 2 (Profile 1 vs Profile 2)
    if norm_target.endswith("1") and (norm_name.endswith("1") or idx == "1"):
        return True
    if norm_target.endswith("2") and (norm_name.endswith("2") or idx == "2"):
        return True

    return False


@router.post("/api/accounts/update-log")
async def update_account_log(body: UpdateLogIn, request: Request):
    """Cập nhật log trạng thái tài khoản hiển thị trên Desktop App."""
    p_name = body.profile_name.strip()
    log_text = body.log.strip()

    accounts = load_accounts()
    matched_profile = p_name
    updated = False
    for a in accounts:
        if _match_account(a, p_name):
            a["log"] = log_text
            matched_profile = a.get("name") or p_name
            updated = True
            break
    if updated:
        save_accounts(accounts)

    ext_hub = getattr(request.app.state, "ext_hub", None)
    if ext_hub:
        ext_hub.handle_message(matched_profile, {"type": "LOG_UPDATE", "log": log_text})

    events = getattr(request.app.state, "events", None)
    if events:
        events.publish({"type": "accounts_updated", "profile_name": matched_profile, "log": log_text})

    return {"ok": True, "profile_name": matched_profile, "log": log_text}


@router.post("/api/accounts/import")
async def import_accounts(body: ImportAccountsIn):
    """Import tài khoản (nick|pass hoặc nick|pass|proxy). Tự gán cho profile chưa có account,
    tạo profile mới nếu hết profile trống."""
    items = list(body.accounts)
    raw = body.raw_text.strip()
    if raw:
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|")]
            u = parts[0] if len(parts) > 0 else ""
            p = parts[1] if len(parts) > 1 else ""
            px = parts[2] if len(parts) > 2 else ""
            if u:
                items.append({"username": u, "password": p, "proxy": px})

    if not items:
        raise HTTPException(status_code=400, detail="Không có tài khoản hợp lệ")

    accounts = load_accounts()
    assigned = 0
    created = 0
    skipped = 0
    for it in items:
        u = it.get("username") or ""
        p = it.get("password") or ""
        px = it.get("proxy") or ""
        target = next((a for a in accounts if not a.get("username")), None)
        if target:
            target["username"] = u
            target["password"] = p
            if px:
                target["proxy"] = px
            assigned += 1
        else:
            record = new_account_record(
                {
                    "name": u,
                    "url": _default_url(),
                    "proxy": px,
                    "save_session": True,
                    "username": u,
                    "password": p,
                },
                existing=accounts,
            )
            accounts.append(record)
            created += 1
    save_accounts(accounts)
    log.info("imported %d accounts (assigned=%d, created=%d, skipped=%d)",
             len(items), assigned, created, skipped)
    return {"imported": len(items), "assigned": assigned, "created": created, "skipped": skipped}


@router.post("/api/accounts")
async def add_account(a: AccountIn):
    data = a.model_dump()
    data["url"] = (data["url"] or "").strip() or _default_url()
    record = new_account_record(data)
    accounts = load_accounts()
    accounts.append(record)
    save_accounts(accounts)
    record["index"] = len(accounts)
    log.info("added account %s #%s", record["name"], record["index"])
    return record


@router.post("/api/accounts/bulk")
async def add_accounts_bulk(b: AccountBulkIn):
    prefix = b.prefix.strip()
    if not prefix:
        raise HTTPException(status_code=400, detail="Thiếu tên / tiền tố")
    count = max(1, min(int(b.count), 500))
    names = bulk_names(prefix, count)
    proxies = _split_proxies(b.proxy)
    url = (b.url or "").strip() or _default_url()
    accounts = load_accounts()
    created = []
    for i, name in enumerate(names):
        proxy = proxies[i % len(proxies)] if proxies else ""
        record = new_account_record(
            {
                "name": name,
                "url": url,
                "user_agent": b.user_agent,
                "proxy": proxy,
                "save_session": b.save_session,
            },
            existing=accounts,
        )
        accounts.append(record)
        record["index"] = len(accounts)
        created.append(record)
    save_accounts(accounts)
    log.info("bulk added %d accounts (prefix=%s)", len(created), prefix)
    return {"accounts": created, "count": len(created)}


@router.patch("/api/accounts/{account_id}")
async def update_account(account_id: str, body: AccountUpdateIn):
    accounts = load_accounts()
    for a in accounts:
        if a["id"] == account_id:
            data = body.model_dump(exclude_unset=True)
            a.update(data)
            save_accounts(accounts)
            log.info("updated account %s: %s", account_id, data)
            return a
    raise HTTPException(status_code=404, detail="Không tìm thấy profile")


def _delete_profile_dir(account: dict | None):
    """Xóa thư mục profile trên đĩa (chỉ khi nằm trong profiles_dir)."""
    profile_dir = (account or {}).get("profile_dir")
    if not profile_dir:
        return
    try:
        pd = Path(profile_dir).resolve()
        base = get_profiles_dir().resolve()
        if pd.exists() and (pd == base or base in pd.parents):
            shutil.rmtree(pd, ignore_errors=True)
            log.info("deleted profile dir %s", pd)
        else:
            log.warning("skip delete dir outside profiles_dir: %s", pd)
    except Exception as e:
        log.warning("delete profile dir failed: %s", e)


async def _delete_accounts(manager, account_ids: list[str]) -> int:
    """Đóng session, xóa khỏi accounts.json và xóa thư mục profile hàng loạt."""
    ids = set(account_ids)
    accounts = load_accounts()
    to_delete = {a["id"]: a for a in accounts if a["id"] in ids}

    for sid in [
        s.session_id
        for s in manager.sessions.values()
        if s.account and s.account["id"] in ids
    ]:
        await manager.close_session(sid)

    remaining = [a for a in accounts if a["id"] not in ids]
    save_accounts(remaining)
    for account in to_delete.values():
        _delete_profile_dir(account)

    log.info("deleted %d accounts", len(to_delete))
    return len(to_delete)


class BulkDeleteIn(BaseModel):
    account_ids: list[str] = []


@router.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str, request: Request):
    n = await _delete_accounts(request.app.state.manager, [account_id])
    if not n:
        raise HTTPException(status_code=404, detail="Không tìm thấy profile")
    return {"ok": True}


@router.post("/api/accounts/bulk-delete")
async def delete_accounts_bulk(body: BulkDeleteIn, request: Request):
    n = await _delete_accounts(request.app.state.manager, body.account_ids)
    return {"ok": True, "deleted": n}


@router.post("/api/accounts/{account_id}/save-session")
async def save_account_session(account_id: str, request: Request):
    """Đọc toàn bộ localStorage + sessionStorage từ page đang mở và lưu vào account.

    Game HITCLUB lưu token login trong localStorage. Gọi endpoint này sau khi
    login để lưu chủ động (mở lại profile không cần login lại).
    """
    manager = request.app.state.manager
    session = None
    for s in manager.sessions.values():
        if s.account and s.account.get("id") == account_id and s.page:
            session = s
            break
    if not session:
        raise HTTPException(status_code=400, detail="Không tìm thấy session đang mở cho profile này")
    try:
        ls = await session.page.evaluate("JSON.stringify(window.localStorage)")
        ss = await session.page.evaluate("JSON.stringify(window.sessionStorage)")
        data = {}
        if ls:
            ld = json.loads(ls)
            if ld:
                data["local"] = ld
        if ss:
            sd = json.loads(ss)
            if sd:
                data["session"] = sd
        accounts = load_accounts()
        for a in accounts:
            if a["id"] == account_id:
                a["web_storage"] = data
                break
        save_accounts(accounts)
        session.account["web_storage"] = data
        log.info(
            "manual save web storage for %s (local=%d, session=%d)",
            session.account.get("name"), len(data.get("local", {})), len(data.get("session", {})),
        )
        return {"ok": True, "local": len(data.get("local", {})), "session": len(data.get("session", {}))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
