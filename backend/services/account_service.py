"""Service: nghiệp vụ tài khoản."""


def bulk_names(prefix: str, count: int) -> list[str]:
    """Sinh tên hàng loạt theo số thứ tự zero-padded.

    count=1  -> ["A"]
    count=10 -> ["A01", "A02", ..., "A10"]  (tránh lỗi sort A1, A10, A11...)
    count=100 -> ["A001", ...]
    """
    count = max(1, int(count))
    width = max(2, len(str(count)))
    prefix = (prefix or "").strip()
    if count == 1:
        return [prefix]
    return [f"{prefix}{str(i).zfill(width)}" for i in range(1, count + 1)]
