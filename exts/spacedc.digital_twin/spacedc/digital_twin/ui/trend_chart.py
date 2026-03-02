"""
============================================================
  trend_chart.py — Real-time telemetry trend chart (omni.ui)
  Migrated from: js/trend-chart.js
============================================================

  Renders 4 telemetry curves: Solar, Battery, Radiator, GPU Temp.
  Uses omni.ui.CanvasFrame for custom drawing, or omni.ui.Plot
  for simpler line charts.
"""
from __future__ import annotations
from typing import Optional, List
import math

try:
    import omni.ui as ui
    HAS_OMNI_UI = True
except ImportError:
    HAS_OMNI_UI = False

from ..physics.state import SimState, TrendBuffer
from ..physics.constants import CELL_TECHS, COOLANTS, SIGMA
from ..physics.solar_array_model import compute_peak_solar
from ..physics.thermal_model import compute_peak_rad_capacity

# ── Color constants (AABBGGRR for omni.ui) ──────────────────
COLOR_SOLAR  = 0xFF66E0FF   # yellow
COLOR_BAT    = 0xFF006BFF   # orange
COLOR_RAD    = 0xFF0044FF   # red
COLOR_GPU_T  = 0xFFFFD400   # cyan

TREND_STYLE = {
    "Window": {"background_color": 0xFF040C12},
}


class TrendChartPanel:
    """
    Real-time trend chart window showing 4 telemetry lines.
    Uses omni.ui.Plot widgets (one per metric).
    """

    def __init__(self, state: SimState):
        self._state = state
        self._window: Optional["ui.Window"] = None
        self._plot_solar = None
        self._plot_bat = None
        self._plot_rad = None
        self._plot_gpu = None

    def build(self):
        if not HAS_OMNI_UI:
            return

        self._window = ui.Window(
            "📈 Telemetry Trends",
            width=460,
            height=320,
        )

        with self._window.frame:
            with ui.VStack(spacing=4, style=TREND_STYLE):
                # Solar power
                with ui.HStack(height=14):
                    ui.Label("☀ Solar (kW)", style={"color": COLOR_SOLAR, "font_size": 11})
                self._plot_solar = ui.Plot(
                    ui.Type.LINE, 0.0, 100.0, *([0.0] * 10),
                    height=50,
                    style={"color": COLOR_SOLAR, "background_color": 0xFF0A1428},
                )

                # Battery SOC
                with ui.HStack(height=14):
                    ui.Label("🔋 Battery (%)", style={"color": COLOR_BAT, "font_size": 11})
                self._plot_bat = ui.Plot(
                    ui.Type.LINE, 0.0, 100.0, *([50.0] * 10),
                    height=50,
                    style={"color": COLOR_BAT, "background_color": 0xFF0A1428},
                )

                # Radiator
                with ui.HStack(height=14):
                    ui.Label("🌡 Radiator (kW)", style={"color": COLOR_RAD, "font_size": 11})
                self._plot_rad = ui.Plot(
                    ui.Type.LINE, 0.0, 100.0, *([0.0] * 10),
                    height=50,
                    style={"color": COLOR_RAD, "background_color": 0xFF0A1428},
                )

                # GPU Temp
                with ui.HStack(height=14):
                    ui.Label("🖥 GPU Temp (°C)", style={"color": COLOR_GPU_T, "font_size": 11})
                self._plot_gpu = ui.Plot(
                    ui.Type.LINE, 20.0, 100.0, *([70.0] * 10),
                    height=50,
                    style={"color": COLOR_GPU_T, "background_color": 0xFF0A1428},
                )

    def destroy(self):
        if self._window:
            self._window.destroy()
            self._window = None

    def update(self):
        """Refresh plot data from trend buffer — call each sim tick."""
        if not HAS_OMNI_UI or not self._window:
            return

        trend = self._state.trend
        s = self._state

        # Compute normalization peaks
        peak_solar = max(1.0, compute_peak_solar(
            s.wing_count, s.wing_area, s.current_cell_tech
        ))
        peak_rad = max(1.0, compute_peak_rad_capacity(
            s.rad_count, s.rad_area, s.rad_epsilon, s.current_coolant
        ))

        if len(trend.solar) > 1:
            # Normalize to 0-100 range for the plot widget
            solar_norm = [min(100.0, v / peak_solar * 100.0) for v in trend.solar]
            bat_data = list(trend.bat)
            rad_norm = [min(100.0, v / peak_rad * 100.0) for v in trend.rad]
            gpu_data = list(trend.gpu_t)

            self._plot_solar.set_data(*solar_norm)
            self._plot_bat.set_data(*bat_data)
            self._plot_rad.set_data(*rad_norm)
            self._plot_gpu.set_data(*gpu_data)
