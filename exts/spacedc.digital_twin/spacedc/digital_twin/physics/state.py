"""
============================================================
  state.py — Simulation state, dynamic data models, trend buffer
  Migrated from: js/state.js
============================================================
"""
from __future__ import annotations

import random
import string
from dataclasses import dataclass, field
from typing import List, Dict
from collections import deque

from .constants import CELL_TECHS, COOLANTS, TREND_MAX


# ── Trend buffer max length ──
# (also defined in constants.py, re-imported for clarity)
try:
    from .constants import TREND_MAX
except ImportError:
    TREND_MAX = 600


@dataclass
class SolarWing:
    """One solar array wing."""
    id: int
    name: str
    cells: int = 240
    area: float = 350.0        # m² per wing
    temp: float = 70.0         # °C
    efficiency: float = 0.295
    output: float = 0.0        # kW

    @staticmethod
    def build_fleet(count: int, area: float, cell_tech_key: str) -> List["SolarWing"]:
        """Rebuild wing array (mirrors JS ``rebuildWings``)."""
        tech = CELL_TECHS[cell_tech_key]
        wings: List[SolarWing] = []
        for i in range(count):
            letter = string.ascii_uppercase[i % 26]
            suffix = str(i // 26) if i >= 26 else ""
            wings.append(SolarWing(
                id=i + 1,
                name=f"W{letter}{suffix}",
                area=area,
                temp=65.0 + random.random() * 10.0,
                efficiency=tech["eff"] + (random.random() - 0.5) * 0.005,
            ))
        return wings


@dataclass
class RadiatorPanel:
    """One radiative cooling panel."""
    id: int
    area: float = 143.3        # m² per panel
    surf_temp: float = 58.0    # °C
    emissivity: float = 0.92
    view_factor: float = 0.90
    q_rad: float = 0.0         # kW rejected

    @staticmethod
    def build_fleet(count: int, area: float, epsilon: float) -> List["RadiatorPanel"]:
        """Rebuild radiator panel array (mirrors JS ``rebuildRadPanels``)."""
        panels: List[RadiatorPanel] = []
        for i in range(count):
            panels.append(RadiatorPanel(
                id=i + 1,
                area=area,
                surf_temp=55.0 + random.random() * 8.0,
                emissivity=epsilon,
                view_factor=0.85 + random.random() * 0.1,
            ))
        return panels


@dataclass
class TrendBuffer:
    """Fixed-length ring buffer for telemetry trend data."""
    solar: deque = field(default_factory=lambda: deque(maxlen=TREND_MAX))
    bat:   deque = field(default_factory=lambda: deque(maxlen=TREND_MAX))
    rad:   deque = field(default_factory=lambda: deque(maxlen=TREND_MAX))
    gpu_t: deque = field(default_factory=lambda: deque(maxlen=TREND_MAX))

    def push(self, solar_pwr: float, bat_soc: float, rad_pwr: float, gpu_temp: float):
        self.solar.append(solar_pwr)
        self.bat.append(bat_soc)
        self.rad.append(rad_pwr)
        self.gpu_t.append(gpu_temp)


@dataclass
class SimState:
    """
    Central simulation state — single source of truth.
    Replaces all global ``let`` variables from ``state.js`` + ``simulation.js``.
    """
    # ── Time ────────────────────────────
    sim_time: float = 0.0
    speed: int = 60                     # time acceleration factor
    met_seconds: float = 0.0            # Mission Elapsed Time
    orbit_count: int = 1
    phase_time: float = 0.0             # seconds in current sun/eclipse phase
    last_time: float = 0.0              # last real timestamp (seconds)

    # ── Power ───────────────────────────
    bat_soc: float = 87.0               # battery state-of-charge %
    solar_pwr: float = 0.0              # kW current solar output
    rad_pwr: float = 0.0                # kW current radiator rejection

    # ── Thermal / compute ───────────────
    gpu_temp: float = 76.0              # °C
    arr_temp: float = 62.0              # °C array temperature
    flops: float = 12.8                 # ExaFLOPS current
    gpu_util: int = 92                  # % GPU utilisation

    # ── Digital-twin configurable params ─
    wing_count: int = 8
    wing_area: float = 350.0            # m² per wing
    current_cell_tech: str = "tj"

    rad_count: int = 6
    rad_area: float = 143.3             # m² per panel
    rad_epsilon: float = 0.92
    current_coolant: str = "nh3"

    current_workload: str = "llama70b_train"

    # ── Dynamic arrays ──────────────────
    wings: List[SolarWing] = field(default_factory=list)
    rad_panels: List[RadiatorPanel] = field(default_factory=list)

    # ── Trend buffer ────────────────────
    trend: TrendBuffer = field(default_factory=TrendBuffer)
    trend_timer: float = 0.0

    # ── Logging ─────────────────────────
    log_idx: int = 0
    log_timer: float = 0.0

    # ── Eclipse state ───────────────────
    eclipse: bool = False

    def rebuild_wings(self):
        self.wings = SolarWing.build_fleet(
            self.wing_count, self.wing_area, self.current_cell_tech
        )

    def rebuild_rad_panels(self):
        self.rad_panels = RadiatorPanel.build_fleet(
            self.rad_count, self.rad_area, self.rad_epsilon
        )

    def initialize(self):
        """Build initial arrays — call once at startup."""
        self.rebuild_wings()
        self.rebuild_rad_panels()
