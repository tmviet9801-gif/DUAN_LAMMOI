"""Check Live: đọc trạng thái THẬT của profile rồi cập nhật lại database.

Vì sao cần: cơ chế ghép bàn xác minh đồng đội bằng cách khớp tên hiển thị
in-game (`dn` trong gói WS) với `character_name` trong accounts.json. Nếu
`character_name` thiếu hoặc cũ thì:
  - profile không xác minh được -> không dùng làm đồng đội được;
  - tệ hơn, khớp nhầm sang TÊN ĐĂNG NHẬP. Hai tên chỉ khác một ký tự
    (đăng nhập `nicktestxabai1` vs in-game `nicktestxxabai1`), nên nhầm là
    khớp sai người — account giữ tiền có thể ngồi xả bài với khách lạ.

Nguồn dữ liệu, theo thứ tự tin cậy:
  1. Đọc thẳng từ trang đang mở (`__my_dn`, `__my_uid`, `__my_balance`) — sống nhất.
  2. Extension Hub (`dn`/`balance` do extension báo lên) — dự phòng khi đọc trang lỗi.
  3. localStorage `AUTOTOOL_BALANCE` — dự phòng cuối cho số dư.
  4. WebSocket bằng token đã lưu (`core.ws_account`) — KHÔNG cần mở Chrome.
     Chỉ dùng khi profile đang ĐÓNG: mở phiên WS thứ hai song song với
     trình duyệt cùng account có thể đá phiên kia ra, và điều đó chưa
     kiểm chứng được.

KHÔNG bịa dữ liệu: profile chưa mở hoặc chưa đăng nhập thì báo đúng như vậy,
không đoán theo tên profile.
"""
import logging

from core.page_world import eval_page
from core.ws_account import doc_qua_ws
from game_sim.token_store import TokenStore
from models.config_model import DATA_DIR, load_accounts, save_accounts

log = logging.getLogger("auto_flow_controller")


_READ_LIVE_JS = """() => {
    const bal = (() => {
        if (typeof window.__my_balance === 'number') return window.__my_balance;
        try {
            const raw = localStorage.getItem('AUTOTOOL_BALANCE');
            if (raw !== null && raw !== '') {
                const v = Number(raw);
                if (!isNaN(v)) return v;
            }
        } catch (e) {}
        return null;
    })();
    return {
        dn: window.__my_dn || null,
        u: window.__my_u || null,
        uid: window.__my_uid || null,
        balance: bal,
        // Extension đã nạp chưa — nếu chưa thì mọi giá trị trên đều vô nghĩa
        hooked: !!window.__ws_main_hooked,
        on_login: (typeof window.__autotool_is_on_login_screen === 'function')
            ? !!window.__autotool_is_on_login_screen() : null,
    };
}"""


def _norm(s):
    return str(s or "").strip()


async def _lay_trang_dang_mo(adapter, name):
    """Trang của profile NẾU đang mở — không bao giờ tự bật Chrome lên.

    Adapter thật có `peek_page()` (tra session sẵn có). Bản cũ gọi `_page()`,
    mà `_page()` -> `page_pool.get_or_open()` -> MỞ profile. Với Check Live đó
    là tác dụng phụ sai: người dùng muốn biết số dư, không muốn 5 cửa sổ
    Chrome bật lên. Adapter nào không có `peek_page` thì vẫn dùng `_page`.
    """
    if adapter is None:
        return None
    peek = getattr(adapter, "peek_page", None)
    if callable(peek):
        pg = peek(name)
        return await pg if hasattr(pg, "__await__") else pg
    return await adapter._page(name)


async def check_one_profile(adapter, hub, account, *, token_store=None,
                            ep_ws=False):
    """Đọc trạng thái sống của MỘT account. Không ghi database ở đây.

    Trả về dict mô tả đúng những gì đọc được, kể cả khi thất bại — người gọi tự
    quyết định có cập nhật database hay không.

    `ep_ws=True` dùng WebSocket cả khi profile đang mở. Mặc định KHÔNG, vì
    phiên WS thứ hai có thể đá phiên trình duyệt đang đăng nhập.
    """
    name = account.get("name")
    out = {
        "profile": name,
        "mo": False,
        "dang_nhap": None,
        "ten_in_game": None,
        "uid": None,
        "u": None,
        "so_du": None,
        "nguon": None,
        "loi": None,
        "ma_loi": None,
        "token_key": None,
    }

    page = None
    try:
        page = await _lay_trang_dang_mo(adapter, name)
    except Exception as e:
        out["loi"] = f"Không đọc được trang: {e}"

    if page is not None:
        out["mo"] = True
        try:
            live = await eval_page(page, _READ_LIVE_JS) or {}
            if not live.get("hooked"):
                out["loi"] = ("Extension chưa nạp vào trang (content_main.js). "
                              "Đóng và mở lại profile.")
            else:
                out["dang_nhap"] = (False if live.get("on_login") is True
                                    else (True if live.get("on_login") is False else None))
                out["ten_in_game"] = _norm(live.get("dn")) or None
                out["uid"] = _norm(live.get("uid")) or None
                out["u"] = _norm(live.get("u")) or None
                out["so_du"] = live.get("balance")
                out["nguon"] = "trang"
        except Exception as e:
            out["loi"] = f"Đọc trang lỗi: {e}"

    # Dự phòng: lấy từ Extension Hub khi trang không cho dữ liệu
    if (out["ten_in_game"] is None or out["so_du"] is None) and hub is not None:
        try:
            st = hub.get_profile_state(name) or {}
        except Exception:
            st = {}
        if out["ten_in_game"] is None and _norm(st.get("dn")):
            out["ten_in_game"] = _norm(st.get("dn"))
            out["nguon"] = "hub"
        if out["so_du"] is None and st.get("balance") is not None:
            out["so_du"] = st.get("balance")
            out["nguon"] = out["nguon"] or "hub"
        if out["uid"] is None and _norm(st.get("uid")):
            out["uid"] = _norm(st.get("uid"))

    # Cuối: WebSocket bằng token đã lưu — đường duy nhất đọc được mà không mở
    # Chrome. Chỉ chạy khi profile ĐÓNG (hoặc bị ép), để không đá phiên đang mở.
    thieu = out["ten_in_game"] is None or out["so_du"] is None
    if thieu and (ep_ws or not out["mo"]):
        store = token_store or TokenStore(DATA_DIR / "game_sim_token.json")
        token, khoa = store.find_for_account(account)
        if not token:
            out["loi"] = out["loi"] or "Chưa có token đã lưu — mở profile đăng nhập một lần."
        else:
            kq = await doc_qua_ws(
                token,
                user_agent=account.get("user_agent"),
                proxy=account.get("proxy"),
            )
            if kq.get("ten_in_game"):
                out["ten_in_game"] = out["ten_in_game"] or kq["ten_in_game"]
                out["dang_nhap"] = True
            if kq.get("uid"):
                out["uid"] = out["uid"] or kq["uid"]
            if kq.get("u"):
                out["u"] = out["u"] or kq["u"]
            if kq.get("so_du") is not None and out["so_du"] is None:
                out["so_du"] = kq["so_du"]
            if kq.get("ten_in_game") or kq.get("so_du") is not None:
                out["nguon"] = "ws"
                out["loi"] = None
                out["token_key"] = khoa
            else:
                out["loi"] = kq.get("loi") or out["loi"]
                out["ma_loi"] = kq.get("ma_loi")

    return out


def apply_to_account(account, live):
    """Ghi kết quả đọc được vào record account. Trả về danh sách trường đã đổi.

    Chỉ ghi khi có giá trị thật — không xoá dữ liệu cũ bằng None.
    """
    changed = []

    ten = live.get("ten_in_game")
    if ten:
        cu = _norm(account.get("character_name"))
        if cu != ten:
            account["character_name"] = ten
            changed.append(f"character_name: {cu or '(trống)'} -> {ten}")

    uid = live.get("uid")
    if uid and _norm(account.get("uid")) != uid:
        account["uid"] = uid
        changed.append("uid")

    # `game_username` giữ trường `u` của gói WS, KHÔNG phải `uid`. Đây là quy
    # ước sẵn có (`account_controller._apply_real_identity`), và `context.py`
    # dùng `game_username` làm ứng viên đối chiếu profile — nhét nhầm uid vào
    # đây là bơm rác vào tập định danh.
    u = live.get("u") or uid
    if u and _norm(account.get("game_username")) != _norm(u):
        account["game_username"] = u
        changed.append("game_username")

    so_du = live.get("so_du")
    if so_du is not None and account.get("balance") != so_du:
        account["balance"] = so_du
        changed.append("balance")

    return changed


def canh_bao_trung_ten(accounts):
    """Hai account KHÔNG được trùng tên in-game.

    Toàn bộ xác minh đồng đội dựa trên tên này; trùng nhau thì không phân biệt
    được ai với ai, và cơ chế ghép bàn có thể chọn nhầm người.
    """
    theo_ten = {}
    for a in accounts:
        ten = _norm(a.get("character_name")).lower()
        if not ten:
            continue
        theo_ten.setdefault(ten, []).append(a.get("name"))
    return [
        f"Tên in-game '{ten}' bị trùng ở: {', '.join(str(x) for x in ds)}"
        for ten, ds in theo_ten.items() if len(ds) > 1
    ]


async def check_live(adapter, hub, profile_names=None, *, ep_ws=False):
    """Check Live cho một hoặc nhiều profile, rồi cập nhật accounts.json.

    `profile_names=None` -> kiểm tra mọi account có trong database.
    `ep_ws=True` -> luôn dùng WebSocket, kể cả profile đang mở.
    """
    accounts = load_accounts()
    store = TokenStore(DATA_DIR / "game_sim_token.json")
    muon = None
    if profile_names:
        muon = {_norm(n).lower() for n in profile_names if _norm(n)}

    ket_qua = []
    co_thay_doi = False
    for a in accounts:
        if not a or not a.get("name"):
            continue
        if muon is not None and _norm(a.get("name")).lower() not in muon:
            continue

        live = await check_one_profile(adapter, hub, a, token_store=store,
                                       ep_ws=ep_ws)
        changed = apply_to_account(a, live)
        if changed:
            co_thay_doi = True
        live["da_cap_nhat"] = changed
        live["ten_dang_nhap"] = a.get("username")   # để đối chiếu bằng mắt
        ket_qua.append(live)

    if co_thay_doi:
        save_accounts(accounts)
        log.info("check-live: đã cập nhật %d profile vào accounts.json",
                 sum(1 for r in ket_qua if r["da_cap_nhat"]))

    return {
        "ok": True,
        "so_luong": len(ket_qua),
        "ket_qua": ket_qua,
        "canh_bao": canh_bao_trung_ten(accounts),
    }
