"""Kiểm tra bản build trước khi gửi cho khách.

    python tools/kiem_tra_ban_phat_hanh.py            # kiểm tra cấu hình nguồn
    python tools/kiem_tra_ban_phat_hanh.py --dist     # quét luôn file đã build

Vì sao cần: app chạy trên máy khách thì mọi chuỗi nằm trong file exe đều đọc
được. Mã hoá chuỗi không cứu được gì — app phải giải mã để dùng, nên khoá giải
mã cũng nằm ngay đó. Cách chắc chắn duy nhất là bản gửi khách KHÔNG chứa bí mật
nào cả. Script này soát đúng điều đó.
"""
import argparse
import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# Chuỗi tuyệt đối không được có mặt trong bản gửi khách.
BI_MAT_CAM = [
    ("AutoToolLicenseSecret", "SECRET của scheme HMAC đời cũ"),
    ("AutoToolOwner@", "token chủ sở hữu (mở panel tự sinh key)"),
    ("BEGIN PRIVATE KEY", "khoá riêng dạng PEM"),
    ("MC4CAQAwBQYDK2Vw", "khoá riêng Ed25519 dạng PKCS8 base64"),
]

loi = []
canh_bao = []


def bao_loi(msg):
    loi.append(msg)
    print(f"  [LOI]  {msg}")


def bao_canh_bao(msg):
    canh_bao.append(msg)
    print(f"  [!]    {msg}")


def bao_ok(msg):
    print(f"  [ok]   {msg}")


def kiem_tra_cau_hinh():
    print("\n== Cấu hình phát hành ==")
    import platform_config as pc

    if pc.ALLOW_LEGACY_HMAC:
        bao_loi(
            "ALLOW_LEGACY_HMAC vẫn True. Bật cờ này là Ed25519 mất tác dụng bảo vệ: "
            "key HMAC ký bằng khoá đối xứng lại được chấp nhận."
        )
    else:
        bao_ok("ALLOW_LEGACY_HMAC = False (chỉ nhận key Ed25519)")

    if not pc.LICENSE_PUBLIC_KEY:
        bao_loi("Chưa có LICENSE_PUBLIC_KEY — app sẽ từ chối mọi key Ed25519")
    elif len(pc.LICENSE_PUBLIC_KEY) < 40:
        bao_loi(f"LICENSE_PUBLIC_KEY trông không đúng: {pc.LICENSE_PUBLIC_KEY!r}")
    else:
        bao_ok(f"LICENSE_PUBLIC_KEY đã đặt ({pc.LICENSE_PUBLIC_KEY[:12]}...)")

    if not pc.LICENSE_SERVER_URL:
        bao_canh_bao(
            "Chưa có LICENSE_SERVER_URL — thu hồi license sẽ không có tác dụng, "
            "vì app không hỏi lại máy chủ"
        )
    elif not pc.LICENSE_SERVER_URL.startswith("https://"):
        bao_loi(f"LICENSE_SERVER_URL phải dùng https: {pc.LICENSE_SERVER_URL}")
    else:
        bao_ok(f"LICENSE_SERVER_URL = {pc.LICENSE_SERVER_URL}")

    if pc.OWNER_TOKEN:
        bao_loi(
            "OWNER_TOKEN đang có giá trị — panel tự sinh key trong app sẽ mở. "
            "Bỏ biến môi trường AUTOTOOL_OWNER_TOKEN trước khi build."
        )
    else:
        bao_ok("OWNER_TOKEN rỗng (panel tự sinh key đã tắt)")

    if os.environ.get("AUTOTOOL_LEGACY_SECRET"):
        bao_loi(
            "Biến môi trường AUTOTOOL_LEGACY_SECRET đang được đặt. "
            "PyInstaller không đóng gói biến môi trường, nhưng đừng build trong "
            "shell có nó để tránh nhầm lẫn khi thử."
        )
    else:
        bao_ok("AUTOTOOL_LEGACY_SECRET không được đặt")


def kiem_tra_ma_nguon():
    print("\n== Mã nguồn ==")
    sach = True
    for path in BACKEND.rglob("*.py"):
        if ".venv" in path.parts or "tests" in path.parts or path.name == Path(__file__).name:
            continue
        try:
            noi_dung = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for chuoi, mo_ta in BI_MAT_CAM:
            if chuoi in noi_dung:
                bao_loi(f"{path.relative_to(BACKEND)} có {mo_ta}: {chuoi!r}")
                sach = False
    if sach:
        bao_ok("Không có bí mật nào hardcode trong mã nguồn")


def kiem_tra_file_build():
    """Quét nhị phân đã build — đây mới là thứ khách thực sự nhận được."""
    print("\n== File đã build ==")
    thu_muc = [BACKEND / "dist", BACKEND.parent / "app" / "release"]
    da_quet = 0

    for goc in thu_muc:
        if not goc.exists():
            continue
        for path in goc.rglob("*"):
            if not path.is_file() or path.stat().st_size > 300 * 1024 * 1024:
                continue
            if path.suffix.lower() not in (".exe", ".dll", ".pyd", ".asar", ".js", ".py", ""):
                continue
            try:
                du_lieu = path.read_bytes()
            except Exception:
                continue
            da_quet += 1
            for chuoi, mo_ta in BI_MAT_CAM:
                if chuoi.encode() in du_lieu:
                    bao_loi(f"{path.name} chứa {mo_ta}: {chuoi!r}")

    if not da_quet:
        bao_canh_bao("Chưa có file build nào để quét (chạy build.ps1 trước)")
    else:
        print(f"  Đã quét {da_quet} file.")
        if not loi:
            bao_ok("Không tìm thấy bí mật nào trong file build")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", action="store_true", help="quét cả file đã build")
    args = ap.parse_args()

    print("=" * 62)
    print("  KIỂM TRA BẢN PHÁT HÀNH")
    print("=" * 62)

    kiem_tra_cau_hinh()
    kiem_tra_ma_nguon()
    if args.dist:
        kiem_tra_file_build()

    print("\n" + "=" * 62)
    if loi:
        print(f"  KHÔNG ĐƯỢC PHÁT HÀNH — {len(loi)} lỗi cần sửa")
        print("=" * 62)
        return 1
    if canh_bao:
        print(f"  Phát hành được, nhưng có {len(canh_bao)} cảnh báo nên xem lại")
        print("=" * 62)
        return 0
    print("  Sẵn sàng phát hành")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
