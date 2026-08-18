"""Thin, frame-explicit wrapper around Vallado's SGP4 implementation."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

import numpy as np
from astropy.time import Time

from ..time import ensure_utc_sequence
from ..types import Ephemeris


class SGP4Propagator:
    """Propagate a TLE and return raw TEME states in SI units."""

    def __init__(self, line1: str, line2: str) -> None:
        try:
            from sgp4.api import Satrec
        except ImportError as exc:  # pragma: no cover - dependency error path
            raise ImportError("SGP4 support requires `pip install sgp4`") from exc
        self.line1 = line1.rstrip("\r\n")
        self.line2 = line2.rstrip("\r\n")
        self._satellite = Satrec.twoline2rv(self.line1, self.line2)

    @property
    def satellite_number(self) -> int:
        return int(self._satellite.satnum)

    def propagate(self, times: Iterable[datetime]) -> Ephemeris:
        from sgp4.api import SGP4_ERRORS

        requested_times = ensure_utc_sequence(times)
        astropy_time = Time(list(requested_times), scale="utc")
        errors, position_km, velocity_km_s = self._satellite.sgp4_array(
            np.asarray(astropy_time.jd1), np.asarray(astropy_time.jd2)
        )
        bad = np.flatnonzero(errors)
        if bad.size:
            details = ", ".join(
                f"index {index}: {SGP4_ERRORS.get(int(errors[index]), 'unknown error')}"
                for index in bad
            )
            raise RuntimeError(f"SGP4 propagation failed ({details})")
        return Ephemeris(
            requested_times,
            np.asarray(position_km) * 1000.0,
            np.asarray(velocity_km_s) * 1000.0,
            "TEME",
        )

