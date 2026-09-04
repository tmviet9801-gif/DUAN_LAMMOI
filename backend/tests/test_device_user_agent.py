"""Unit test: kiểm tra cấp phát User-Agent đa dạng cho các Chrome Profile."""
from core.device_profiles import USER_AGENTS_POOL, assign_user_agent_if_empty, get_random_user_agent
from models.config_model import new_account_record


def test_random_user_agent_from_pool():
    ua = get_random_user_agent()
    assert ua in USER_AGENTS_POOL
    assert len(ua) > 20
    assert "Chrome" in ua


def test_assign_user_agent_to_multiple_accounts():
    accounts = [{"name": f"Acc_{i}", "user_agent": ""} for i in range(10)]
    for acc in accounts:
        assign_user_agent_if_empty(acc, accounts)

    # Đảm bảo tất cả đều có User-Agent
    for acc in accounts:
        assert acc["user_agent"] != ""
        assert acc["user_agent"] in USER_AGENTS_POOL

    # Đảm bảo phân tán đa dạng (không phải tất cả đều trùng 1 UA)
    unique_uas = set(acc["user_agent"] for acc in accounts)
    assert len(unique_uas) > 1, f"Cần có nhiều User-Agent khác nhau, hiện có: {unique_uas}"


def test_new_account_record_automatically_gets_user_agent():
    rec = new_account_record({"name": "Profile Test Device"})
    assert "user_agent" in rec
    assert rec["user_agent"] != ""
    assert rec["user_agent"] in USER_AGENTS_POOL


def test_existing_user_agent_is_preserved():
    custom_ua = "Mozilla/5.0 (CustomDeviceTest) Safari/537.36"
    rec = new_account_record({"name": "Profile Custom", "user_agent": custom_ua})
    assert rec["user_agent"] == custom_ua
