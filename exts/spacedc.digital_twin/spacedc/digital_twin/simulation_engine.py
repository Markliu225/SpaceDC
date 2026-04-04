"""
============================================================
  simulation_engine.py — Main simulation loop
  Migrated from: js/simulation.js (update + animate functions)
============================================================

  Integrates all physics models and drives scene + UI updates.
  In Omniverse Kit, this is ticked via ``omni.kit.app.get_app().
  get_update_event_stream()`` subscription.
"""
from __future__ import annotations

import time
import math
import traceback
from typing import Optional, Callable

from .physics.state import SimState
from .physics.constants import ORBIT_PERIOD, CELL_TECHS, COOLANTS, WORKLOADS
from .physics.orbital_mechanics import get_angle, is_eclipse, get_raan, get_true_anomaly_deg, get_sun_beta_angle
from .physics.solar_array_model import compute_peak_solar, compute_solar_power, update_wings
from .physics.thermal_model import (
    update_radiator_panels, compute_rad_power_total,
    compute_gpu_temperature, compute_array_temperature,
    compute_average_rad_surface_temp,
)
from .physics.battery_model import update_battery_soc
from .physics.workload_model import compute_workload_metrics
from .physics.telemetry import TelemetryLogger, LOGS


class SimulationEngine:
    """
    Main simulation engine — one ``tick()`` call per frame.
    Mirrors the JS ``update(ts)`` function from simulation.js.
    """

    def __init__(self, state: SimState, logger: TelemetryLogger):
        self.state = state
        self.logger = logger
        self._last_wall_time: Optional[float] = None
        self._earth_rot_y: float = 0.0

        # Callbacks for scene / UI updates
        self._on_scene_update: Optional[Callable] = None
        self._on_ui_update: Optional[Callable] = None
        self._earth_rotation_deg_per_sec: float = 8.0

    def set_callbacks(
        self,
        on_scene_update: Optional[Callable] = None,
        on_ui_update: Optional[Callable] = None,
    ):
        self._on_scene_update = on_scene_update
        self._on_ui_update = on_ui_update

    def tick(self, wall_time: Optional[float] = None) -> dict:
        """
        Advance the simulation by one frame.
        Returns a dict of computed values for the current tick.

        ``wall_time``: real wall-clock seconds (monotonic).
                       If None, uses ``time.monotonic()``.
        """
        if wall_time is None:
            wall_time = time.monotonic()

        s = self.state

        # ── Delta-time ──────────────────────────────────────
        if self._last_wall_time is None:
            self._last_wall_time = wall_time
        dt = min((wall_time - self._last_wall_time), 0.1)
        self._last_wall_time = wall_time

        s.sim_time += dt * s.speed
        s.met_seconds += dt * s.speed
        s.phase_time += dt * s.speed

        # ── Orbit / eclipse detection ───────────────────────
        angle = get_angle(s.sim_time, s.orbit_period)
        eclipse = is_eclipse(angle, s.eclipse_fraction)
        prev_eclipse = is_eclipse(get_angle(s.sim_time - dt * s.speed, s.orbit_period), s.eclipse_fraction)

        new_orbit = int(s.sim_time / s.orbit_period) + 1
        if new_orbit != s.orbit_count:
            s.orbit_count = new_orbit
            self.logger.add_log("info", f"Orbit #{s.orbit_count} commenced.", s.met_seconds)

        if eclipse != prev_eclipse:
            s.phase_time = 0.0
            if eclipse:
                self.logger.add_log("warn", "Entering umbra. Battery discharge.", s.met_seconds)
            else:
                self.logger.add_log("ok", "Exiting eclipse. Solar online.", s.met_seconds)

        s.eclipse = eclipse

        # ── Solar power ─────────────────────────────────────
        tech = CELL_TECHS[s.current_cell_tech]
        peak_solar = compute_peak_solar(s.wing_count, s.wing_area, s.current_cell_tech)
        solar_pwr = compute_solar_power(peak_solar, eclipse)
        s.solar_pwr = solar_pwr

        # ── Workload metrics ────────────────────────────────
        wl_metrics = compute_workload_metrics(s.current_workload, eclipse, s.bat_soc)
        compute_load = wl_metrics["compute_load_kw"]
        heat_load = wl_metrics["heat_load_kw"]

        # ── Wing table update ───────────────────────────────
        update_wings(s.wings, eclipse, s.current_cell_tech)

        # ── Radiator update ─────────────────────────────────
        update_radiator_panels(s.rad_panels, eclipse, s.current_coolant)
        rad_pwr = compute_rad_power_total(s.rad_panels, eclipse)
        s.rad_pwr = rad_pwr

        # ── Battery SOC ─────────────────────────────────────
        s.bat_soc = update_battery_soc(
            s.bat_soc, eclipse, compute_load, solar_pwr, dt, s.speed
        )

        # ── GPU temperature ─────────────────────────────────
        gpu_temp = compute_gpu_temperature(eclipse, s.bat_soc, rad_pwr, heat_load)
        s.gpu_temp = gpu_temp
        s.arr_temp = compute_array_temperature(eclipse)
        s.flops = wl_metrics["flops"]
        s.gpu_util = wl_metrics["gpu_util_pct"]

        # ── Trend buffer ────────────────────────────────────
        s.trend_timer += dt * s.speed
        if s.trend_timer >= 1.0:
            s.trend_timer = 0.0
            s.trend.push(solar_pwr, s.bat_soc, rad_pwr, gpu_temp)

        # ── Periodic log messages ───────────────────────────
        s.log_timer += dt * s.speed
        if s.log_timer > 85.0:
            s.log_timer = 0.0
            log_type, log_msg = LOGS[s.log_idx % len(LOGS)]
            self.logger.add_log(log_type, log_msg, s.met_seconds)
            s.log_idx += 1

        # ── Earth rotation ──────────────────────────────────
        # Keep Earth rotation visually alive even on lower frame rates.
        self._earth_rot_y = (self._earth_rot_y + dt * self._earth_rotation_deg_per_sec) % 360.0

        # ── Build result dict ───────────────────────────────
        result = {
            "angle":       angle,
            "eclipse":     eclipse,
            "solar_pwr":   solar_pwr,
            "peak_solar":  peak_solar,
            "rad_pwr":     rad_pwr,
            "bat_soc":     s.bat_soc,
            "gpu_temp":    gpu_temp,
            "flops":       s.flops,
            "gpu_util":    s.gpu_util,
            "compute_load": compute_load,
            "heat_load":   heat_load,
            "earth_rot_y": self._earth_rot_y,
            "raan":        get_raan(s.met_seconds),
            "true_anomaly": get_true_anomaly_deg(s.sim_time),
            "beta_angle":  get_sun_beta_angle(s.sim_time),
        }

        # ── Invoke callbacks ────────────────────────────────
        if self._on_scene_update:
            try:
                self._on_scene_update(result)
            except Exception as e:
                print(f"[SpaceDC] ERROR in scene update callback: {e}")
                traceback.print_exc()
        if self._on_ui_update:
            try:
                self._on_ui_update(result)
            except Exception as e:
                print(f"[SpaceDC] ERROR in UI update callback: {e}")
                traceback.print_exc()

        return result
