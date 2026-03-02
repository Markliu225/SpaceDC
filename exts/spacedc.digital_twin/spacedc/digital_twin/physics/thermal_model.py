"""
============================================================
  thermal_model.py — Radiative cooling / thermal model
  Migrated from: js/radiator.js (updateRadTable)
                 js/simulation.js (radPwr, thermalRatio, gpuTemp)
============================================================
"""
from __future__ import annotations
import math
import random
from typing import List, TYPE_CHECKING

from .constants import SIGMA, COOLANTS

if TYPE_CHECKING:
    from .state import RadiatorPanel


def update_radiator_panels(
    panels: List["RadiatorPanel"],
    eclipse: bool,
    coolant_key: str,
) -> float:
    """
    Update each panel's surface temperature and radiated power.
    Returns total radiated power in kW.

    Stefan-Boltzmann:  Q = ε · σ · A · F · (T⁴ − T_space⁴)
    where T_space = 2.7 K (cosmic microwave background).
    """
    cool = COOLANTS[coolant_key]
    total_q = 0.0
    for p in panels:
        # Temperature update
        if eclipse:
            p.surf_temp = max(14.0, p.surf_temp - 0.5)
        else:
            p.surf_temp = min(63.0, 54.0 + random.random() * 7.0)

        # Radiative heat rejection (kW)
        t_kelvin = p.surf_temp + 273.15
        p.q_rad = (
            p.emissivity * SIGMA * p.area * p.view_factor
            * (t_kelvin ** 4 - 2.7 ** 4)
        ) / 1000.0 * cool["heatCapFactor"]

        total_q += p.q_rad

    return total_q


def compute_rad_power_total(panels: List["RadiatorPanel"], eclipse: bool) -> float:
    """Sum of all panel Q_rad, with eclipse 50% factor applied like JS."""
    return sum(
        (p.q_rad * 0.5 if eclipse else p.q_rad)
        for p in panels
    )


def compute_gpu_temperature(
    eclipse: bool,
    bat_soc: float,
    rad_power: float,
    heat_load: float,
) -> float:
    """
    GPU temperature model from simulation.js:
      gpuTempBase = eclipse ? 65 + batSOC*0.18 : 76 + random()*4
      gpuTemp = base + (1 - thermalRatio) * 25
    """
    thermal_ratio = min(1.0, rad_power / max(1.0, heat_load))
    if eclipse:
        base = 65.0 + bat_soc * 0.18
    else:
        base = 76.0 + random.random() * 4.0
    return base + (1.0 - thermal_ratio) * 25.0


def compute_array_temperature(eclipse: bool) -> float:
    """Solar array temperature sensor readout."""
    if eclipse:
        return -55.0 + random.random() * 5.0
    return 62.0 + random.random() * 16.0


def compute_average_rad_surface_temp(panels: List["RadiatorPanel"]) -> float:
    """Average radiator surface temperature across all panels."""
    if not panels:
        return 0.0
    return sum(p.surf_temp for p in panels) / len(panels)


def compute_peak_rad_capacity(
    rad_count: int,
    rad_area: float,
    rad_epsilon: float,
    coolant_key: str,
) -> float:
    """
    Theoretical peak radiator capacity (kW) — used by DT summary.
    Tsurf = 58°C → T = 331.15 K, VF = 0.9.
    """
    cool = COOLANTS[coolant_key]
    t_surf = 58.0 + 273.15
    total_area = rad_count * rad_area
    return (
        rad_epsilon * SIGMA * total_area * 0.9
        * (t_surf ** 4 - 2.7 ** 4)
    ) / 1000.0 * cool["heatCapFactor"]


def check_thermal_feasibility(
    workload_heat_kw: float,
    peak_rad_kw: float,
) -> tuple:
    """
    Returns (status, ratio, message):
      status: 'ok' | 'warn' | 'danger'
      ratio:  peak_rad / heat_load (as fraction, e.g. 1.2 = 120%)
    """
    ratio = peak_rad_kw / max(1.0, workload_heat_kw)
    if ratio >= 1.2:
        return ("ok", ratio, f"✓ OK ({ratio * 100:.0f}% capacity)")
    elif ratio >= 1.0:
        return ("warn", ratio, f"⚠ Marginal ({ratio * 100:.0f}%)")
    else:
        deficit = workload_heat_kw - peak_rad_kw
        return ("danger", ratio, f"✗ OVERHEAT ({ratio * 100:.0f}% — deficit {deficit:.0f} kW)")
