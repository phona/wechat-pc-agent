"""Learn and sample human-like timing from WeChat message history."""

import json
import logging
import math
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class HumanTiming:
    """Learn timing distributions from real message history and sample delays."""

    def __init__(self, profile_path: str = ""):
        self._profile_path = profile_path
        self._profile: dict = {}

    def learn(self, db_reader, months: int = 3) -> None:
        """Analyze message history and fit timing distributions.

        Args:
            db_reader: A DBReader instance for querying the MSG database.
            months: How many months of history to analyze.
        """
        since = int(time.time()) - months * 30 * 86400
        messages = db_reader.get_messages_since(since, limit=50000)
        if not messages:
            logger.warning("No messages found for learning")
            return

        # Group by talker
        by_talker: dict[str, list] = {}
        for msg in messages:
            by_talker.setdefault(msg.talker, []).append(msg)

        reply_delays: list[float] = []
        typing_speeds: list[float] = []
        active_hours: list[int] = [0] * 24

        for talker, msgs in by_talker.items():
            msgs.sort(key=lambda m: m.create_time)
            for i in range(1, len(msgs)):
                prev, curr = msgs[i - 1], msgs[i]
                # Count outgoing messages for active hours
                if curr.is_sender:
                    hour = datetime.fromtimestamp(curr.create_time).hour
                    active_hours[hour] += 1

                # Reply delay: incoming followed by outgoing
                if not prev.is_sender and curr.is_sender:
                    delay = curr.create_time - prev.create_time
                    if 1 <= delay <= 600:  # 1s to 10min — realistic range
                        reply_delays.append(float(delay))
                        # Estimate typing speed
                        content_len = len(curr.content or "")
                        if content_len > 0 and delay > 0:
                            typing_speeds.append(content_len / delay)

        # Fit log-normal to reply delays
        if reply_delays:
            log_delays = [math.log(d) for d in reply_delays]
            mu = sum(log_delays) / len(log_delays)
            variance = sum((x - mu) ** 2 for x in log_delays) / len(log_delays)
            sigma = math.sqrt(variance) if variance > 0 else 0.5
        else:
            mu, sigma = math.log(5.0), 0.8  # default: ~5s median

        # Median typing speed
        if typing_speeds:
            typing_speeds.sort()
            median_speed = typing_speeds[len(typing_speeds) // 2]
        else:
            median_speed = 3.0  # chars/sec default

        # Normalize active hours
        total_hours = sum(active_hours) or 1
        active_hours_norm = [h / total_hours for h in active_hours]

        self._profile = {
            "reply_delay_mu": mu,
            "reply_delay_sigma": sigma,
            "typing_speed": median_speed,
            "active_hours": active_hours_norm,
            "sample_count": len(reply_delays),
        }
        logger.info(
            "Learned timing profile: mu=%.2f sigma=%.2f speed=%.1f chars/s from %d samples",
            mu, sigma, median_speed, len(reply_delays),
        )

        if self._profile_path:
            self.save()

    def save(self, path: str = "") -> None:
        """Save profile to JSON file."""
        target = path or self._profile_path
        if not target:
            return
        Path(target).write_text(json.dumps(self._profile, indent=2), encoding="utf-8")
        logger.info("Saved timing profile to %s", target)

    def load(self, path: str = "") -> bool:
        """Load profile from JSON file. Returns True if loaded successfully."""
        target = path or self._profile_path
        if not target:
            return False
        try:
            self._profile = json.loads(Path(target).read_text(encoding="utf-8"))
            logger.info("Loaded timing profile from %s", target)
            return True
        except Exception as e:
            logger.warning("Failed to load timing profile from %s: %s", target, e)
            return False

    def sample_reply_delay(self, msg_length: int = 0) -> float:
        """Sample a human-like reply delay in seconds."""
        mu = self._profile.get("reply_delay_mu", math.log(5.0))
        sigma = self._profile.get("reply_delay_sigma", 0.8)

        # Log-normal sample via Box-Muller
        z = random.gauss(0, 1)
        delay = math.exp(mu + sigma * z)

        # Reading time scales with message length
        if msg_length > 20:
            delay += (msg_length - 20) * 0.05

        return max(1.0, min(delay, 300.0))

    def sample_typing_delay(self, text: str) -> float:
        """Estimate total typing time for the given text in seconds."""
        speed = self._profile.get("typing_speed", 3.0)
        if speed <= 0:
            speed = 3.0
        base = len(text) / speed
        # Add noise ±20%
        noise = random.uniform(0.8, 1.2)
        return max(0.5, min(base * noise, 60.0))

    def is_active_hour(self) -> bool:
        """Check if the current hour is an active period based on learned profile."""
        hours = self._profile.get("active_hours")
        if not hours:
            return True  # No profile, assume always active
        current_hour = datetime.now().hour
        return hours[current_hour] >= 0.01
