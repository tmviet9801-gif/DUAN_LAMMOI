"""Helper thời gian.

Cung cấp hàm lấy timestamp hiện tại, Stopwatch đo thời gian chạy.
"""
import time
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat()


def now_ms() -> int:
    return int(time.time() * 1000)


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


class Stopwatch:
    """Đo elapsed time. Dùng `with Stopwatch() as sw` để tự động in kết quả."""

    def __init__(self, label: str = ""):
        self.label = label
        self.start = time.perf_counter()

    def elapsed(self) -> float:
        return time.perf_counter() - self.start

    def elapsed_ms(self) -> int:
        return int(self.elapsed() * 1000)

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args):
        pass