"""Utilities for throttling scraper requests."""

from __future__ import annotations

import random
import time
from typing import Tuple


def polite_sleep(delay_range: Tuple[float, float]) -> float:
    """Sleep for a random interval within ``delay_range``.

    Parameters
    ----------
    delay_range:
        Two-tuple of ``(min_seconds, max_seconds)`` representing the
        inclusive bounds for a random sleep duration.

    Returns
    -------
    float
        The actual number of seconds slept.
    """
    delay = random.uniform(*delay_range)
    time.sleep(delay)
    return delay
