"""Sample human-like timing from a learned profile."""

import json
import logging
import math
import random
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class HumanTiming:
    """Sample human-like timing delays from a JSON profile."""

    def __init__(self, profile_path: str = ""):
        self._profile_path = profile_path
        self._profile: dict = {}

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
