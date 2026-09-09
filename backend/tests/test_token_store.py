"""Kho token: khoá chính tắc, ghi nguyên tử, và những bẫy đã suýt mắc.

Kho từng tích tụ 9 khoá cho 5 account. Các test dưới khoá lại ba bất biến rút
ra từ vòng phản bác thiết kế — mỗi cái tương ứng một cách hỏng cụ thể đã được
chỉ ra, không phải phòng xa chung chung.
"""
import json
import threading

import pytest

from game_sim.token_store import TokenStore

TOK1 = "1-" + "a" * 32
TOK2 = "1-" + "b" * 32
TOK3 = "1-" + "c" * 32


def _kho(tmp_path, data=None):
    f = tmp_path / "tok.json"
    f.write_text(json.dumps(data or {}), encoding="utf-8")
    return TokenStore(f)


ACC1 = {"id": "6f50bda5-1111", "name": "Account 01", "username": "nicktestxabai1",
        "character_name": "nicktestxxabai1"}
ACC2 = {"id": "ed7a8fb2-2222", "name": "Account 02", "username": "nicktestxabai2",
        "character_name": "nicktestxxabai2"}


# ---------- khoá chính tắc là id, không phải tên ----------

def test_ghi_theo_id_chu_khong_theo_ten(tmp_path):
    """Người dùng đổi tên account được; tên không làm khoá bền được."""
    store = _kho(tmp_path)
    assert store.save_for_account(ACC1, TOK1) is True

    d = json.loads((tmp_path / "tok.json").read_text(encoding="utf-8"))
    assert ACC1["id"] in d
    assert "Account 01" not in d
    assert d[ACC1["id"]]["account_name"] == "Account 01"
    assert d[ACC1["id"]]["username"] == "nicktestxabai1"


def test_doi_ten_account_van_tim_ra_token(tmp_path):
    """Đây là gốc rễ đã sinh ra khoá mồ côi: đổi tên mà không di trú khoá."""
    store = _kho(tmp_path)
    store.save_for_account(ACC1, TOK1)

    doi_ten = {**ACC1, "name": "Nick Chính"}
    tok, khoa = store.find_for_account(doi_ten)
    assert tok == TOK1, "đổi tên không được làm mất token"
    assert khoa == ACC1["id"]


def test_tim_duoc_qua_khoa_bi_danh_cu(tmp_path):
    """Kho thật có `Account01`, `Account 01` và cả tên đăng nhập cho một người."""
    store = _kho(tmp_path, {
        "Account01":      {"token": TOK1, "saved_at": "2026-09-03T11:40:00+00:00"},
        "nicktestxabai1": {"token": TOK2, "saved_at": "2026-09-05T16:43:10+00:00"},
        "Account 01":     {"token": TOK3, "saved_at": "2026-09-08T21:29:09+00:00"},
    })
    tok, khoa = store.find_for_account(ACC1)
    assert tok == TOK3, "phải chọn bản ghi mới nhất — token cũ đã hết hạn"
    assert khoa == "Account 01"


def test_khoa_id_thang_moi_ban_ghi_bi_danh(tmp_path):
    store = _kho(tmp_path, {
        "Account 01":  {"token": TOK1, "saved_at": "2099-01-01T00:00:00+00:00"},
        ACC1["id"]:    {"token": TOK2, "saved_at": "2026-01-01T00:00:00+00:00"},
    })
    tok, khoa = store.find_for_account(ACC1)
    assert (tok, khoa) == (TOK2, ACC1["id"]), "khoá id đáng tin hơn bí danh"


def test_khong_tim_thay_thi_tra_none(tmp_path):
    store = _kho(tmp_path, {"Account 01": {"token": TOK1, "saved_at": "2026-09-08"}})
    assert store.find_for_account({"id": "x", "name": "Account 99"}) == (None, None)
    assert store.find_for_account(None) == (None, None)


# ---------- BẤT BIẾN 1: ghi là đọc-sửa-ghi, không ghi đè ----------

def test_hai_instance_khong_xoa_thay_doi_cua_nhau(tmp_path):
    """Có ít nhất 4 nơi tự dựng TokenStore riêng trên CÙNG một file.

    Bản trước nạp file một lần trong __init__ rồi ghi cả dict — nên instance
    ghi sau XOÁ MẤT token instance khác vừa lưu.
    """
    f = tmp_path / "tok.json"
    f.write_text("{}", encoding="utf-8")
    a = TokenStore(f)
    b = TokenStore(f)          # dựng TRƯỚC khi a ghi -> ảnh chụp rỗng

    a.save_for_account(ACC1, TOK1)
    b.save_for_account(ACC2, TOK2)

    d = json.loads(f.read_text(encoding="utf-8"))
    assert ACC1["id"] in d, "token của instance ghi trước bị xoá mất"
    assert ACC2["id"] in d


def test_ghi_nguyen_tu_khong_de_lai_file_cut(tmp_path):
    store = _kho(tmp_path)
    store.save_for_account(ACC1, TOK1)
    assert not (tmp_path / "tok.json.tmp").exists(), "còn sót file tạm"
    json.loads((tmp_path / "tok.json").read_text(encoding="utf-8"))


def test_ghi_lai_cung_token_thi_khong_cham_dia(tmp_path):
    store = _kho(tmp_path)
    assert store.save_for_account(ACC1, TOK1) is True
    assert store.save_for_account(ACC1, TOK1) is False


# ---------- BẤT BIẾN 2: lock phải reentrant ----------

def test_khong_deadlock_khi_phuong_thuc_goi_lan_nhau(tmp_path):
    """`save()` gọi `save_for_account()`; Lock thường sẽ tự khoá chính mình.

    Các đường gọi này nằm trên event loop của backend, nên deadlock làm đứng
    hình cả tiến trình chứ không chỉ một request. Test có TIMEOUT để deadlock
    hiện thành ĐỎ chứ không thành treo vô hạn.
    """
    store = _kho(tmp_path)
    xong = threading.Event()

    def chay():
        # account không có id -> save_for_account lùi về save (gọi lồng nhau)
        store.save_for_account({"name": "Không Có Id"}, TOK1)
        store.find_for_account(ACC1)
        store.clear_for_account({"id": "x", "name": "Không Có Id"})
        xong.set()

    t = threading.Thread(target=chay, daemon=True)
    t.start()
    assert xong.wait(timeout=10), "DEADLOCK: phương thức gọi lồng nhau bị treo"


def test_nhieu_luong_ghi_dong_thoi_khong_mat_ban_ghi(tmp_path):
    f = tmp_path / "tok.json"
    f.write_text("{}", encoding="utf-8")
    accs = [{"id": f"id-{i}", "name": f"Acc {i}"} for i in range(12)]

    def ghi(a):
        TokenStore(f).save_for_account(a, "1-" + f"{hash(a['id']) & 0xffffffff:08x}" * 4)

    ts = [threading.Thread(target=ghi, args=(a,)) for a in accs]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=15)
        assert not t.is_alive(), "luồng ghi bị treo"

    d = json.loads(f.read_text(encoding="utf-8"))
    assert len(d) == 12, f"mất bản ghi khi ghi đồng thời: chỉ còn {len(d)}"


# ---------- BẤT BIẾN 3: đường đọc không bao giờ xoá ----------

def test_doc_khong_duoc_xoa_hay_chep_gi(tmp_path):
    """Ý tưởng "đọc xong tự lành" trao token người cũ cho người mới.

    `bulk_names` sinh đúng "Account01"..., nên một account MỚI có thể trùng
    tên với khoá cũ của account KHÁC. Đường đọc chỉ thấy MỘT account nên
    không biết khoá đó còn khớp ai nữa.
    """
    truoc = {
        "Account01":  {"token": TOK1, "saved_at": "2026-09-03T11:40:00+00:00"},
        "Account 01": {"token": TOK2, "saved_at": "2026-09-08T21:29:09+00:00"},
    }
    store = _kho(tmp_path, dict(truoc))
    store.find_for_account(ACC1)
    store.get("Account01")
    store.get_record("Account 01")

    sau = json.loads((tmp_path / "tok.json").read_text(encoding="utf-8"))
    assert sau == truoc, "đường đọc đã sửa dữ liệu"


# ---------- di trú ----------

def test_migrate_gop_9_khoa_ve_dung_mot_khoa_moi_account(tmp_path):
    store = _kho(tmp_path, {
        "Account01":      {"token": TOK1, "saved_at": "2026-09-03T11:40:00+00:00"},
        "nicktestxabai1": {"token": TOK2, "saved_at": "2026-09-05T16:43:10+00:00"},
        "Account 01":     {"token": TOK3, "saved_at": "2026-09-08T21:29:09+00:00"},
        "Account02":      {"token": TOK1, "saved_at": "2026-09-03T11:29:36+00:00"},
        "Account 02":     {"token": TOK2, "saved_at": "2026-09-08T20:37:58+00:00"},
    })
    bc = store.migrate([ACC1, ACC2], backup_path=tmp_path / "bak.json")

    d = json.loads((tmp_path / "tok.json").read_text(encoding="utf-8"))
    assert set(d) == {ACC1["id"], ACC2["id"]}
    assert d[ACC1["id"]]["token"] == TOK3, "phải giữ token MỚI NHẤT"
    assert d[ACC2["id"]]["token"] == TOK2
    assert bc["truoc"] == 5 and bc["sau"] == 2
    assert (tmp_path / "bak.json").exists()


def test_migrate_giu_nguyen_khoa_nhap_nhang(tmp_path):
    """Khoá khớp HAI account thì không được gán cho ai.

    Thêm hàng loạt sinh account mới tên "Account01" trong khi khoá cũ
    "Account01" thuộc về "Account 01" — gán bừa là trao token người này cho
    người kia.
    """
    moi = {"id": "moi-9999", "name": "Account01"}
    store = _kho(tmp_path, {
        "Account01": {"token": TOK1, "saved_at": "2026-09-03T11:40:00+00:00"},
    })
    bc = store.migrate([ACC1, moi], backup_path=tmp_path / "bak.json")

    d = json.loads((tmp_path / "tok.json").read_text(encoding="utf-8"))
    assert "Account01" in d, "khoá nhập nhằng phải được giữ nguyên"
    assert ACC1["id"] not in d and moi["id"] not in d
    assert len(bc["giu_nhap_nhang"]) == 1
    assert "Account 01" in bc["giu_nhap_nhang"][0]


def test_migrate_giu_khoa_khong_thuoc_ai(tmp_path):
    """Account đã bị xoá thì token của nó không được gán sang người khác."""
    store = _kho(tmp_path, {
        "AccountDaXoa": {"token": TOK1, "saved_at": "2026-09-01T00:00:00+00:00"},
    })
    bc = store.migrate([ACC1], backup_path=tmp_path / "bak.json")
    d = json.loads((tmp_path / "tok.json").read_text(encoding="utf-8"))
    assert "AccountDaXoa" in d
    assert bc["khong_chu"] == ["AccountDaXoa"]


def test_migrate_khong_dung_du_lieu_khi_khong_sao_luu_duoc(tmp_path):
    """Không có bản lùi thì không được xoá gì."""
    truoc = {"Account 01": {"token": TOK1, "saved_at": "2026-09-08T21:29:09+00:00"}}
    store = _kho(tmp_path, dict(truoc))
    # thư mục không tồn tại -> ghi sao lưu thất bại
    bc = store.migrate([ACC1], backup_path=tmp_path / "khong_co" / "bak.json")

    sau = json.loads((tmp_path / "tok.json").read_text(encoding="utf-8"))
    assert sau == truoc, "sao lưu hỏng mà vẫn đụng dữ liệu"
    assert bc["backup"] is None


def test_migrate_chay_hai_lan_khong_doi_gi_them(tmp_path):
    store = _kho(tmp_path, {
        "Account 01": {"token": TOK3, "saved_at": "2026-09-08T21:29:09+00:00"},
    })
    store.migrate([ACC1], backup_path=tmp_path / "b1.json")
    lan1 = json.loads((tmp_path / "tok.json").read_text(encoding="utf-8"))
    store.migrate([ACC1], backup_path=tmp_path / "b2.json")
    lan2 = json.loads((tmp_path / "tok.json").read_text(encoding="utf-8"))
    assert lan1 == lan2, "migrate phải idempotent"
    assert not (tmp_path / "b2.json").exists(), (
        "khong co gi de gop thi khong duoc rai them ban sao credential")


# ---------- xoá theo account ----------

def test_xoa_account_thi_xoa_moi_khoa_cua_no(tmp_path):
    """Token là thông tin đăng nhập — không được sống lâu hơn chủ của nó."""
    store = _kho(tmp_path, {
        "Account01":      {"token": TOK1, "saved_at": "2026-09-03"},
        "nicktestxabai1": {"token": TOK2, "saved_at": "2026-09-05"},
        ACC1["id"]:       {"token": TOK3, "saved_at": "2026-09-08"},
        ACC2["id"]:       {"token": TOK1, "saved_at": "2026-09-08"},
    })
    n = store.clear_for_account(ACC1)
    d = json.loads((tmp_path / "tok.json").read_text(encoding="utf-8"))
    assert n == 3
    assert set(d) == {ACC2["id"]}, "chỉ được xoá khoá của đúng account đó"


def test_xoa_account_khong_dung_toi_nguoi_khac(tmp_path):
    store = _kho(tmp_path, {ACC2["id"]: {"token": TOK1, "saved_at": "2026-09-08"}})
    assert store.clear_for_account(ACC1) == 0
    d = json.loads((tmp_path / "tok.json").read_text(encoding="utf-8"))
    assert set(d) == {ACC2["id"]}


# ---------- tương thích ngược ----------

def test_save_theo_ten_van_chay(tmp_path):
    """Chỗ gọi cũ chưa kịp chuyển sang save_for_account không được vỡ."""
    store = _kho(tmp_path)
    assert store.save("Account 01", TOK1, extra={"username": "nicktestxabai1"}) is True
    assert store.get("Account 01") == TOK1
    tok, _ = store.find_for_account(ACC1)
    assert tok == TOK1, "khoá thô vẫn phải tìm ra được qua bí danh"


def test_extract_from_storage_uu_tien_khoa_token():
    assert TokenStore.extract_from_storage({"rac": "x", "token": TOK1}) == TOK1
    assert TokenStore.extract_from_storage({"gi_do": f"...{TOK2}..."}) == TOK2
    assert TokenStore.extract_from_storage({}) is None
    assert TokenStore.extract_from_storage(None) is None


def test_token_khong_hop_le_thi_khong_ghi(tmp_path):
    store = _kho(tmp_path)
    assert store.save_for_account(ACC1, "khong-phai-token") is False
    assert store.save_for_account(ACC1, "") is False
    assert json.loads((tmp_path / "tok.json").read_text(encoding="utf-8")) == {}


# ---------- nối vào dự án ----------

def _src(*phan):
    from pathlib import Path

    return Path(__file__).parents[1].joinpath(*phan).read_text(encoding="utf-8")


def _code(*phan):
    """Chỉ dòng CODE — chú thích giải thích lỗi cũ có nhắc lại chuỗi bị cấm."""
    return "\n".join(d for d in _src(*phan).splitlines()
                     if not d.strip().lstrip("#").startswith(("#",))
                     and not d.strip().startswith("#"))


def test_moi_cho_ghi_deu_dung_khoa_id():
    """Còn một chỗ ghi theo tên thô là khoá mồ côi lại mọc."""
    for f in (("game_sim", "adapters", "hitclub.py"),
              ("services", "browser_service.py")):
        src = _code(*f)
        assert "token_store.save_for_account(" in src, f"{f[-1]} chưa ghi theo id"
        assert "token_store.save(" not in src, f"{f[-1]} còn ghi theo tên thô"


def test_duong_doc_tra_theo_account_khong_tra_khoa_chinh_xac():
    """`get()` tra khoá chính xác nên trượt khi kho có nhiều thế hệ khoá."""
    assert "find_for_account" in _code("game_sim", "adapters", "hitclub.py")
    assert "find_for_account" in _code("services", "browser_service.py")


def test_tiem_token_khong_con_phu_thuoc_web_storage():
    """Account MỚI chưa có web_storage là trường hợp CẦN token nhất.

    Trước đây cả khối tiêm nằm trong `if account.get("web_storage")` nên nó
    không bao giờ chạy cho account mới.
    """
    src = _src("services", "browser_service.py")
    assert 'if account and (account.get("web_storage") or fresh):' in src
    assert 'ws = account.get("web_storage") or {}' in src, "còn account['web_storage'] -> KeyError"


def test_endpoint_khong_nhan_ten_tho_tu_client():
    """Tên thô của client chảy xuống token_store.save() -> đẻ khoá username."""
    src = _src("controllers", "auto_flow_controller", "routes_basic.py")
    for ep in ('@router.post("/api/autoplay/start")',
               '@router.post("/api/autoplay/capture")'):
        khoi = src.split(ep, 1)[1][:1200]
        assert "resolve_profile_name(" in khoi, f"{ep} chưa chuẩn hoá tên profile"


def test_xoa_account_thi_xoa_token():
    src = _src("controllers", "account_controller.py")
    assert "clear_for_account" in src, "xoá profile mà bỏ token lại"
    khoi = src.split("async def _delete_accounts", 1)[1][:2000]
    assert "from models.config_model import DATA_DIR" in khoi, (
        "DATA_DIR phải import TRONG hàm — bind ở mức module thì test đụng file thật")


def test_migration_chay_khi_khoi_dong():
    src = _src("main.py")
    assert ".migrate(" in src and "game_sim_token" in src
