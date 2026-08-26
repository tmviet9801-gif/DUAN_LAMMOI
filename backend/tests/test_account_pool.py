from game_sim.account_pool import AccountPool


def test_round_robin_rotation():
    pool = AccountPool({"A": {"main": "A", "supports": ["A1", "A2", "A3"]}})
    got = [pool.next_support("A") for _ in range(3)]
    assert got == ["A1", "A2", "A3"]


def test_skips_busy():
    pool = AccountPool({"A": {"main": "A", "supports": ["A1", "A2"]}})
    pool.mark_busy("A1", "A")
    assert pool.next_support("A") == "A2"
    # A2 giờ busy, A1 vẫn busy -> pool exhausted
    assert pool.next_support("A") is None


def test_cooldown_skips_then_available():
    pool = AccountPool({"A": {"main": "A", "supports": ["A1", "A2"]}})
    pool.release("A1", cooldown_s=100)
    assert pool.next_support("A") == "A2"  # A2 free
    assert pool.next_support("A") is None  # A2 busy, A1 cooldown


def test_exclude_main():
    pool = AccountPool({"A": {"main": "A", "supports": ["A1", "A2"]}})
    # exclude A1 -> A2
    assert pool.next_support("A", exclude=["A1"]) == "A2"


def test_pool_exhausted_returns_none():
    pool = AccountPool({"A": {"main": "A", "supports": []}})
    assert pool.next_support("A") is None


def test_unknown_group_none():
    pool = AccountPool({"A": {"main": "A", "supports": ["A1"]}})
    assert pool.next_support("ZZZ") is None
