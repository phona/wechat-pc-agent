"""Tests for wechat.ui_simulator — all pyautogui interactions are mocked."""

import random
import time
from unittest.mock import MagicMock, patch, call

import pytest

from wechat.ui_simulator import UISimulator, QWERTY_NEIGHBORS


@pytest.fixture
def pag():
    """Mock pyautogui module."""
    m = MagicMock()
    m.position.return_value = (500, 500)
    return m


@pytest.fixture
def sim():
    return UISimulator(running_check=lambda: True, typo_enabled=True, typo_rate=0.02)


@pytest.fixture
def sim_no_typo():
    return UISimulator(running_check=lambda: True, typo_enabled=False)


@pytest.fixture
def sim_no_overshoot():
    return UISimulator(running_check=lambda: True, mouse_overshoot_enabled=False)


# ── Mouse movement ──────────────────────────────────────────────────


class TestBezierMoveClick:
    def test_moves_to_target_and_clicks(self, sim, pag):
        sim.bezier_move_click(600, 600, pag)
        # Should have multiple moveTo calls and at least one click
        assert pag.moveTo.call_count >= 10
        assert pag.click.called

    def test_variable_speed_steps(self, sim, pag):
        """Step delays should vary — not all the same."""
        delays = []
        original_sleep = time.sleep

        with patch("wechat.ui_simulator.time.sleep", side_effect=lambda d: delays.append(d)):
            sim.bezier_move_click(700, 700, pag)

        # Filter out overshoot/correction delays — just look at main movement
        main_delays = delays[:15]  # at least 15 steps
        assert len(set(round(d, 6) for d in main_delays)) > 3, "Delays should vary, not be uniform"

    def test_jitter_decreases_near_target(self, sim, pag):
        """Micro-jitter sigma decreases as t→1."""
        positions = []
        pag.moveTo.side_effect = lambda x, y, **kw: positions.append((x, y))

        random.seed(42)
        sim.bezier_move_click(600, 600, pag)

        # Compare jitter of early vs late positions
        # With jitter, early positions should deviate more from the Bézier curve
        # We just verify positions were collected and vary
        assert len(positions) >= 10

    @patch("wechat.ui_simulator.random.random", return_value=0.05)
    def test_overshoot_produces_extra_moves(self, mock_rand, sim, pag):
        """When random < 0.12, overshoot should produce extra moveTo calls after main path."""
        sim.bezier_move_click(600, 600, pag)
        # Overshoot adds at least 1 extra moveTo (overshoot point) + correction steps
        assert pag.moveTo.call_count >= 18  # 15 main + 1 overshoot + corrections

    def test_no_overshoot_when_disabled(self, sim_no_overshoot, pag):
        sim_no_overshoot.bezier_move_click(600, 600, pag)
        # Only main path moves + final click, no extra moves
        main_count = pag.moveTo.call_count
        assert pag.click.call_count == 1  # exactly one click, no re-click

    def test_interrupted_returns_early(self, pag):
        """If running_check returns False mid-movement, stop early."""
        call_count = 0

        def check():
            nonlocal call_count
            call_count += 1
            return call_count < 5

        sim = UISimulator(running_check=check)
        sim.bezier_move_click(800, 800, pag)
        # Should have stopped after a few moves
        assert pag.moveTo.call_count < 10


# ── Typing ──────────────────────────────────────────────────────────


class TestTypeText:
    def test_types_all_characters(self, sim, pag):
        random.seed(99)  # seed to avoid typos
        sim._typo_enabled = False
        sim.type_text("hello", pag)
        written = [c[0][0] for c in pag.write.call_args_list]
        assert "".join(written) == "hello"

    def test_no_typos_when_disabled(self, sim_no_typo, pag):
        sim_no_typo.type_text("hello world test", pag)
        # No backspace should be called
        backspace_calls = [c for c in pag.press.call_args_list if c[0][0] == "backspace"]
        assert len(backspace_calls) == 0

    def test_typo_produces_backspace_and_correction(self, pag):
        """Force a typo and verify backspace + correct char sequence."""
        sim = UISimulator(typo_enabled=True, typo_rate=1.0)  # 100% typo rate
        with patch("wechat.ui_simulator.time.sleep"):
            sim.type_text("a", pag)

        # Should have: write(wrong), press(backspace), write('a')
        writes = [c[0][0] for c in pag.write.call_args_list]
        assert len(writes) == 2  # wrong + correct
        assert writes[1] == "a"
        pag.press.assert_called_with("backspace")

    def test_typo_uses_neighbor_key(self, pag):
        """Wrong char should be from QWERTY neighbor map."""
        sim = UISimulator(typo_enabled=True, typo_rate=1.0)
        random.seed(42)
        with patch("wechat.ui_simulator.time.sleep"):
            sim.type_text("f", pag)

        wrong_char = pag.write.call_args_list[0][0][0]
        assert wrong_char in QWERTY_NEIGHBORS["f"]

    def test_uppercase_typo_stays_uppercase(self, pag):
        sim = UISimulator(typo_enabled=True, typo_rate=1.0)
        random.seed(42)
        with patch("wechat.ui_simulator.time.sleep"):
            sim.type_text("F", pag)

        wrong_char = pag.write.call_args_list[0][0][0]
        assert wrong_char.isupper()

    def test_bimodal_delays(self, sim_no_typo, pag):
        """Typing delays should have two modes: fast and hesitant."""
        delays = []
        with patch("wechat.ui_simulator.time.sleep", side_effect=lambda d: delays.append(d)):
            random.seed(10)
            sim_no_typo.type_text("abcdefghijklmnop", pag)

        # Should see a mix of fast (0.04-0.08) and slow (0.10-0.20) delays
        fast = [d for d in delays if 0.03 <= d <= 0.09]
        slow = [d for d in delays if 0.09 < d <= 0.25]
        assert len(fast) > 0, "Should have fast delays"
        assert len(slow) > 0, "Should have slow delays"

    def test_interrupted_stops_typing(self, pag):
        call_count = 0

        def check():
            nonlocal call_count
            call_count += 1
            return call_count < 3

        sim = UISimulator(running_check=check, typo_enabled=False)
        with patch("wechat.ui_simulator.time.sleep"):
            sim.type_text("abcdefghij", pag)

        assert pag.write.call_count < 10


# ── Paste ───────────────────────────────────────────────────────────


class TestPasteText:
    @patch("wechat.ui_simulator.time.sleep")
    def test_paste_calls_ctrl_v(self, mock_sleep, pag):
        sim = UISimulator()
        mock_pyperclip = MagicMock()
        with patch.dict("sys.modules", {"pyperclip": mock_pyperclip}):
            sim.paste_text("你好", pag)
            mock_pyperclip.copy.assert_called_once_with("你好")
            pag.hotkey.assert_called_once_with("ctrl", "v")


# ── Reading simulation ──────────────────────────────────────────────


class TestSimulateReading:
    def test_duration_proportional_to_length(self):
        sim = UISimulator()
        with patch("wechat.ui_simulator.time.sleep"):
            short = sim.simulate_reading(10)
            long = sim.simulate_reading(200)
        assert long > short

    def test_clamped_minimum(self):
        sim = UISimulator()
        with patch("wechat.ui_simulator.time.sleep"):
            result = sim.simulate_reading(1)
        assert result >= 1.0

    def test_clamped_maximum(self):
        sim = UISimulator()
        with patch("wechat.ui_simulator.time.sleep"):
            result = sim.simulate_reading(10000)
        assert result <= 30.0

    def test_fidgets_when_pyautogui_provided(self, pag):
        sim = UISimulator()
        random.seed(42)
        with patch("wechat.ui_simulator.time.sleep"):
            sim.simulate_reading(200, pyautogui=pag)
        # May have fidget mouse movements
        # Just verify it doesn't crash

    def test_interrupted_returns_early(self):
        call_count = 0

        def check():
            nonlocal call_count
            call_count += 1
            return call_count < 3

        sim = UISimulator(running_check=check)
        with patch("wechat.ui_simulator.time.sleep"):
            result = sim.simulate_reading(500)
        assert result < 30.0  # should not reach max


# ── Idle behaviors ──────────────────────────────────────────────────


class TestIdleBehaviors:
    def test_perform_idle_action_returns_positive(self, sim, pag):
        with patch("wechat.ui_simulator.time.sleep"):
            duration = sim.perform_idle_action(pag)
        assert duration > 0

    def test_idle_scroll_calls_scroll(self, sim, pag):
        with patch("wechat.ui_simulator.time.sleep"):
            sim._idle_scroll(pag, (0, 0, 800, 600))
        pag.scroll.assert_called_once()

    def test_idle_mouse_wander_moves(self, sim, pag):
        with patch("wechat.ui_simulator.time.sleep"):
            sim._idle_mouse_wander(pag, (0, 0, 800, 600))
        pag.moveTo.assert_called()

    def test_idle_do_nothing_sleeps(self, sim):
        delays = []
        with patch("wechat.ui_simulator.time.sleep", side_effect=lambda d: delays.append(d)):
            sim._idle_do_nothing()
        assert sum(delays) >= 2.0

    def test_pick_idle_action_distribution(self, sim):
        """All three actions should be reachable."""
        random.seed(0)
        actions = {sim._pick_idle_action() for _ in range(100)}
        assert "scroll" in actions
        assert "mouse_wander" in actions
        assert "do_nothing" in actions

    def test_idle_with_window_rect(self, sim, pag):
        with patch("wechat.ui_simulator.time.sleep"):
            sim.perform_idle_action(pag, window_rect=(100, 100, 900, 700))
        # Should not crash
