"""Danh mục bàn ĐỌC TỪ SERVER, thay cho bảng RID chép cứng.

`FIXED_TABLE_RIDS` là một ảnh chụp tĩnh: nó nói rid 2 là bàn $100 Solo. Hôm nay
đúng — đã đối chiếu với 28 phòng trong bản bắt thật, không lệch một dòng nào.
Nhưng tool không có cách nào BIẾT nếu server thêm một mức cược hoặc đổi thứ tự
danh sách. Khi đó rid 2 thành $500 Solo, và tool vẫn thản nhiên gửi
`[3,"Simms",2,""]` rồi đối chiếu `.b` — nếu `.b` cũng bị ghi đè hay thiếu thì cả
nhóm vào $500 im lặng; còn nếu `.b` đúng thì thành vòng lặp vô tận: gửi rid 2 ->
vào $500 -> sai cược -> out -> nghỉ 3,5s -> lại gửi rid 2, mãi mãi, vì không ai
sửa bảng.

Nguồn dữ liệu (đo từ khung thật):
  gửi  : [6,"Simms","channelPlugin",{"cmd":300,"aid":"1","gid":1}]
  nhận : [5,{"cmd":300,"rs":[{rid,b,Mu,gid,mM,rn,uC,hpwd,...}, ...],"pR":...}]

Mỗi phòng cho đủ ba thứ cần: `rid`, mức cược `b`, số chỗ `Mu` — và cả `mM`, số
dư tối thiểu để ngồi được, vốn cũng đang bị chép cứng ở `preflight.py`.

Ghi chú: chú thích trong `hitclub._find_empty_room` nói "game KHÔNG trả cmd=300
rs[]". Điều đó KHÔNG đúng với bản bắt hiện tại — một khung `recv` chứa `rs` với
đủ 28 phòng. Dù vậy vẫn đọc thêm `cmd 305 ri` làm nguồn phụ, vì đó là đường game
đẩy từng bàn một và có thể tới trước.
"""
import asyncio
import json
import logging
from pathlib import Path

log = logging.getLogger("game_sim.room_catalog")

# Bao lâu thì coi danh mục đã lưu là cũ. Danh sách bàn của server rất ít đổi,
# nhưng để quá lâu thì mất luôn ý nghĩa của việc đối chiếu lúc chạy.
HAN_DUNG_GIAY = 24 * 3600


def _khoa(bet, mu) -> str:
    return f"{int(bet)}_{int(mu)}"


def gop_phong(rooms, gid=1):
    """Từ danh sách phòng thô -> bảng rid và bảng số dư tối thiểu.

    Chỉ nhận phòng ĐÚNG game và có đủ ba trường; phòng thiếu dữ liệu bị bỏ chứ
    không đoán, vì đoán sai ở đây là gửi cả nhóm vào bàn khác mức cược.
    """
    rid_theo_cap, so_du = {}, {}
    for r in rooms or []:
        if not isinstance(r, dict) or r.get("gid") != gid:
            continue
        rid, b, mu = r.get("rid"), r.get("b"), r.get("Mu")
        if not isinstance(rid, (int, float)) or rid <= 0:
            continue
        if not isinstance(b, (int, float)) or b <= 0:
            continue
        if not isinstance(mu, (int, float)) or mu <= 0:
            continue
        rid_theo_cap[_khoa(b, mu)] = int(rid)
        mM = r.get("mM")
        if isinstance(mM, (int, float)) and mM >= 0:
            so_du[str(int(b))] = int(mM)
    return rid_theo_cap, so_du


def _quet_khung(msgs, gid=1):
    """Trích phòng từ `cmd 300 rs[]` (nguồn chính) và `cmd 305 ri` (nguồn phụ)."""
    theo_rid, nguon = {}, None
    for it in msgs or []:
        text = it.get("text") if isinstance(it, dict) else None
        if not text:
            continue
        try:
            arr = json.loads(text)
        except Exception:
            continue
        if not isinstance(arr, list):
            continue
        for phan in arr:
            if not isinstance(phan, dict):
                continue
            if phan.get("cmd") == 300 and isinstance(phan.get("rs"), list):
                for r in phan["rs"]:
                    if isinstance(r, dict) and isinstance(r.get("rid"), (int, float)):
                        theo_rid[int(r["rid"])] = r
                nguon = "cmd300"
            elif phan.get("cmd") == 305 and isinstance(phan.get("ri"), dict):
                ri = phan["ri"]
                if isinstance(ri.get("rid"), (int, float)) and ri["rid"] > 0:
                    theo_rid.setdefault(int(ri["rid"]), ri)
                    nguon = nguon or "cmd305"
    return list(theo_rid.values()), nguon


async def doc_tu_server(page, sniffer, yeu_cau, gid=1, so_lan=3, cho=1.6):
    """Hỏi server danh sách bàn rồi dựng bảng. Trả dict, không ném exception."""
    ra = {"rid": {}, "so_du_toi_thieu": {}, "so_phong": 0, "nguon": None,
          "loi": None}
    if page is None or sniffer is None:
        ra["loi"] = "thiếu page/sniffer"
        return ra

    from game_sim.ws_sniffer import _PAGE_RECV

    for lan in range(so_lan):
        try:
            await sniffer.send_raw(page, yeu_cau)
        except Exception as e:
            ra["loi"] = f"gửi yêu cầu lỗi: {e}"
        await asyncio.sleep(cho)
        try:
            await sniffer.drain(page)
        except Exception:
            pass

        rooms, nguon = _quet_khung(_PAGE_RECV.get(id(page)) or [], gid=gid)
        rid_map, so_du = gop_phong(rooms, gid=gid)
        if rid_map:
            ra.update({"rid": rid_map, "so_du_toi_thieu": so_du,
                       "so_phong": len(rid_map), "nguon": nguon, "loi": None})
            log.info("danh mục bàn: đọc được %d cặp (cược_chỗ -> rid) từ %s "
                     "sau %d lượt hỏi", len(rid_map), nguon, lan + 1)
            return ra

    ra["loi"] = ra["loi"] or "server không trả danh sách bàn"
    return ra


# ---------- lưu / nạp ----------

def duong_dan(data_dir) -> Path:
    return Path(data_dir) / "room_catalog.json"


def luu(data_dir, danh_muc, gid=1, thoi_diem=None):
    """Ghi lại để lần sau dùng được ngay cả khi chưa mở trình duyệt.

    Preflight (kiểm số dư trước khi mở Chrome) chạy khi CHƯA có page nào, nên
    nó không tự hỏi server được — nó đọc bản đã lưu này.
    """
    if not danh_muc or not danh_muc.get("rid"):
        return False
    from core.time_utils import utcnow_iso

    p = duong_dan(data_dir)
    try:
        cu = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        if not isinstance(cu, dict):
            cu = {}
    except Exception:
        cu = {}
    cu[str(gid)] = {
        "rid": danh_muc["rid"],
        "so_du_toi_thieu": danh_muc.get("so_du_toi_thieu") or {},
        "nguon": danh_muc.get("nguon"),
        "doc_luc": thoi_diem or utcnow_iso(),
    }
    try:
        tam = p.with_suffix(".json.tmp")
        tam.write_text(json.dumps(cu, ensure_ascii=False, indent=2), encoding="utf-8")
        tam.replace(p)
        return True
    except Exception as e:
        log.warning("không lưu được danh mục bàn: %s", e)
        return False


def nap(data_dir, gid=1):
    """Đọc danh mục đã lưu. Trả `None` nếu chưa có hoặc hỏng."""
    p = duong_dan(data_dir)
    try:
        if not p.exists():
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        muc = d.get(str(gid)) if isinstance(d, dict) else None
        if isinstance(muc, dict) and muc.get("rid"):
            return muc
    except Exception as e:
        log.warning("không đọc được danh mục bàn: %s", e)
    return None


def doi_chieu(song, anh_chup):
    """So bảng đọc-lúc-chạy với ảnh chụp chép cứng.

    Trả danh sách mô tả các cặp LỆCH. Rỗng nghĩa là ảnh chụp vẫn đúng.
    """
    lech = []
    for khoa, rid in (song or {}).items():
        cu = (anh_chup or {}).get(khoa)
        if cu is not None and int(cu) != int(rid):
            b, mu = khoa.split("_", 1)
            lech.append(f"bàn ${b} {mu} chỗ: bảng chép cứng ghi rid {cu}, "
                        f"server trả rid {rid}")
    return lech
