from models.window_layout_model import compute_grid

WORK_AREA = (0, 0, 1920, 1080)


def test_2_windows_row():
    rects = compute_grid(2, 5, 8, 4, WORK_AREA)
    assert len(rects) == 2
    x1, y1, w1, h1 = rects[0]
    x2, y2, w2, h2 = rects[1]
    assert y1 == y2
    assert x2 > x1
    assert w1 > 0
    assert h1 > 0


def test_2_windows_col():
    rects = compute_grid(6, 2, 8, 4, WORK_AREA, direction="col")
    assert len(rects) == 6
    x_col0 = {rects[i][0] for i in range(3)}
    x_col1 = {rects[i][0] for i in range(3, 6)}
    assert len(x_col0) == 1
    assert len(x_col1) == 1
    assert list(x_col1)[0] > list(x_col0)[0]


def test_10_windows_fills_grid():
    n = 10
    rects = compute_grid(n, 5, 8, 4, WORK_AREA)
    assert len(rects) == n
    xs = [r[0] for r in rects]
    ys = [r[1] for r in rects]
    assert max(xs) < 1920
    assert max(ys) < 1080


def test_fixed_window_size():
    rects = compute_grid(2, 5, 8, 4, WORK_AREA, window_size=(800, 600))
    for _, _, w, h in rects:
        assert w <= 800
        assert h <= 600


def test_zero_count():
    assert compute_grid(0, 5, 8, 4, WORK_AREA) == []


def test_margin_gap_respected():
    rects = compute_grid(2, 5, 100, 50, WORK_AREA)
    x1, y1, w1, h1 = rects[0]
    x2, y2, w2, h2 = rects[1]
    assert x1 >= 50
    assert y1 >= 50
    assert x2 - x1 - w1 >= 100