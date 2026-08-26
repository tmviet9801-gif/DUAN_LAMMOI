"""Model tính toán lưới cửa sổ trên màn hình."""
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
SPI_GETWORKAREA = 0x0030


def get_work_area():
    rect = wintypes.RECT()
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def compute_grid(n, cols, gap, margin, work_area, window_size=(0, 0), direction="row"):
    if n <= 0:
        return []
    x0, y0, sw, sh = work_area
    cols = max(1, int(cols))
    gap = max(0, int(gap))
    margin = max(0, int(margin))
    win_w, win_h = int(window_size[0] or 0), int(window_size[1] or 0)

    if win_w > 0 and win_h > 0:
        cell_w = min(win_w, sw - 2 * margin)
        cell_h = min(win_h, sh - 2 * margin)
        fit_cols = max(1, (sw - 2 * margin + gap) // (cell_w + gap))
        fit_rows = max(1, (sh - 2 * margin + gap) // (cell_h + gap))
        cols = min(cols, fit_cols)
        rows = min(fit_rows, (n + cols - 1) // cols)
    else:
        rows = (n + cols - 1) // cols
        cell_w = max(200, (sw - 2 * margin - (cols - 1) * gap) // cols)
        cell_h = max(150, (sh - 2 * margin - (rows - 1) * gap) // rows)

    rects = []
    for i in range(n):
        if direction == "col":
            c, r = divmod(i, rows)
        else:
            r, c = divmod(i, cols)
        x = x0 + margin + c * (cell_w + gap)
        y = y0 + margin + r * (cell_h + gap)
        rects.append((int(x), int(y), cell_w, cell_h))
    return rects
