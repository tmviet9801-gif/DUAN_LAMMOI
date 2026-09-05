import pytest
from unittest.mock import AsyncMock, MagicMock
from core.card_strategy import HandDecomposition, CooperativeDiscardEngine, CANVAS_BTNS

def test_hand_decomposition_trajectory_validity():
    traj = HandDecomposition.get_discard_trajectory()
    assert len(traj) >= 8
    # Tất cả các tọa độ X phải nằm trong khoảng hợp lệ dải bài [0.200, 0.860]
    for x in traj:
        assert 0.200 <= x <= 0.860
    # Phải đi từ lá to (bên phải) về lá nhỏ (bên trái)
    assert traj[0] > traj[-1]
    assert traj[0] >= 0.700
    assert traj[-1] <= 0.300

def test_theoretical_savings_calculation():
    bet = 100000
    savings = HandDecomposition.compute_theoretical_savings(bet=bet, rake_rate=0.02)
    assert savings["bet"] == 100000
    assert savings["loss_optimal"] == 100000  # Acc 2 chỉ thua đúng 1 lá
    assert savings["rake_optimal"] == 2000    # Phế chỉ 2% của 1 cược
    assert savings["loss_normal"] == 1000000  # Thường thua 10 lá
    assert savings["rake_normal"] == 20000
    assert savings["savings_percent"] >= 90.0
    assert savings["savings_rake_vnd"] == 18000

@pytest.mark.anyio
async def test_cooperative_engine_turn_detection_sub_first():
    mock_anchor = MagicMock()
    mock_sub = MagicMock()

    engine = CooperativeDiscardEngine(mock_anchor, mock_sub, "Acc1", "Acc2")
    
    # Giả lập: Sub có lượt đánh trước (check_turn_active trả về True)
    engine.check_turn_active = AsyncMock(side_effect=[True, False])
    first_turn = await engine.detect_first_turn(max_seconds=1.0)
    assert first_turn == "SUB_FIRST"

@pytest.mark.anyio
async def test_cooperative_engine_turn_detection_main_first():
    mock_anchor = MagicMock()
    mock_sub = MagicMock()

    engine = CooperativeDiscardEngine(mock_anchor, mock_sub, "Acc1", "Acc2")
    
    # Giả lập: Main có lượt đánh trước
    engine.check_turn_active = AsyncMock(side_effect=[False, True])
    first_turn = await engine.detect_first_turn(max_seconds=1.0)
    assert first_turn == "MAIN_FIRST"

@pytest.mark.anyio
async def test_cooperative_engine_optimal_discard_execution():
    mock_anchor = MagicMock()
    mock_anchor.mouse.click = AsyncMock()
    mock_anchor.screenshot = AsyncMock(return_value=b"fake")
    mock_anchor.evaluate = AsyncMock(return_value={"w": 784, "h": 505})

    mock_sub = MagicMock()
    mock_sub.mouse.click = AsyncMock()
    mock_sub.screenshot = AsyncMock(return_value=b"fake")
    mock_sub.evaluate = AsyncMock(return_value={"w": 784, "h": 505})

    engine = CooperativeDiscardEngine(mock_anchor, mock_sub, "Acc1", "Acc2")
    engine.detect_first_turn = AsyncMock(return_value="SUB_FIRST")
    engine._is_game_ended = AsyncMock(side_effect=[False, False, True])

    success = await engine.execute_optimal_discard()
    assert success is True
    # Anchor và Sub đều được gọi click chuột để đánh bài và bỏ lượt
    assert mock_anchor.mouse.click.call_count >= 2
    assert mock_sub.mouse.click.call_count >= 2
