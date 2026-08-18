"""UTC time handling helpers.

The package intentionally rejects naive datetimes.  Orbit and Earth-orientation
calculations are too sensitive to silently guessing a timezone.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

import numpy as np


def ensure_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime, rejecting timezone-naive input."""

    if not isinstance(value, datetime):
        raise TypeError("epoch must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware; use timezone.utc for UTC")
    return value.astimezone(timezone.utc)


def ensure_utc_sequence(values: Iterable[datetime]) -> tuple[datetime, ...]:
    result = tuple(ensure_utc(value) for value in values)
    if not result:
        raise ValueError("at least one time is required")
    if any(b < a for a, b in zip(result, result[1:])):
        raise ValueError("times must be monotonically non-decreasing")
    return result


def time_grid(start: datetime, stop: datetime, step_s: float) -> tuple[datetime, ...]:
    """Build an inclusive UTC grid and always include ``stop`` exactly."""

    start = ensure_utc(start)
    stop = ensure_utc(stop)
    if stop < start:
        raise ValueError("stop must not be earlier than start")
    if not np.isfinite(step_s) or step_s <= 0.0:
        raise ValueError("step_s must be a finite positive number")
    duration = (stop - start).total_seconds()
    count = int(np.floor(duration / step_s))
    values = [start + timedelta(seconds=k * step_s) for k in range(count + 1)]
    if not values or values[-1] < stop:
        values.append(stop)
    else:
        values[-1] = stop
    return tuple(values)


def seconds_since(times: Iterable[datetime], epoch: datetime) -> np.ndarray:
    epoch = ensure_utc(epoch)
    values = ensure_utc_sequence(times)
    return np.asarray([(value - epoch).total_seconds() for value in values], dtype=float)

