"""UI simulation primitives for human-like mouse, keyboard, and idle behaviors."""

import logging
import math
import random
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# QWERTY neighbor map for typo simulation (lowercase only)
QWERTY_NEIGHBORS = {
    "q": "wa", "w": "qeas", "e": "wrds", "r": "etfd", "t": "rygf",
    "y": "tuhg", "u": "yijh", "i": "uokj", "o": "iplk", "p": "ol",
    "a": "qwsz", "s": "awedxz", "d": "serfcx", "f": "drtgvc",
    "g": "ftyhbv", "h": "gyujnb", "j": "huikmn", "k": "jiolm",
    "l": "kop", "z": "asx", "x": "zsdc", "c": "xdfv",
    "v": "cfgb", "b": "vghn", "n": "bhjm", "m": "njk",
}


class UISimulator:
    """Consolidates all pyautogui-based UI simulation with human-like behaviors.

    All pyautogui/pyperclip imports are deferred to method calls so the module
    can be imported and tested on non-Windows systems.
    """

    def __init__(
        self,
        running_check: Optional[Callable[[], bool]] = None,
        typo_enabled: bool = True,
        typo_rate: float = 0.02,
        mouse_overshoot_enabled: bool = True,
    ):
        self._running_check = running_check or (lambda: True)
        self._typo_enabled = typo_enabled
        self._typo_rate = typo_rate
        self._mouse_overshoot_enabled = mouse_overshoot_enabled

    def _is_running(self) -> bool:
        return self._running_check()

    # ── Mouse movement ──────────────────────────────────────────────

    def _step_delay(self, t: float, base: float) -> float:
        """Ease-in-ease-out delay. Slow at start/end, fast in middle."""
        speed = 0.3 + 2.8 * math.sin(math.pi * t) ** 0.6
        return base / speed

    def bezier_move_click(self, x: int, y: int, pyautogui) -> None:
        """Move mouse along a cubic Bézier curve to (x, y) with human-like
        speed variation, micro-jitter, and optional overshoot, then click."""
        start_x, start_y = pyautogui.position()
        dx = x - start_x
        dy = y - start_y
        distance = math.hypot(dx, dy)
        steps = max(15, int(distance / 4))
        base_delay = random.uniform(0.004, 0.010)

        # Perpendicular direction for control point offsets
        perp_x, perp_y = -dy, dx
        norm = math.hypot(perp_x, perp_y) or 1.0
        perp_x, perp_y = perp_x / norm, perp_y / norm

        offset1 = random.gauss(0, 30)
        offset2 = random.gauss(0, 30)
        cp1_x = start_x + dx * 0.33 + perp_x * offset1
        cp1_y = start_y + dy * 0.33 + perp_y * offset1
        cp2_x = start_x + dx * 0.66 + perp_x * offset2
        cp2_y = start_y + dy * 0.66 + perp_y * offset2

        for i in range(1, steps + 1):
            if not self._is_running():
                return
            t = i / steps
            inv = 1 - t
            # Cubic Bézier
            bx = inv**3 * start_x + 3 * inv**2 * t * cp1_x + 3 * inv * t**2 * cp2_x + t**3 * x
            by = inv**3 * start_y + 3 * inv**2 * t * cp1_y + 3 * inv * t**2 * cp2_y + t**3 * y

            # Micro-jitter: decreases near target
            jitter_sigma = max(0.3, 1.5 * (1 - t))
            jx = bx + random.gauss(0, jitter_sigma)
            jy = by + random.gauss(0, jitter_sigma)

            pyautogui.moveTo(int(jx), int(jy), _pause=False)
            time.sleep(self._step_delay(t, base_delay))

        # Overshoot: 12% chance
        if self._mouse_overshoot_enabled and random.random() < 0.12:
            angle = random.uniform(0, 2 * math.pi)
            overshoot_dist = random.uniform(3, 12)
            ox = int(x + overshoot_dist * math.cos(angle))
            oy = int(y + overshoot_dist * math.sin(angle))
            pyautogui.moveTo(ox, oy, _pause=False)
            time.sleep(random.uniform(0.05, 0.15))
            # Correct back
            correction_steps = random.randint(3, 6)
            for i in range(1, correction_steps + 1):
                t = i / correction_steps
                cx = int(ox + (x - ox) * t)
                cy = int(oy + (y - oy) * t)
                pyautogui.moveTo(cx, cy, _pause=False)
                time.sleep(random.uniform(0.005, 0.015))

        # Slight miss: 4% chance
        if self._mouse_overshoot_enabled and random.random() < 0.04:
            miss_offset = random.uniform(5, 15)
            miss_angle = random.uniform(0, 2 * math.pi)
            mx = int(x + miss_offset * math.cos(miss_angle))
            my = int(y + miss_offset * math.sin(miss_angle))
            pyautogui.click(mx, my)
            time.sleep(random.uniform(0.2, 0.4))
            # Re-click correct position
            pyautogui.click(x, y)
        else:
            pyautogui.click(x, y)

    # ── Typing ──────────────────────────────────────────────────────

    def type_text(self, text: str, pyautogui) -> None:
        """Type ASCII text character by character with bimodal delays,
        thinking pauses, and optional typo simulation."""
        chars_since_pause = 0
        for char in text:
            if not self._is_running():
                return

            # Typo simulation (ASCII letters only)
            if (
                self._typo_enabled
                and char.lower() in QWERTY_NEIGHBORS
                and random.random() < self._effective_typo_rate(chars_since_pause)
            ):
                self._do_typo(char, pyautogui)
                chars_since_pause = 0
                continue

            pyautogui.write(char)
            chars_since_pause += 1

            # Post-punctuation pause
            if char in ".!?," and random.random() < 0.5:
                time.sleep(random.uniform(0.1, 0.4))
            # Thinking pause (4%)
            elif random.random() < 0.04:
                time.sleep(random.uniform(0.3, 1.2))
            else:
                # Bimodal delay: 70% fast, 30% hesitant
                if random.random() < 0.7:
                    time.sleep(random.uniform(0.04, 0.08))
                else:
                    time.sleep(random.uniform(0.10, 0.20))

    def _effective_typo_rate(self, chars_since_pause: int) -> float:
        """Typo rate increases with consecutive fast typing (fatigue)."""
        return self._typo_rate + 0.005 * (chars_since_pause // 50)

    def _do_typo(self, correct_char: str, pyautogui) -> None:
        """Type a wrong neighbor char, notice, backspace, retype correctly."""
        neighbors = QWERTY_NEIGHBORS.get(correct_char.lower(), "")
        if not neighbors:
            pyautogui.write(correct_char)
            return

        wrong = random.choice(neighbors)
        if correct_char.isupper():
            wrong = wrong.upper()

        pyautogui.write(wrong)
        time.sleep(random.uniform(0.1, 0.3))  # notice the error
        pyautogui.press("backspace")
        time.sleep(random.uniform(0.05, 0.15))
        pyautogui.write(correct_char)

    def paste_text(self, text: str, pyautogui) -> None:
        """Paste text via clipboard (for CJK / non-ASCII)."""
        import pyperclip

        pyperclip.copy(text)
        time.sleep(random.uniform(0.05, 0.2))
        pyautogui.hotkey("ctrl", "v")
        time.sleep(random.uniform(0.1, 0.3))

    # ── Reading simulation ──────────────────────────────────────────

    def simulate_reading(self, msg_length: int, pyautogui=None) -> float:
        """Simulate reading an incoming message. Returns total seconds spent.

        Optionally performs micro mouse movements if pyautogui is provided.
        """
        read_time = msg_length * random.uniform(0.04, 0.08)
        read_time = max(1.0, min(30.0, read_time))

        # Split into chunks with optional mouse fidgets
        fidgets = random.randint(0, 2) if pyautogui else 0
        fidget_times = sorted(random.uniform(0, read_time) for _ in range(fidgets))

        elapsed = 0.0
        fidget_idx = 0
        chunk = 0.5  # check every 0.5s

        while elapsed < read_time:
            if not self._is_running():
                return elapsed
            sleep_time = min(chunk, read_time - elapsed)
            time.sleep(sleep_time)
            elapsed += sleep_time

            # Perform fidget if it's time
            if pyautogui and fidget_idx < len(fidget_times) and elapsed >= fidget_times[fidget_idx]:
                try:
                    cx, cy = pyautogui.position()
                    fx = cx + random.randint(-50, 50)
                    fy = cy + random.randint(-50, 50)
                    pyautogui.moveTo(fx, fy, duration=random.uniform(0.1, 0.3), _pause=False)
                except Exception:
                    pass
                fidget_idx += 1

        return elapsed

    # ── Idle behaviors ──────────────────────────────────────────────

    def perform_idle_action(self, pyautogui, window_rect: Optional[tuple] = None) -> float:
        """Perform a random idle action. Returns seconds consumed."""
        action = self._pick_idle_action()

        if action == "scroll":
            return self._idle_scroll(pyautogui, window_rect)
        elif action == "mouse_wander":
            return self._idle_mouse_wander(pyautogui, window_rect)
        else:  # do_nothing
            return self._idle_do_nothing()

    def _pick_idle_action(self) -> str:
        actions = [("scroll", 4), ("mouse_wander", 3), ("do_nothing", 5)]
        total = sum(w for _, w in actions)
        r = random.uniform(0, total)
        cumulative = 0
        for action, weight in actions:
            cumulative += weight
            if r <= cumulative:
                return action
        return "do_nothing"

    def _idle_scroll(self, pyautogui, window_rect: Optional[tuple]) -> float:
        """Scroll within the chat area."""
        if not self._is_running():
            return 0.0
        try:
            if window_rect:
                left, top, right, bottom = window_rect
                # Move to chat area (upper-center)
                sx = (left + right) // 2
                sy = top + (bottom - top) // 3
                pyautogui.moveTo(sx, sy, duration=0.3, _pause=False)
            scroll_amount = random.choice([-3, -2, -1, 1, 2, 3])
            pyautogui.scroll(scroll_amount)
        except Exception:
            pass
        pause = random.uniform(1.0, 4.0)
        time.sleep(pause)
        return pause + 0.3

    def _idle_mouse_wander(self, pyautogui, window_rect: Optional[tuple]) -> float:
        """Move mouse to a random spot within the window."""
        if not self._is_running():
            return 0.0
        try:
            if window_rect:
                left, top, right, bottom = window_rect
                wx = random.randint(left + 20, right - 20)
                wy = random.randint(top + 20, bottom - 20)
            else:
                cx, cy = pyautogui.position()
                wx = cx + random.randint(-200, 200)
                wy = cy + random.randint(-200, 200)
            pyautogui.moveTo(wx, wy, duration=random.uniform(0.3, 0.8), _pause=False)
        except Exception:
            pass
        pause = random.uniform(0.5, 2.0)
        time.sleep(pause)
        return pause + 0.5

    def _idle_do_nothing(self) -> float:
        """Just wait — user staring at screen or looking away."""
        pause = random.uniform(2.0, 8.0)
        waited = 0.0
        while waited < pause and self._is_running():
            chunk = min(1.0, pause - waited)
            time.sleep(chunk)
            waited += chunk
        return waited
