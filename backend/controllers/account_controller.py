"""Controller: quản lý tài khoản / profile."""
import json
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from models.config_model import get_profiles_dir, load_accounts, new_account_record, save_accounts
from platform_config import DEFAULT_PROFILE_URL
from services.account_service import bulk_names, ensure_account_fingerprints

log = logging.getLogger("account_controller")
router = APIRouter()


class AccountIn(BaseModel):
    name: str
    url: str = DEFAULT_PROFILE_URL
    user_agent: str = ""
    proxy: str = ""
    save_session: bool = True
    username: str = ""
    password: str = ""


class AccountBulkIn(BaseModel):
    prefix: str
    count: int = 1
    url: str = DEFAULT_PROFILE_URL
    user_agent: str = ""
    proxy: str = ""
    save_session: bool = True
    username: str = ""
    password: str = ""


class ImportAccountsIn(BaseModel):
    accounts: list[dict] = []  # [{username, password}]


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
async def get_accounts():
    accounts = ensure_account_fingerprints(load_accounts())
    for i, a in enumerate(accounts):
        a["index"] = i + 1
    return accounts


@router.post("/api/accounts/import")
async def import_accounts(body: ImportAccountsIn):
    """Import tài khoản (nick|pass). Tự gán cho profile chưa có account,
    tạo profile mới nếu hết profile trống."""
    items = []
    for it in body.accounts:
        username = (it.get("username") or "").strip()
        password = (it.get("password") or "").strip()
        if username:
            items.append({"username": username, "password": password})
    if not items:
        raise HTTPException(status_code=400, detail="Không có tài khoản hợp lệ")

    accounts = load_accounts()
    assigned = 0
    created = 0
    skipped = 0
    for it in items:
        target = next((a for a in accounts if not a.get("username")), None)
        if target:
            target["username"] = it["username"]
            target["password"] = it["password"]
            assigned += 1
        else:
            record = new_account_record(
                {
                    "name": it["username"],
                    "url": DEFAULT_PROFILE_URL,
                    "user_agent": "",
                    "proxy": "",
                    "save_session": True,
                    "username": it["username"],
                    "password": it["password"],
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
    record = new_account_record(a.model_dump())
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
    accounts = load_accounts()
    created = []
    for i, name in enumerate(names):
        proxy = proxies[i % len(proxies)] if proxies else ""
        record = new_account_record(
            {
                "name": name,
                "url": b.url,
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

    Game HITCLUB lưu token login trong localStorage nhưng Firefox/Playwright
    KHÔNG flush localStorage xuống đĩa khi đóng persistent context — nên mở lại
    bị mất login. Gọi endpoint này sau khi login để lưu chủ động.
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
