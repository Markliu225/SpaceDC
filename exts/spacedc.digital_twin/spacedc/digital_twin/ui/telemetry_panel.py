"""
============================================================
  telemetry_panel.py — Telemetry log & HUD overlay (omni.ui)
  Migrated from: js/telemetry.js + js/simulation.js (DOM updates)
============================================================
"""
from __future__ import annotations
from typing import Optional

try:
    import omni.ui as ui
    HAS_OMNI_UI = True
except ImportError:
    HAS_OMNI_UI = False

from ..physics.state import SimState
from ..physics.telemetry import TelemetryLogger

# ── Style ───────────────────────────────────────────────────
LOG_STYLE = {
    "Label::ok":     {"color": 0xFF39FF14, "font_size": 11},
    "Label::info":   {"color": 0xFF00D4FF, "font_size": 11},
    "Label::warn":   {"color": 0xFFFFAA00, "font_size": 11},
    "Label::danger": {"color": 0xFFFF2244, "font_size": 11},
}

HUD_STYLE = {
    "Label::phase_sunlit":  {"color": 0xFFFFE066, "font_size": 16},
    "Label::phase_eclipse": {"color": 0xFF6688FF, "font_size": 16},
    "Label::metric":        {"color": 0xFF39FF14, "font_size": 14},
    "Label::metric_warn":   {"color": 0xFFFF6600, "font_size": 14},
    "Label::met":           {"color": 0xFF00D4FF, "font_size": 13},
    "Label::status_ok":     {"color": 0xFF39FF14, "font_size": 14},
    "Label::status_warn":   {"color": 0xFFFFAA00, "font_size": 14},
    "Label::status_danger": {"color": 0xFFFF2244, "font_size": 14},
}


class TelemetryPanel:
    """Scrolling telemetry log window."""

    def __init__(self, logger: TelemetryLogger):
        self._logger = logger
        self._window: Optional["ui.Window"] = None
        self._scroll: Optional["ui.ScrollingFrame"] = None
        self._vstack = None

        # Subscribe to new logs
        self._logger.subscribe(self._on_new_log)

    def build(self):
        if not HAS_OMNI_UI:
            return
        self._window = ui.Window("📡 Telemetry Log", width=420, height=260)
        with self._window.frame:
            self._scroll = ui.ScrollingFrame(style=LOG_STYLE)
            with self._scroll:
                self._vstack = ui.VStack(spacing=1)

    def destroy(self):
        self._logger.unsubscribe(self._on_new_log)
        if self._window:
            self._window.destroy()
            self._window = None

    def _on_new_log(self, entry: dict):
        if not HAS_OMNI_UI or not self._vstack:
            return
        with self._vstack:
            ui.Label(
                f"{entry['timestamp']} {entry['msg']}",
                name=entry["level"],
                height=16,
            )
        # Auto-scroll to bottom
        if self._scroll:
            self._scroll.scroll_y = self._scroll.scroll_y_max


class HUDOverlay:
    """
    Heads-up-display showing key metrics.
    Mirrors the header stats + phase box + system status from the web version.
    """

    def __init__(self, state: SimState, logger: TelemetryLogger):
        self._state = state
        self._logger = logger
        self._window: Optional["ui.Window"] = None

        # Labels for live update
        self._lbl_phase = None
        self._lbl_phase_detail = None
        self._lbl_met = None
        self._lbl_orbit = None
        self._lbl_solar = None
        self._lbl_bat = None
        self._lbl_rad = None
        self._lbl_gpu_t = None
        self._lbl_flops = None
        self._lbl_gpu_pct = None
        self._lbl_status = None

    def build(self):
        if not HAS_OMNI_UI:
            return

        self._window = ui.Window(
            "🛰️ ORBITAL DC-1 HUD",
            width=340,
            height=400,
            flags=ui.WINDOW_FLAGS_NO_RESIZE,
        )

        with self._window.frame:
            with ui.VStack(spacing=4, style=HUD_STYLE):
                # Phase box
                self._lbl_phase = ui.Label(
                    "☀️ SUNLIT PASS", name="phase_sunlit",
                    alignment=ui.Alignment.CENTER, height=28
                )
                self._lbl_phase_detail = ui.Label(
                    "", name="metric", alignment=ui.Alignment.CENTER, height=18
                )
                ui.Separator(height=2)

                # MET + Orbit
                with ui.HStack(height=20):
                    self._lbl_met = ui.Label("T+000:00:00", name="met")
                    self._lbl_orbit = ui.Label("Orbit #1", name="met",
                                               alignment=ui.Alignment.RIGHT)

                ui.Separator(height=2)

                # Power gauges
                ui.Label("⚡ Power", height=18)
                with ui.VStack(spacing=2):
                    with ui.HStack(height=18):
                        ui.Label("Solar:", width=80)
                        self._lbl_solar = ui.Label("0 kW", name="metric")
                    with ui.HStack(height=18):
                        ui.Label("Battery:", width=80)
                        self._lbl_bat = ui.Label("87%", name="metric")
                    with ui.HStack(height=18):
                        ui.Label("Radiator:", width=80)
                        self._lbl_rad = ui.Label("0 kW", name="metric")

                ui.Separator(height=2)

                # Compute gauges
                ui.Label("🖥 Compute", height=18)
                with ui.VStack(spacing=2):
                    with ui.HStack(height=18):
                        ui.Label("FLOPS:", width=80)
                        self._lbl_flops = ui.Label("12.8 EF", name="metric")
                    with ui.HStack(height=18):
                        ui.Label("GPU Util:", width=80)
                        self._lbl_gpu_pct = ui.Label("92%", name="metric")
                    with ui.HStack(height=18):
                        ui.Label("GPU Temp:", width=80)
                        self._lbl_gpu_t = ui.Label("76°C", name="metric")

                ui.Separator(height=2)

                # System status
                self._lbl_status = ui.Label(
                    "● NOMINAL", name="status_ok",
                    alignment=ui.Alignment.CENTER, height=24,
                )

    def destroy(self):
        if self._window:
            self._window.destroy()
            self._window = None

    def update(self):
        """Called each simulation tick to refresh HUD values."""
        if not HAS_OMNI_UI or not self._window:
            return

        s = self._state

        # Phase
        if s.eclipse:
            self._lbl_phase.text = "🌑 ECLIPSE PASS"
            self._lbl_phase.name = "phase_eclipse"
            self._lbl_phase_detail.text = f"Bat {s.bat_soc:.0f}% SOC — discharge"
        else:
            self._lbl_phase.text = "☀️ SUNLIT PASS"
            self._lbl_phase.name = "phase_sunlit"
            self._lbl_phase_detail.text = f"Solar arrays {s.solar_pwr:.0f} kW"

        # MET
        self._lbl_met.text = self._logger.format_met(s.met_seconds)
        self._lbl_orbit.text = f"Orbit #{s.orbit_count}"

        # Power
        self._lbl_solar.text = f"{s.solar_pwr:.0f} kW"
        self._lbl_bat.text = f"{s.bat_soc:.0f}%"
        self._lbl_bat.name = "metric_warn" if s.bat_soc < 25 else "metric"
        self._lbl_rad.text = f"{s.rad_pwr:.0f} kW"

        # Compute
        self._lbl_flops.text = f"{s.flops:.1f} EF"
        self._lbl_gpu_pct.text = f"{s.gpu_util}%"
        self._lbl_gpu_t.text = f"{s.gpu_temp:.0f}°C"
        self._lbl_gpu_t.name = "metric_warn" if s.gpu_temp > 90 else "metric"

        # System status
        if s.gpu_temp > 95:
            self._lbl_status.text = "▲ GPU OVERHEAT"
            self._lbl_status.name = "status_danger"
        elif s.bat_soc < 20:
            self._lbl_status.text = "▲ LOW BATTERY"
            self._lbl_status.name = "status_danger"
        elif s.eclipse:
            self._lbl_status.text = "◉ ECLIPSE MODE"
            self._lbl_status.name = "status_warn"
        else:
            self._lbl_status.text = "● NOMINAL"
            self._lbl_status.name = "status_ok"
