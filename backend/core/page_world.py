"""Chạy JS trong world CỦA TRANG (không cô lập).

Patchright mặc định `isolated_context=True` cho `page.evaluate` / `frame.evaluate`:
JS chạy trong một world riêng để chống phát hiện, và world đó **không thấy biến
global của trang, cũng không thấy biến của content script `world: "MAIN"`**
(`backend/extension/content_main.js`).

Toàn bộ giao tiếp của tool với game dựa trên các global do `content_main.js`
tạo ra — `window.__autotool_is_in_tldl_lobby`, `__autotool_is_inside_table`,
`__autotool_exec_join`, `__ws_get_simms`, `__room_players`, `__last_room_info`…
Chạy trong world cô lập thì mọi biến đó là `undefined`, nên:

- `_is_in_tldl_lobby_util` luôn trả False -> "Không đưa được profile vào sảnh"
- `__autotool_is_inside_table` undefined -> không phát hiện được kẹt bàn cũ
- `__ws_get_simms()` trả null -> "Không gửi được join", tool không bao giờ
  vào được bàn đúng mức cược
- `p.evaluate(content_main_code)` chỉ tạo một BẢN SAO của extension trong world
  cô lập; bản sao đó patch `window.WebSocket` của chính world nó nên không bao
  giờ nhìn thấy socket thật của game.

Bằng chứng: Extension Hub báo balance/dn sống đúng (chỉ content_main.js đọc
được), trong khi cùng lúc `page.evaluate` thấy `window.WebSocket` vẫn là native
chưa patch. Một `window.WebSocket` không thể vừa bị patch vừa native trong cùng
một world.

Dùng `eval_page()` cho MỌI evaluate cần đọc/ghi state của game hoặc gọi helper
của extension.
"""


async def eval_page(target, expression, arg=None):
    """`target.evaluate(...)` nhưng chạy trong world của trang.

    `target` là Page hoặc Frame. Tự lùi về `evaluate` chuẩn khi đối tượng không
    nhận `isolated_context` — Playwright thuần, hoặc page giả trong test.
    """
    try:
        if arg is None:
            return await target.evaluate(expression, isolated_context=False)
        return await target.evaluate(expression, arg, isolated_context=False)
    except TypeError:
        if arg is None:
            return await target.evaluate(expression)
        return await target.evaluate(expression, arg)
