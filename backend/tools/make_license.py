"""Sinh license key cho khách (owner).

Cách dùng:
    python tools/make_license.py --machine-id <MachineGuid> --days 30 --max-tabs 10
    python tools/make_license.py --days 30 --max-tabs 10   # tự lấy machine id máy này

Lấy MachineGuid của máy khách: chạy trên máy khách
    python tools/make_license.py --print-id
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import license as lic  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Sinh license AutoTool")
    ap.add_argument("--machine-id", default=None, help="MachineGuid của máy khách (mặc định: máy này)")
    ap.add_argument("--days", type=int, default=30, help="Số ngày hiệu lực")
    ap.add_argument("--max-tabs", type=int, default=10, help="Giới hạn số tab")
    ap.add_argument("--features", default="game", help="Features (game)")
    ap.add_argument("--print-id", action="store_true", help="Chỉ in MachineGuid")
    args = ap.parse_args()

    if args.print_id:
        print(lic.get_machine_id())
        return

    machine_id = args.machine_id or lic.get_machine_id()
    key = lic.make_key(machine_id, args.days, args.max_tabs, args.features)
    print(f"Machine: {machine_id}")
    print(f"Key    : {key}")
    # verify
    v = lic.validate_key(key, machine_id)
    print(f"Verify : {'OK' if v['valid'] else v}")


if __name__ == "__main__":
    main()
