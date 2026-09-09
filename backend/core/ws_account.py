"""Đọc trạng thái account qua WebSocket bằng token đã lưu — KHÔNG mở Chrome.

Vì sao đi đường WebSocket chứ không phải HTTP: đã đo thực tế bằng cách hook
`fetch`/`XMLHttpRequest` ngay trong trang game suốt 45 giây. Endpoint HTTP duy
nhất còn sống là `GET /lobby/info.aspx`, và nó chỉ trả `{"data":{"time":...}}`
— một nhịp tim, không có thông tin tài khoản. Sau khi đăng nhập, game lấy MỌI
thứ qua WebSocket. Nên "check bằng request, không mở Chrome" = WebSocket.

Giao thức (đã bắt được từ khung thật):
  gửi  : [1,"Simms","","",{"agentId":"1","accessToken":"1-<32hex>","reconnect":false}]
  nhận : [1,true,0,"<session>","Simms",null]        -> xác thực OK
         [1,false,<mã>,"",null,""]                  -> hỏng (404 = token hết hạn)
  rồi  : [5,{"cmd":100,"dn":"<tên in-game>","uid":"1_643156061","As":{"gold":95745},...}]

`cmd 100` tới ngay sau khung xác thực và chứa đủ ba thứ cần: tên in-game, uid,
số dư. Không cần vào sảnh, không cần vào bàn.

CẢNH BÁO: chưa kiểm chứng được việc mở phiên WS thứ hai khi trình duyệt CÙNG
account đang mở có đá phiên kia ra hay không (lúc đo không có Chrome nào chạy).
Người gọi nên ưu tiên đọc từ trang khi profile đang mở, và chỉ dùng đường này
khi profile đóng. Xem `check_live.check_one_profile`.
"""
import asyncio
import json
import logging

from models.proxy_model import parse_proxy

log = logging.getLogger("core.ws_account")

WS_URL = "wss://carkgwaiz.hytsocesk.com/websocket"
ORIGIN = "https://v.hitclub.email"
UA_MAC_DINH = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36")

# Mã lỗi server trả trong khung [1,false,<mã>,...]
_GIAI_THICH_LOI = {
    404: "Token hết hạn hoặc không hợp lệ — cần mở profile đăng nhập lại.",
    401: "Token bị từ chối.",
    403: "Tài khoản bị chặn.",
}


def che_token(tok):
    """Che token khi ghi log — không bao giờ để token đầy đủ lọt ra log/API."""
    tok = str(tok or "")
    if len(tok) <= 12:
        return "<trống>"
    return f"{tok[:6]}…{tok[-4:]}"


def proxy_url(raw):
    """Chuỗi proxy của account -> URL cho `websockets`, hoặc None."""
    p = parse_proxy(raw)
    if not p:
        return None
    server = p.get("server") or ""
    user, pwd = p.get("username"), p.get("password")
    if user and pwd and "://" in server:
        lc, _, hostport = server.partition("://")
        return f"{lc}://{user}:{pwd}@{hostport}"
    return server or None


def _quet(msg, thay):
    """Dò `dn`/`uid`/`u`/`gold` ở mọi độ sâu — server đổi chỗ tuỳ khung."""
    if isinstance(msg, dict):
        for k, v in msg.items():
            kl = str(k).lower()
            if kl == "dn" and isinstance(v, str) and v and not thay["ten_in_game"]:
                thay["ten_in_game"] = v
            elif kl == "uid" and v and not thay["uid"]:
                thay["uid"] = str(v)
            elif kl == "u" and isinstance(v, str) and v and not thay.get("u"):
                thay["u"] = v
            elif kl == "gold" and isinstance(v, (int, float)):
                thay["so_du"] = v
            _quet(v, thay)
    elif isinstance(msg, list):
        for v in msg:
            _quet(v, thay)


def _ket_qua_rong():
    return {"ok": False, "ten_in_game": None, "uid": None, "u": None,
            "so_du": None, "loi": None, "ma_loi": None, "nguon": "ws"}


async def doc_qua_ws(token, *, user_agent=None, proxy=None, timeout=10.0,
                     url=WS_URL):
    """Xác thực bằng `token` rồi đọc tên in-game / uid / số dư.

    Không ném exception: mọi hỏng hóc trả về trong trường `loi` để người gọi
    quyết định — trùng cách `check_one_profile` đang làm.
    """
    out = _ket_qua_rong()
    if not token:
        out["loi"] = "Chưa có token đã lưu cho profile này."
        return out

    try:
        from websockets.asyncio.client import connect
    except Exception as e:                                   # pragma: no cover
        out["loi"] = f"Thiếu thư viện websockets: {e}"
        return out

    kwargs = {
        "additional_headers": {
            "User-Agent": user_agent or UA_MAC_DINH,
            "Origin": ORIGIN,
        },
        "open_timeout": timeout,
        "close_timeout": 5,
        "max_size": 8 << 20,
    }
    pu = proxy_url(proxy) if proxy else None
    if pu:
        kwargs["proxy"] = pu

    khung_auth = json.dumps(
        [1, "Simms", "", "", {"agentId": "1", "accessToken": token,
                              "reconnect": False}]
    )

    try:
        async with connect(url, **kwargs) as ws:
            await ws.send(khung_auth)
            han = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < han:
                con_lai = han - asyncio.get_event_loop().time()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(0.5, con_lai))
                except asyncio.TimeoutError:
                    break
                try:
                    msg = json.loads(raw if isinstance(raw, str)
                                     else raw.decode("utf-8", "replace"))
                except Exception:
                    continue

                # Khung xác thực: [1, ok, mã, session, zone, ...]
                if isinstance(msg, list) and msg and msg[0] == 1 and len(msg) >= 3:
                    if msg[1] is True:
                        out["ok"] = True
                        continue
                    ma = msg[2] if isinstance(msg[2], int) else None
                    out["ma_loi"] = ma
                    out["loi"] = _GIAI_THICH_LOI.get(
                        ma, f"Server từ chối xác thực (mã {ma}).")
                    return out

                _quet(msg, out)
                # `cmd 100` mang đủ cả ba -> xong sớm, không giữ phiên vô ích
                if out["ten_in_game"] and out["so_du"] is not None:
                    break
    except Exception as e:
        if out["ok"] and out["ten_in_game"]:
            # Server đóng sau khi đã trả dữ liệu — vẫn tính là đọc được
            log.debug("ws_account: đóng sau khi có dữ liệu: %s", e)
            return out
        out["loi"] = out["loi"] or f"Lỗi kết nối WebSocket: {type(e).__name__}: {e}"
        return out

    if out["ok"] and not out["ten_in_game"]:
        out["loi"] = "Xác thực OK nhưng server không trả khung thông tin tài khoản."
    return out
