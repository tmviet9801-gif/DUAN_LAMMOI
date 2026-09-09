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
    character_name: str | None = None
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
        p_state = ext_hub.get_profile_state(a.get("name") or a.get("username") or a.get("character_name") or "") if ext_hub else None
        is_ext_connected = bool(p_state and p_state.get("connected"))

        # Phân biệt rõ ràng:
        # 1. Tài khoản đăng nhập (Account Username)
        # 2. Tên nhân vật in-game (Character Name - dùng để tìm bàn & so khớp)
        ws_local = a.get("web_storage", {}).get("local", {})
        a["username"] = a.get("username") or ws_local.get("KEY_USER_NAME") or a.get("name")
        a["character_name"] = (
            (p_state and p_state.get("dn"))
            or a.get("character_name")
            or a.get("game_username")
            or a.get("name")
            or a["username"]
        )

        if (s and s.page) or is_ext_connected:
            a["status"] = "Live"
            a["connected"] = True

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

            # 4. Bài trên tay: Nếu không ở trong bàn (room == -1), bài bắt buộc là []
            cur_room = a.get("room", -1)
            if cur_room == -1 or cur_room is None or str(cur_room) == "-1":
                a["cards"] = []
            elif p_state and p_state.get("cards") is not None:
                a["cards"] = p_state["cards"]
            else:
                a["cards"] = a.get("cards") or []
        else:
            a["status"] = "Idle"
            a["connected"] = False
            a["cards"] = []
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
    val = _parse_balance(body.balance)

    accounts = load_accounts()
    matched_profile = p_name
    updated = False
    for a in accounts:
        if _match_account(a, p_name):
            a["balance"] = val
            matched_profile = a.get("name") or p_name
            updated = True
            break
    if updated:
        save_accounts(accounts)

    ext_hub = getattr(request.app.state, "ext_hub", None)
    if ext_hub:
        ext_hub.handle_message(matched_profile, {"type": "BALANCE_UPDATE", "balance": val})

    events = getattr(request.app.state, "events", None)
    if events:
        events.publish({"type": "accounts_updated", "profile_name": matched_profile, "balance": val})

    return {"ok": True, "profile_name": matched_profile, "balance": val}


def _parse_balance(raw) -> int | float | str:
    """Chuyển balance từ Extension (số nguyên / có dấu phân cách) về số.

    - "54068" -> 54068
    - "54.068" -> 54068 (dấu chấm phân tách hàng nghìn)
    - "1.234.567" -> 1234567
    - "10.000" -> 10000
    - "1234,56" -> 1234.56 (số thập phân, không nhân 100)
    """
    s = str(raw).strip()
    if not s:
        return raw
    # Bỏ dấu phẩy phân tách hàng nghìn (1,234 / 12,345)
    cleaned = s.replace(",", "")
    # Nếu có NHIỀU dấu chấm -> chấm là phân tách hàng nghìn (VN: 1.234.567)
    if cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")
    elif cleaned.count(".") == 1:
        before, after = cleaned.split(".")
        # "1.234" / "10.000" -> phân tách hàng nghìn (3 chữ số sau chấm), không phải số thập phân
        if len(after) == 3:
            cleaned = before + after
    try:
        f = float(cleaned)
        if f.is_integer():
            return int(f)
        return f
    except Exception:
        return raw


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
    canonical_name = p_name
    for a in accounts:
        if _match_account(a, p_name):
            a["cards"] = cards
            canonical_name = a.get("name") or p_name
            updated = True
            break
    if updated:
        save_accounts(accounts)

    ext_hub = getattr(request.app.state, "ext_hub", None)
    if ext_hub:
        ext_hub.handle_message(canonical_name, {"type": "CARDS_DEALT", "cards": cards})

    events = getattr(request.app.state, "events", None)
    if events:
        events.publish({"type": "cards_updated", "profile_name": p_name, "cards": cards})
        events.publish({"type": "accounts_updated", "profile_name": p_name, "cards": cards})
        if canonical_name != p_name:
            events.publish({"type": "cards_updated", "profile_name": canonical_name, "cards": cards})
            events.publish({"type": "accounts_updated", "profile_name": canonical_name, "cards": cards})

    return {"ok": True, "profile_name": canonical_name, "cards": cards}


class UpdateLogIn(BaseModel):
    profile_name: str
    log: str


def _account_aliases(acc: dict) -> list[str]:
    """Tập hợp toàn bộ định danh của 1 tài khoản để so khớp mềm từ Extension.

    Extension gửi lên các tên khác nhau tuỳ ngữ cảnh: tên profile (Account01),
    username đăng nhập, tên nhân vật in-game (dn), uid... Nên phải khớp được
    hết các trường này nếu không balance/log/cards từ Extension sẽ bị bỏ qua
    âm thầm (nguyên nhân: "số dư không realtime", "log cũ không được xoá").
    """
    if not isinstance(acc, dict):
        return []
    aliases = []
    for key in ("name", "username", "character_name", "game_username", "id", "uid"):
        val = acc.get(key)
        if isinstance(val, (str, int)) and str(val).strip():
            aliases.append(str(val).strip())
    ws_local = (acc.get("web_storage") or {}).get("local") or {}
    for key in ("KEY_USER_NAME", "AUTOTOOL_PROFILE_NAME", "AUTOTOOL_IN_GAME_DN", "AUTOTOOL_IN_GAME_U"):
        val = ws_local.get(key)
        if isinstance(val, str) and val.strip():
            aliases.append(val.strip())
    return aliases


def _match_account(acc: dict, p_name: str) -> bool:
    if not p_name:
        return False
    acc_id = str(acc.get("id") or "").strip()
    idx = str(acc.get("index") or "").strip()
    target = p_name.strip().lower()

    aliases = [a.lower() for a in _account_aliases(acc)]
    if target in aliases:
        return True

    norm_target = "".join(c for c in target if c.isalnum())
    norm_aliases = ["".join(c for c in a if c.isalnum()) for a in aliases]
    if norm_target and norm_target in norm_aliases:
        return True

    norm_name = "".join(c for c in str(acc.get("name") or "").lower() if c.isalnum())
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


class UpdateUsernameIn(BaseModel):
    profile_name: str
    real_dn: str          # Tên hiển thị in-game chính xác (từ server game, cmd 100)
    real_u: str = ""      # Username in-game (có thể trùng hoặc khác dn)
    real_uid: str = ""    # UID số (định danh tuyệt đối)


@router.post("/api/accounts/update-username")
async def update_account_username(body: UpdateUsernameIn, request: Request):
    """AUTO-SYNC tên in-game thực tế từ Extension vào accounts.json.
    
    Được gọi tự động mỗi khi game trả về cmd 100 (thông tin user).
    Ghi đúng tên nhân vật thực tế (real_dn) vào trường username để tránh
    lỗi lệch ký tự do người dùng nhập sai (ví dụ 1 chữ x vs 2 chữ x).
    """
    p_name   = (body.profile_name or "").strip()
    real_dn  = (body.real_dn or "").strip()
    real_u   = (body.real_u or "").strip()
    real_uid = (body.real_uid or "").strip()

    if not p_name or not real_dn:
        return {"ok": False, "error": "Thiếu profile_name hoặc real_dn"}

    accounts = load_accounts()
    matched_profile = p_name
    old_username = ""
    updated = False

    for a in accounts:
        if _match_account(a, p_name):
            old_char = a.get("character_name", "")
            # Ghi đúng tên nhân vật in-game vào character_name (dùng để tìm bàn và so khớp)
            a["character_name"] = real_dn
            a["game_username"] = real_dn
            if not a.get("username"):
                a["username"] = real_dn

            if real_uid:
                a["uid"] = real_uid
            if real_u and real_u != real_dn:
                a["game_username"] = real_u  # lưu thêm u-field để tham chiếu
            matched_profile = a.get("name") or p_name
            updated = True
            break

    if updated:
        save_accounts(accounts)
        if old_username != real_dn:
            log.info(
                "AUTO-SYNC username: profile='%s' | '%s' -> '%s' (uid=%s)",
                matched_profile, old_username, real_dn, real_uid
            )

    # Thông báo qua Hub WebSocket để broadcast_partners re-sync
    ext_hub = getattr(request.app.state, "ext_hub", None)
    if ext_hub:
        ext_hub.handle_message(matched_profile, {
            "type": "AUTOTOOL_USERNAME_SYNC",
            "real_dn": real_dn,
            "real_u": real_u,
            "real_uid": real_uid,
        })

    # Đẩy sự kiện SSE lên App UI để cập nhật tên ngay lập tức
    events = getattr(request.app.state, "events", None)
    if events:
        events.publish({
            "type": "accounts_updated",
            "profile_name": matched_profile,
            "username": real_dn,
            "uid": real_uid or None,
        })

    return {
        "ok": True,
        "profile_name": matched_profile,
        "username": real_dn,
        "uid": real_uid or None,
        "changed": old_username != real_dn,
    }


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
async def update_account(account_id: str, body: AccountUpdateIn, request: Request):
    accounts = load_accounts()
    for a in accounts:
        if a["id"] == account_id:
            data = body.model_dump(exclude_unset=True)
            a.update(data)
            # 1. Tên tài khoản đăng nhập (Account Username)
            if "username" in data and data["username"]:
                new_user = str(data["username"]).strip()
                a["username"] = new_user
                if "web_storage" not in a or not isinstance(a["web_storage"], dict):
                    a["web_storage"] = {}
                if "local" not in a["web_storage"] or not isinstance(a["web_storage"]["local"], dict):
                    a["web_storage"]["local"] = {}
                a["web_storage"]["local"]["KEY_USER_NAME"] = new_user

            # 2. Tên nhân vật in-game (Character Name)
            if "character_name" in data and data["character_name"]:
                new_char = str(data["character_name"]).strip()
                a["character_name"] = new_char
                a["game_username"] = new_char

            save_accounts(accounts)
            log.info("updated account %s: %s", account_id, data)

            # Broadcast lại partners cho mọi extension đang mở để nhận ngay lập tức
            ext_hub = getattr(request.app.state, "ext_hub", None)
            if ext_hub:
                try:
                    await ext_hub.broadcast_partners()
                except Exception as ex:
                    log.warning("broadcast_partners error: %s", ex)

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

    # Token là thông tin đăng nhập — không được sống lâu hơn chủ của nó. Xoá
    # profile mà bỏ token lại là để credential nằm trong data/ vô thời hạn, và
    # `find_for_account` của một account mới trùng tên có thể nhặt phải nó.
    # DATA_DIR import BÊN TRONG hàm: bind ở mức module thì fixture test không
    # ghi đè được, và test xoá account sẽ đụng file credential THẬT.
    try:
        from game_sim.token_store import TokenStore
        from models.config_model import DATA_DIR

        store = TokenStore(DATA_DIR / "game_sim_token.json")
        for account in to_delete.values():
            n = store.clear_for_account(account)
            if n:
                log.info("đã xoá %d khoá token của %s", n, account.get("name"))
    except Exception as e:
        log.warning("xoá token khi xoá account thất bại: %s", e)

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
