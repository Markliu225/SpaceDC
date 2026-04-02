"""
============================================================
  satellite_status_window.py — Satellite Status Detail Window
  Displays subsystem-level telemetry and per-wing / per-radiator
  status in a rich tabular layout.
============================================================
"""
from __future__ import annotations

from typing import Optional, List

try:
    import omni.ui as ui
    HAS_OMNI_UI = True
except ImportError:
    HAS_OMNI_UI = False

from ..physics.state import SimState

# ── Style tokens ────────────────────────────────────────────
STATUS_STYLE = {
    "Window": {
        "background_color": 0xFF18140A,
        "border_color": 0xFF2A3545,
        "border_width": 1,
    },
    "Label::title": {
        "color": 0xFFD8B400,
        "font_size": 18,
    },
    "Label::section": {
        "color": 0xFFD8B400,
        "font_size": 14,
    },
    "Label::label": {
        "color": 0xFFD8C4B0,
        "font_size": 12,
    },
    "Label::value": {
        "color": 0xFF82E57A,
        "font_size": 12,
    },
    "Label::value_warn": {
        "color": 0xFF47B3FF,
        "font_size": 12,
    },
    "Label::value_danger": {
        "color": 0xFF6B6BFF,
        "font_size": 12,
    },
    "Label::unit": {
        "color": 0xFF807060,
        "font_size": 11,
    },
    "Label::status_nominal": {
        "color": 0xFF82E57A,
        "font_size": 12,
    },
    "Label::status_warn": {
        "color": 0xFF47B3FF,
        "font_size": 12,
    },
    "Label::status_danger": {
        "color": 0xFF6B6BFF,
        "font_size": 12,
    },
    "Label::header_col": {
        "color": 0xFF807060,
        "font_size": 11,
    },
    "Label::wing_name": {
        "color": 0xFFD8B400,
        "font_size": 12,
    },
    "Label::rad_name": {
        "color": 0xFF47B3FF,
        "font_size": 12,
    },
    "Label::phase_sunlit": {
        "color": 0xFF82E57A,
        "font_size": 14,
    },
    "Label::phase_eclipse": {
        "color": 0xFF47B3FF,
        "font_size": 14,
    },
    "Rectangle::bar_bg": {
        "background_color": 0xFF1A2030,
        "border_radius": 3,
    },
    "Rectangle::bar_fill_green": {
        "background_color": 0xFF82E57A,
        "border_radius": 3,
    },
    "Rectangle::bar_fill_cyan": {
        "background_color": 0xFFD8B400,
        "border_radius": 3,
    },
    "Rectangle::bar_fill_orange": {
        "background_color": 0xFF47B3FF,
        "border_radius": 3,
    },
    "Rectangle::bar_fill_red": {
        "background_color": 0xFF6B6BFF,
        "border_radius": 3,
    },
    "Rectangle::separator": {
        "background_color": 0xFF2A3545,
    },
    "ScrollingFrame": {
        "background_color": 0xFF0C1422,
    },
}

# Helper: horizontal bar gauge
def _bar_gauge(fraction: float, width: float = 120, height: float = 10,
               fill_name: str = "bar_fill_green"):
    """Draw a simple horizontal bar with background + colored fill."""
    frac = max(0.0, min(1.0, fraction))
    with ui.ZStack(width=width, height=height):
        ui.Rectangle(name="bar_bg", width=width, height=height)
        ui.Rectangle(name=fill_name, width=width * frac, height=height)


class SatelliteStatusWindow:
    """
    Detailed satellite subsystem status window.
    Shows: orbit info, power subsystem, thermal subsystem, compute subsystem,
    per-wing solar array status, and per-radiator panel status.
    """

    def __init__(self, state: SimState):
        self._state = state
        self._window: Optional["ui.Window"] = None

        # ── Live label references ───────
        # Orbit & Phase
        self._lbl_phase: Optional["ui.Label"] = None
        self._lbl_target_name: Optional["ui.Label"] = None
        self._lbl_target_id: Optional["ui.Label"] = None
        self._lbl_target_source: Optional["ui.Label"] = None
        self._lbl_altitude: Optional["ui.Label"] = None
        self._lbl_inclination: Optional["ui.Label"] = None
        self._lbl_period: Optional["ui.Label"] = None
        self._lbl_eclipse_frac: Optional["ui.Label"] = None
        self._lbl_orbit_count: Optional["ui.Label"] = None

        # Power
        self._lbl_solar_pwr: Optional["ui.Label"] = None
        self._lbl_bat_soc: Optional["ui.Label"] = None
        self._lbl_rad_pwr: Optional["ui.Label"] = None
        self._bar_bat: Optional[dict] = None

        # Thermal
        self._lbl_gpu_temp: Optional["ui.Label"] = None
        self._lbl_arr_temp: Optional["ui.Label"] = None

        # Compute
        self._lbl_flops: Optional["ui.Label"] = None
        self._lbl_gpu_util: Optional["ui.Label"] = None
        self._lbl_workload: Optional["ui.Label"] = None

        # Per-wing labels
        self._wing_labels: List[dict] = []
        # Per-radiator labels
        self._rad_labels: List[dict] = []

        # Container frames for dynamic rebuild
        self._wing_frame: Optional["ui.Frame"] = None
        self._rad_frame: Optional["ui.Frame"] = None

        # Overall status
        self._lbl_overall: Optional["ui.Label"] = None

    # ── Build ───────────────────────────────────────────────

    def build(self):
        if not HAS_OMNI_UI:
            return

        self._window = ui.Window(
            "Satellite Status",
            width=460,
            height=700,
        )

        with self._window.frame:
            with ui.ScrollingFrame(style=STATUS_STYLE):
                with ui.VStack(spacing=6, style=STATUS_STYLE):
                    ui.Spacer(height=4)
                    self._build_header()
                    self._build_separator()
                    self._build_orbit_section()
                    self._build_separator()
                    self._build_power_section()
                    self._build_separator()
                    self._build_thermal_section()
                    self._build_separator()
                    self._build_compute_section()
                    self._build_separator()
                    self._build_wing_section()
                    self._build_separator()
                    self._build_radiator_section()
                    self._build_separator()
                    self._build_overall_status()
                    ui.Spacer(height=8)

    def destroy(self):
        if self._window:
            self._window.destroy()
            self._window = None

    # ── Section builders ────────────────────────────────────

    def _build_separator(self):
        ui.Rectangle(name="separator", height=1)

    def _build_header(self):
        ui.Label(
            "ORBITAL DC-1  //  Subsystem Status",
            name="title",
            alignment=ui.Alignment.CENTER,
            height=28,
        )
        self._lbl_phase = ui.Label(
            "SUNLIT PASS", name="phase_sunlit",
            alignment=ui.Alignment.CENTER, height=22,
        )

    def _build_orbit_section(self):
        ui.Label("ORBIT", name="section", height=20)
        with ui.VStack(spacing=2):
            self._lbl_target_name = self._kv_row("Target", "ORBITAL DC-1")
            self._lbl_target_id = self._kv_row("Target ID", "SIM-001")
            self._lbl_target_source = self._kv_row("Source", "Internal Orbit Model")
            self._lbl_altitude = self._kv_row("Altitude", "550.0 km")
            self._lbl_inclination = self._kv_row("Inclination", "97.6°")
            self._lbl_period = self._kv_row("Period", "95.7 min")
            self._lbl_eclipse_frac = self._kv_row("Eclipse Fraction", "36.0%")
            self._lbl_orbit_count = self._kv_row("Orbit #", "1")

    def _build_power_section(self):
        ui.Label("POWER SUBSYSTEM", name="section", height=20)
        with ui.VStack(spacing=2):
            self._lbl_solar_pwr = self._kv_row("Solar Output", "0 kW")
            self._lbl_rad_pwr = self._kv_row("Radiator Rejection", "0 kW")

            # Battery with bar
            with ui.HStack(height=18):
                ui.Label("Battery SOC", name="label", width=140)
                self._lbl_bat_soc = ui.Label("87%", name="value", width=60)
            # Bar gauge for battery
            self._bat_bar_fill = None
            with ui.ZStack(width=ui.Percent(100), height=12):
                ui.Rectangle(name="bar_bg", height=12)
                self._bat_bar_fill = ui.Rectangle(
                    name="bar_fill_green",
                    width=ui.Percent(87),
                    height=12,
                )

    def _build_thermal_section(self):
        ui.Label("THERMAL", name="section", height=20)
        with ui.VStack(spacing=2):
            self._lbl_gpu_temp = self._kv_row("GPU Temp", "76°C")
            self._lbl_arr_temp = self._kv_row("Array Temp", "62°C")

    def _build_compute_section(self):
        ui.Label("COMPUTE", name="section", height=20)
        with ui.VStack(spacing=2):
            self._lbl_flops = self._kv_row("Performance", "12.8 ExaFLOPS")
            self._lbl_gpu_util = self._kv_row("GPU Utilization", "92%")
            self._lbl_workload = self._kv_row("Workload", "—")

    def _build_wing_section(self):
        ui.Label("SOLAR WINGS", name="section", height=20)
        # Table header
        with ui.HStack(height=16):
            ui.Label("Name", name="header_col", width=50)
            ui.Label("Area m²", name="header_col", width=60)
            ui.Label("Temp °C", name="header_col", width=60)
            ui.Label("Eff %", name="header_col", width=50)
            ui.Label("Output kW", name="header_col", width=70)
            ui.Label("Status", name="header_col", width=70)

        self._wing_frame = ui.Frame(height=0)
        self._rebuild_wing_rows()

    def _build_radiator_section(self):
        ui.Label("RADIATOR PANELS", name="section", height=20)
        with ui.HStack(height=16):
            ui.Label("ID", name="header_col", width=40)
            ui.Label("Area m²", name="header_col", width=60)
            ui.Label("Temp °C", name="header_col", width=60)
            ui.Label("ε", name="header_col", width=40)
            ui.Label("VF", name="header_col", width=40)
            ui.Label("Q kW", name="header_col", width=60)
            ui.Label("Status", name="header_col", width=60)

        self._rad_frame = ui.Frame(height=0)
        self._rebuild_rad_rows()

    def _build_overall_status(self):
        self._lbl_overall = ui.Label(
            "● ALL SUBSYSTEMS NOMINAL",
            name="status_nominal",
            alignment=ui.Alignment.CENTER,
            height=28,
        )

    # ── Dynamic row builders ────────────────────────────────

    def _rebuild_wing_rows(self):
        """Rebuild solar wing rows when wing count changes."""
        if not self._wing_frame:
            return
        self._wing_labels.clear()
        with self._wing_frame:
            with ui.VStack(spacing=1):
                for w in self._state.wings:
                    row = {}
                    with ui.HStack(height=16):
                        row["name"] = ui.Label(w.name, name="wing_name", width=50)
                        row["area"] = ui.Label(f"{w.area:.0f}", name="value", width=60)
                        row["temp"] = ui.Label(f"{w.temp:.1f}", name="value", width=60)
                        row["eff"] = ui.Label(f"{w.efficiency * 100:.1f}", name="value", width=50)
                        row["output"] = ui.Label(f"{w.output:.1f}", name="value", width=70)
                        row["status"] = ui.Label("OK", name="status_nominal", width=70)
                    self._wing_labels.append(row)

    def _rebuild_rad_rows(self):
        """Rebuild radiator rows when radiator count changes."""
        if not self._rad_frame:
            return
        self._rad_labels.clear()
        with self._rad_frame:
            with ui.VStack(spacing=1):
                for rp in self._state.rad_panels:
                    row = {}
                    with ui.HStack(height=16):
                        row["id"] = ui.Label(f"R{rp.id}", name="rad_name", width=40)
                        row["area"] = ui.Label(f"{rp.area:.0f}", name="value", width=60)
                        row["temp"] = ui.Label(f"{rp.surf_temp:.1f}", name="value", width=60)
                        row["eps"] = ui.Label(f"{rp.emissivity:.2f}", name="value", width=40)
                        row["vf"] = ui.Label(f"{rp.view_factor:.2f}", name="value", width=40)
                        row["q"] = ui.Label(f"{rp.q_rad:.1f}", name="value", width=60)
                        row["status"] = ui.Label("OK", name="status_nominal", width=60)
                    self._rad_labels.append(row)

    # ── Helper ──────────────────────────────────────────────

    def _kv_row(self, label_text: str, default_value: str) -> "ui.Label":
        """Create a label: value row and return the value label for live update."""
        with ui.HStack(height=18):
            ui.Label(label_text, name="label", width=140)
            val_lbl = ui.Label(default_value, name="value")
        return val_lbl

    # ── Live update ─────────────────────────────────────────

    def update(self):
        """Called each UI tick to refresh all values."""
        if not HAS_OMNI_UI or not self._window:
            return

        s = self._state

        # Phase
        if self._lbl_phase:
            if s.eclipse:
                self._lbl_phase.text = "ECLIPSE PASS"
                self._lbl_phase.name = "phase_eclipse"
            else:
                self._lbl_phase.text = "SUNLIT PASS"
                self._lbl_phase.name = "phase_sunlit"

        # Orbit
        if self._lbl_target_name:
            self._lbl_target_name.text = s.tracked_satellite_name
        if self._lbl_target_id:
            self._lbl_target_id.text = s.tracked_satellite_id
        if self._lbl_target_source:
            self._lbl_target_source.text = s.tracked_satellite_source
        if self._lbl_altitude:
            self._lbl_altitude.text = f"{s.tracked_altitude_km:.1f} km"
        if self._lbl_inclination:
            self._lbl_inclination.text = f"{s.tracked_inclination_deg:.1f}°"
        if self._lbl_period:
            self._lbl_period.text = f"{s.tracked_period_s / 60:.1f} min"
        if self._lbl_eclipse_frac:
            self._lbl_eclipse_frac.text = f"{s.eclipse_fraction * 100:.1f}%"
        if self._lbl_orbit_count:
            self._lbl_orbit_count.text = f"{s.orbit_count}"

        # Power
        if self._lbl_solar_pwr:
            self._lbl_solar_pwr.text = f"{s.solar_pwr:.1f} kW"
        if self._lbl_rad_pwr:
            self._lbl_rad_pwr.text = f"{s.rad_pwr:.1f} kW"
        if self._lbl_bat_soc:
            soc = s.bat_soc
            self._lbl_bat_soc.text = f"{soc:.0f}%"
            if soc < 20:
                self._lbl_bat_soc.name = "value_danger"
            elif soc < 40:
                self._lbl_bat_soc.name = "value_warn"
            else:
                self._lbl_bat_soc.name = "value"

        # Battery bar
        if self._bat_bar_fill:
            self._bat_bar_fill.width = ui.Percent(max(1, min(100, s.bat_soc)))
            if s.bat_soc < 20:
                self._bat_bar_fill.name = "bar_fill_red"
            elif s.bat_soc < 40:
                self._bat_bar_fill.name = "bar_fill_orange"
            else:
                self._bat_bar_fill.name = "bar_fill_green"

        # Thermal
        if self._lbl_gpu_temp:
            self._lbl_gpu_temp.text = f"{s.gpu_temp:.1f}°C"
            if s.gpu_temp > 95:
                self._lbl_gpu_temp.name = "value_danger"
            elif s.gpu_temp > 85:
                self._lbl_gpu_temp.name = "value_warn"
            else:
                self._lbl_gpu_temp.name = "value"
        if self._lbl_arr_temp:
            self._lbl_arr_temp.text = f"{s.arr_temp:.1f}°C"

        # Compute
        if self._lbl_flops:
            self._lbl_flops.text = f"{s.flops:.1f} ExaFLOPS"
        if self._lbl_gpu_util:
            self._lbl_gpu_util.text = f"{s.gpu_util}%"
        if self._lbl_workload:
            self._lbl_workload.text = s.current_workload.replace("_", " ").title()

        # Per-wing update
        self._update_wing_rows()

        # Per-radiator update
        self._update_rad_rows()

        # Overall status
        self._update_overall_status()

    def _update_wing_rows(self):
        """Update per-wing label values."""
        wings = self._state.wings
        # If wing count changed, rebuild rows
        if len(self._wing_labels) != len(wings):
            self._rebuild_wing_rows()
            return

        for i, w in enumerate(wings):
            if i >= len(self._wing_labels):
                break
            row = self._wing_labels[i]
            row["area"].text = f"{w.area:.0f}"
            row["temp"].text = f"{w.temp:.1f}"
            row["eff"].text = f"{w.efficiency * 100:.1f}"
            row["output"].text = f"{w.output:.1f}"

            # Status based on temp and efficiency
            if w.temp > 120:
                row["status"].text = "OVERHEAT"
                row["status"].name = "status_danger"
                row["temp"].name = "value_danger"
            elif w.temp > 100:
                row["status"].text = "HOT"
                row["status"].name = "status_warn"
                row["temp"].name = "value_warn"
            else:
                row["status"].text = "OK"
                row["status"].name = "status_nominal"
                row["temp"].name = "value"

    def _update_rad_rows(self):
        """Update per-radiator label values."""
        panels = self._state.rad_panels
        if len(self._rad_labels) != len(panels):
            self._rebuild_rad_rows()
            return

        for i, rp in enumerate(panels):
            if i >= len(self._rad_labels):
                break
            row = self._rad_labels[i]
            row["area"].text = f"{rp.area:.0f}"
            row["temp"].text = f"{rp.surf_temp:.1f}"
            row["eps"].text = f"{rp.emissivity:.2f}"
            row["vf"].text = f"{rp.view_factor:.2f}"
            row["q"].text = f"{rp.q_rad:.1f}"

            if rp.surf_temp > 100:
                row["status"].text = "OVERHEAT"
                row["status"].name = "status_danger"
                row["temp"].name = "value_danger"
            elif rp.surf_temp > 80:
                row["status"].text = "WARM"
                row["status"].name = "status_warn"
                row["temp"].name = "value_warn"
            else:
                row["status"].text = "OK"
                row["status"].name = "status_nominal"
                row["temp"].name = "value"

    def _update_overall_status(self):
        """Determine overall satellite health."""
        if not self._lbl_overall:
            return
        s = self._state

        # Check for danger conditions
        dangers = []
        warnings = []

        if s.gpu_temp > 95:
            dangers.append("GPU OVERHEAT")
        elif s.gpu_temp > 85:
            warnings.append("GPU HOT")

        if s.bat_soc < 15:
            dangers.append("BATTERY CRITICAL")
        elif s.bat_soc < 30:
            warnings.append("BATTERY LOW")

        # Check wings
        for w in s.wings:
            if w.temp > 120:
                dangers.append(f"Wing {w.name} OVERHEAT")
                break
            elif w.temp > 100:
                warnings.append(f"Wing {w.name} HOT")
                break

        # Check radiators
        for rp in s.rad_panels:
            if rp.surf_temp > 100:
                dangers.append(f"Rad R{rp.id} OVERHEAT")
                break
            elif rp.surf_temp > 80:
                warnings.append(f"Rad R{rp.id} WARM")
                break

        if dangers:
            self._lbl_overall.text = f"▲ {dangers[0]}"
            self._lbl_overall.name = "status_danger"
        elif warnings:
            self._lbl_overall.text = f"◉ {warnings[0]}"
            self._lbl_overall.name = "status_warn"
        elif s.eclipse:
            self._lbl_overall.text = "◉ ECLIPSE MODE — NOMINAL"
            self._lbl_overall.name = "status_warn"
        else:
            self._lbl_overall.text = "● ALL SUBSYSTEMS NOMINAL"
            self._lbl_overall.name = "status_nominal"
