"""Cấu hình logging tập trung cho toàn backend.

Mọi module dùng `logging.getLogger(__name__)` và chỉ gọi `setup_logging()`
một lần ở entry point (main.py) để format thống nhất.
"""
import logging

_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        logging.basicConfig(
            level=level,
            format="%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        _CONFIGURED = True
    return logging.getLogger("app")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
