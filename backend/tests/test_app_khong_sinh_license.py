"""App chỉ NHẬP và KIỂM license — không còn đường nào tự sinh key.

Việc cấp license chuyển sang dự án quản trị riêng. Đây không chỉ là dọn giao
diện: chừng nào app còn tự ký được key thì ai unpack được exe cũng tự cấp key
vô hạn cho mình — đúng lỗ hổng mà bản Ed25519 sinh ra để bịt.

`lic.make_key` vẫn còn trong `backend/license.py` vì bộ kiểm thử dùng nó để
dựng key thử. Điều phải khoá là: KHÔNG có đường nào từ mạng hay từ giao diện
gọi tới nó.
"""
import re
from pathlib import Path

BE = Path(__file__).parents[1]
APP = BE.parent / "app" / "renderer"

CONTROLLER = BE / "controllers" / "license_controller.py"
INDEX = APP / "index.html"
LICENSE_JS = APP / "js" / "license.js"
MENU_JS = APP / "js" / "menu.js"


def _code(p: Path) -> str:
    """Chỉ lấy dòng CODE, bỏ cả khối `/** */` và `<!-- -->`.

    Chú thích giải thích việc đã bỏ có chứa đúng chuỗi đang cấm — bẫy này đã
    vấp nhiều lần trong repo.
    """
    src = p.read_text(encoding="utf-8")
    if p.suffix in (".js", ".html"):
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    mo = "#" if p.suffix == ".py" else "//"
    return "\n".join(d for d in src.splitlines() if not d.strip().startswith(mo))


# ---------- backend ----------

def test_khong_con_endpoint_sinh_key():
    code = _code(CONTROLLER)
    assert "/api/license/make" not in code
    assert "make_key" not in code
    assert "OWNER_TOKEN" not in code, "token chủ không còn nơi dùng"


def test_router_chi_con_bon_endpoint_kiem_license():
    import sys
    if str(BE) not in sys.path:
        sys.path.insert(0, str(BE))
    import controllers.license_controller as lc
    duong = {r.path for r in lc.router.routes}
    assert duong == {
        "/api/license/activate",
        "/api/license/deactivate",
        "/api/license/recheck",
        "/api/license/status",
    }, duong


def test_khong_route_nao_khac_goi_make_key():
    """Quét MỌI controller: không được có đường mạng nào chạm tới make_key."""
    pham = []
    for f in (BE / "controllers").rglob("*.py"):
        if "make_key" in _code(f):
            pham.append(str(f.relative_to(BE)))
    assert pham == [], f"còn đường sinh key: {pham}"


# ---------- giao diện ----------

def test_giao_dien_khong_con_muc_sinh_license():
    code = _code(INDEX)
    for cam in ("make-license", "makeLicenseModal", "mkGenerate", "mkOwnerToken"):
        assert cam not in code, f"giao diện còn `{cam}`"


def test_khong_con_ma_js_sinh_license():
    for f in (LICENSE_JS, MENU_JS):
        code = _code(f)
        for cam in ("openMakeLicense", "makeLicenseModal", "mkGenerate",
                    "/api/license/make"):
            assert cam not in code, f"{f.name} còn `{cam}`"


def test_khong_con_tham_chieu_mo_coi_trong_renderer():
    """Nút gọi một hàm đã xoá thì im lặng không làm gì — tệ hơn không có nút."""
    pham = []
    for f in APP.rglob("*.js"):
        code = _code(f)
        for cam in ("openMakeLicense", "mkOwnerToken", "mkMachineId", "mkKeyResult"):
            if cam in code:
                pham.append(f"{f.name}: {cam}")
    assert pham == [], pham


# ---------- phần PHẢI giữ lại ----------

def test_van_con_du_duong_nhap_va_kiem_license():
    """App vẫn phải: nhập key, xem mã máy, xem hạn còn lại và số profile."""
    code = _code(INDEX)
    for can in ("cfgLicenseKey", "btnSaveLicenseKey", "btnCopyMachineId",
                "cfgLicenseCard", "licenseGate"):
        assert can in code, f"mất đường nhập/kiểm license: `{can}`"


def test_trang_thai_license_van_bao_du_ba_thong_tin():
    """Mã máy, hạn còn lại, số profile mở được — ba thứ người dùng cần thấy."""
    code = _code(BE / "license.py")
    for can in ("machine_id", "expiry", "max_tabs"):
        assert can in code, f"thiếu trường `{can}` trong thông tin license"
