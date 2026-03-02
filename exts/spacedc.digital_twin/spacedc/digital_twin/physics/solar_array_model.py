"""
============================================================
  solar_array_model.py — Solar power generation model
  Migrated from: js/solar-array.js (updateWingTable logic)
                 js/simulation.js  (peakSolar, solarPwr)
============================================================
"""
from __future__ import annotations
import random
from typing import List, TYPE_CHECKING

from .constants import CELL_TECHS, SOLAR_IRRADIANCE

if TYPE_CHECKING:
    from .state import SolarWing


def compute_peak_solar(wing_count: int, wing_area: float, cell_tech_key: str) -> float:
    """
    Peak solar power in kW (sunlit, before random jitter).
    Formula: n × A × G × η × (1 − α·ΔT)
    where G = 1367 W/m², ΔT = 75−25 = 50°C.
    """
    tech = CELL_TECHS[cell_tech_key]
    return (wing_count * wing_area * SOLAR_IRRADIANCE * tech["eff"]
            / 1000.0 * (1.0 - (75.0 - 25.0) * tech["tcoef"]))


def compute_solar_power(peak_solar: float, eclipse: bool) -> float:
    """
    Instantaneous solar power output in kW.
    In eclipse: 0.  In sun: peak × (0.97 + random jitter up to 0.03).
    """
    if eclipse:
        return 0.0
    return peak_solar * (0.97 + random.random() * 0.03)


def update_wings(wings: List["SolarWing"], eclipse: bool, cell_tech_key: str) -> None:
    """
    Update each wing's output & temperature (mirrors JS ``updateWingTable``).
    Mutates wing objects in-place.
    """
    tech = CELL_TECHS[cell_tech_key]
    for w in wings:
        if eclipse:
            w.output = 0.0
            w.temp = max(-65.0, w.temp - 1.4)
        else:
            w.output = (w.area * SOLAR_IRRADIANCE * w.efficiency
                        / 1000.0 * (1.0 - (w.temp - 25.0) * tech["tcoef"]))
            w.temp = min(84.0, w.temp + 0.35)
