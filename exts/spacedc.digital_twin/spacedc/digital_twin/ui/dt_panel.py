"""
============================================================
  dt_panel.py — Digital Twin Control Panel (omni.ui)
  Migrated from: js/dt-controls.js + simulation.js DOM updates
============================================================

  Provides the main Digital Twin parameter control window using
  omni.ui widgets. All sliders / combo-boxes drive the SimState
  and trigger scene rebuilds.
"""
from __future__ import annotations

from typing import Callable, Optional

try:
    import omni.ui as ui
    HAS_OMNI_UI = True
except ImportError:
    HAS_OMNI_UI = False

from ..physics.constants import CELL_TECHS, COOLANTS, WORKLOADS, SIGMA
from ..physics.state import SimState
from ..physics.thermal_model import compute_peak_rad_capacity, check_thermal_feasibility
from ..physics.solar_array_model import compute_peak_solar

# ── Style tokens ────────────────────────────────────────────
PANEL_STYLE = {
    "Window": {"background_color": 0xFF0C1220},
    "Label": {"color": 0xFFAABBCC, "font_size": 13},
    "Label::header": {"color": 0xFF00D4FF, "font_size": 15},
    "Label::value": {"color": 0xFF39FF14, "font_size": 14},
    "Label::warn": {"color": 0xFFFFAA00, "font_size": 14},
    "Label::danger": {"color": 0xFFFF2244, "font_size": 14},
}


class DigitalTwinPanel:
    """
    The main Digital Twin control window.
    Mirrors all 7 DT controls from the web version:
      1. Solar wing count
      2. Solar wing area
      3. Cell technology
      4. Radiator panel count
      5. Radiator panel area / epsilon
      6. Coolant selection
      7. Workload selection
    """

    def __init__(
        self,
        state: SimState,
        on_rebuild: Optional[Callable] = None,
        on_state_change: Optional[Callable] = None,
    ):
        self._state = state
        self._on_rebuild = on_rebuild        # called when 3D model needs rebuild
        self._on_state_change = on_state_change
        self._window: Optional["ui.Window"] = None

        # Value label references for live update
        self._lbl_wing_count = None
        self._lbl_wing_area = None
        self._lbl_rad_count = None
        self._lbl_rad_area = None
        self._lbl_epsilon = None
        self._lbl_peak_solar = None
        self._lbl_peak_rad = None
        self._lbl_balance = None
        self._lbl_thermal = None
        self._lbl_period = None
        self._lbl_eclipse_frac = None
        self._lbl_sunlight = None

        # Speed button references
        self._speed_labels = {}

    def build(self):
        if not HAS_OMNI_UI:
            print("[SpaceDC] omni.ui not available — skipping DT panel")
            return

        self._window = ui.Window(
            "🛰️ SpaceDC Digital Twin",
            width=380,
            height=720,
        )
        with self._window.frame:
            with ui.ScrollingFrame():
                with ui.VStack(spacing=6, style=PANEL_STYLE):
                    self._build_header()
                    ui.Separator(height=2)
                    self._build_speed_controls()
                    ui.Separator(height=2)
                    self._build_orbit_section()  # <--- 新增
                    ui.Separator(height=2)
                    self._build_solar_section()
                    ui.Separator(height=2)
                    self._build_radiator_section()
                    ui.Separator(height=2)
                    self._build_workload_section()
                    ui.Separator(height=2)
                    self._build_summary_section()

    def destroy(self):
        if self._window:
            self._window.destroy()
            self._window = None

    # ── Section builders ────────────────────────────────────

    def _build_header(self):
        ui.Label(
            "ORBITAL DC-1 · Space Data Center",
            name="header",
            alignment=ui.Alignment.CENTER,
            height=28,
        )
        ui.Label(
            "Digital Twin Control Panel",
            alignment=ui.Alignment.CENTER,
            height=20,
        )

    def _build_speed_controls(self):
        ui.Label("⏱ Simulation Speed", height=20)
        with ui.HStack(height=24, spacing=4):
            for spd in [1, 10, 60, 600]:
                btn = ui.Button(
                    f"{spd}×",
                    width=60,
                    clicked_fn=lambda s=spd: self._set_speed(s),
                )

    def _build_orbit_section(self):
        ui.Label("🌍 Orbital Configuration", name="header", height=24)

        # Altitude input
        with ui.HStack(height=24, spacing=4):
            ui.Label("Altitude (km):", width=110)
            field_alt = ui.FloatField(width=90, height=22)
            field_alt.model.set_value(self._state.orbit_altitude)
            field_alt.model.add_end_edit_fn(self._on_altitude_edited)
            ui.Label("km", width=30)

        # Inclination input
        with ui.HStack(height=24, spacing=4):
            ui.Label("Inclination (°):", width=110)
            field_inc = ui.FloatField(width=90, height=22)
            field_inc.model.set_value(self._state.orbit_inclination)
            field_inc.model.add_end_edit_fn(self._on_inclination_edited)
            ui.Label("°", width=30)

        # Dynamic readouts
        with ui.VStack(spacing=2):
            with ui.HStack(height=18):
                ui.Label("Period:", width=120)
                self._lbl_period = ui.Label("—", name="value")
            with ui.HStack(height=18):
                ui.Label("Eclipse frac:", width=120)
                self._lbl_eclipse_frac = ui.Label("—", name="value")
            with ui.HStack(height=18):
                ui.Label("Sunlight:", width=120)
                self._lbl_sunlight = ui.Label("—", name="value")

        # Initialise readouts
        self._refresh_orbit_readouts()

    def _build_solar_section(self):
        ui.Label("☀ Solar Array Configuration", name="header", height=24)

        # Wing count slider
        with ui.HStack(height=22):
            ui.Label("Wings:", width=90)
            self._lbl_wing_count = ui.Label(
                str(self._state.wing_count), name="value", width=40
            )
        slider_wc = ui.IntSlider(min=2, max=12, step=1, height=20)
        slider_wc.model.set_value(self._state.wing_count)
        slider_wc.model.add_value_changed_fn(self._on_wing_count_changed)

        # Wing area slider
        with ui.HStack(height=22):
            ui.Label("Wing Area:", width=90)
            self._lbl_wing_area = ui.Label(
                f"{int(self._state.wing_area)} m²", name="value", width=80
            )
        slider_wa = ui.IntSlider(min=50, max=500, step=10, height=20)
        slider_wa.model.set_value(int(self._state.wing_area))
        slider_wa.model.add_value_changed_fn(self._on_wing_area_changed)

        # Cell technology
        with ui.HStack(height=22):
            ui.Label("Cell Tech:", width=90)
        tech_names = [CELL_TECHS[k]["name"] for k in CELL_TECHS]
        tech_keys = list(CELL_TECHS.keys())
        combo_tech = ui.ComboBox(
            tech_keys.index(self._state.current_cell_tech),
            *tech_names,
            height=22,
        )
        combo_tech.model.add_item_changed_fn(
            lambda m, _: self._on_cell_tech_changed(tech_keys[m.get_item_value_model().as_int])
        )

    def _build_radiator_section(self):
        ui.Label("🌡 Radiative Cooling Configuration", name="header", height=24)

        # Rad panel count
        with ui.HStack(height=22):
            ui.Label("Panels:", width=90)
            self._lbl_rad_count = ui.Label(
                str(self._state.rad_count), name="value", width=40
            )
        slider_rc = ui.IntSlider(min=2, max=10, step=1, height=20)
        slider_rc.model.set_value(self._state.rad_count)
        slider_rc.model.add_value_changed_fn(self._on_rad_count_changed)

        # Rad panel area
        with ui.HStack(height=22):
            ui.Label("Panel Area:", width=90)
            self._lbl_rad_area = ui.Label(
                f"{int(self._state.rad_area)} m²", name="value", width=80
            )
        slider_ra = ui.IntSlider(min=50, max=300, step=5, height=20)
        slider_ra.model.set_value(int(self._state.rad_area))
        slider_ra.model.add_value_changed_fn(self._on_rad_area_changed)

        # Emissivity (epsilon)
        with ui.HStack(height=22):
            ui.Label("Emissivity ε:", width=90)
            self._lbl_epsilon = ui.Label(
                f"{self._state.rad_epsilon:.2f}", name="value", width=60
            )
        slider_eps = ui.IntSlider(min=50, max=99, step=1, height=20)
        slider_eps.model.set_value(int(self._state.rad_epsilon * 100))
        slider_eps.model.add_value_changed_fn(self._on_epsilon_changed)

        # Coolant
        with ui.HStack(height=22):
            ui.Label("Coolant:", width=90)
        cool_names = [COOLANTS[k]["name"] for k in COOLANTS]
        cool_keys = list(COOLANTS.keys())
        combo_cool = ui.ComboBox(
            cool_keys.index(self._state.current_coolant),
            *cool_names,
            height=22,
        )
        combo_cool.model.add_item_changed_fn(
            lambda m, _: self._on_coolant_changed(cool_keys[m.get_item_value_model().as_int])
        )

    def _build_workload_section(self):
        ui.Label("🖥 Compute Workload", name="header", height=24)

        wl_names = [WORKLOADS[k]["name"] for k in WORKLOADS]
        wl_keys = list(WORKLOADS.keys())
        combo_wl = ui.ComboBox(
            wl_keys.index(self._state.current_workload),
            *wl_names,
            height=22,
        )
        combo_wl.model.add_item_changed_fn(
            lambda m, _: self._on_workload_changed(wl_keys[m.get_item_value_model().as_int])
        )

        self._lbl_thermal = ui.Label("", name="value", height=20)

    def _build_summary_section(self):
        ui.Label("📊 System Summary", name="header", height=24)

        with ui.VStack(spacing=3):
            with ui.HStack(height=18):
                ui.Label("Peak Solar:", width=120)
                self._lbl_peak_solar = ui.Label("—", name="value")
            with ui.HStack(height=18):
                ui.Label("Peak Rad:", width=120)
                self._lbl_peak_rad = ui.Label("—", name="value")
            with ui.HStack(height=18):
                ui.Label("Power Balance:", width=120)
                self._lbl_balance = ui.Label("—", name="value")

        self._update_summary()

    # ── Event handlers ──────────────────────────────────────

    def _set_speed(self, speed: int):
        self._state.speed = speed
        self._notify_change()

    def _on_wing_count_changed(self, model):
        self._state.wing_count = model.as_int
        self._state.rebuild_wings()
        if self._lbl_wing_count:
            self._lbl_wing_count.text = str(self._state.wing_count)
        self._trigger_rebuild()
        self._update_summary()

    def _on_wing_area_changed(self, model):
        self._state.wing_area = float(model.as_int)
        self._state.rebuild_wings()
        if self._lbl_wing_area:
            self._lbl_wing_area.text = f"{int(model.get_value_as_int())} m²"
        self._notify_change()

    def _on_cell_tech_changed(self, key: str):
        self._state.current_cell_tech = key
        self._state.rebuild_wings()
        self._trigger_rebuild()
        self._update_summary()

    def _on_rad_count_changed(self, model):
        self._state.rad_count = model.as_int
        self._state.rebuild_rad_panels()
        if self._lbl_rad_count:
            self._lbl_rad_count.text = str(self._state.rad_count)
        self._trigger_rebuild()
        self._update_summary()

    def _on_rad_area_changed(self, model):
        self._state.rad_area = float(model.as_int)
        self._state.rebuild_rad_panels()
        if self._lbl_rad_area:
            self._lbl_rad_area.text = f"{int(self._state.rad_area)} m²"
        self._trigger_rebuild()
        self._update_summary()

    def _on_epsilon_changed(self, model):
        self._state.rad_epsilon = model.as_int / 100.0
        for p in self._state.rad_panels:
            p.emissivity = self._state.rad_epsilon
        if self._lbl_epsilon:
            self._lbl_epsilon.text = f"{self._state.rad_epsilon:.2f}"
        self._update_summary()
        self._notify_change()

    def _on_coolant_changed(self, key: str):
        self._state.current_coolant = key
        self._trigger_rebuild()
        self._update_summary()

    def _on_workload_changed(self, key: str):
        self._state.current_workload = key
        self._update_summary()
        self._notify_change()

    def _on_altitude_edited(self, model):
        val = model.get_value_as_float()
        val = max(160.0, min(36000.0, val))   # clamp LEO→GEO
        model.set_value(val)
        self._state.update_orbit_params(val, self._state.orbit_inclination)
        self._refresh_orbit_readouts()
        self._update_summary()
        self._notify_change()
        # Rebuild the 3-D orbit ring to match new radius
        if self._on_rebuild:
            self._on_rebuild()

    def _on_inclination_edited(self, model):
        val = model.get_value_as_float()
        val = max(0.0, min(180.0, val))
        model.set_value(val)
        self._state.update_orbit_params(self._state.orbit_altitude, val)
        self._refresh_orbit_readouts()
        self._notify_change()
        if self._on_rebuild:
            self._on_rebuild()

    def _refresh_orbit_readouts(self):
        """Update the Period / Eclipse / Sunlight labels from current state."""
        s = self._state
        period_min = s.orbit_period / 60.0
        eclipse_pct = s.eclipse_fraction * 100.0
        sunlight_pct = (1.0 - s.eclipse_fraction) * 100.0
        if self._lbl_period:
            self._lbl_period.text = f"{period_min:.1f} min"
        if hasattr(self, "_lbl_eclipse_frac") and self._lbl_eclipse_frac:
            self._lbl_eclipse_frac.text = f"{eclipse_pct:.1f}%"
        if self._lbl_sunlight:
            self._lbl_sunlight.text = f"{sunlight_pct:.1f}%"

    # ── Helpers ──────────────────────────────────────────────

    def _trigger_rebuild(self):
        self._notify_change()
        if self._on_rebuild:
            self._on_rebuild()

    def _notify_change(self):
        if self._on_state_change:
            self._on_state_change()

    def _update_summary(self):
        s = self._state

        peak_solar = compute_peak_solar(s.wing_count, s.wing_area, s.current_cell_tech)
        peak_rad = compute_peak_rad_capacity(
            s.rad_count, s.rad_area, s.rad_epsilon, s.current_coolant
        )
        wl = WORKLOADS[s.current_workload]
        compute_load = wl["totalComputekW"]
        heat_load = compute_load * wl["heatFraction"]
        balance = peak_solar - compute_load

        if self._lbl_peak_solar:
            self._lbl_peak_solar.text = f"{peak_solar:.1f} kW"
        if self._lbl_peak_rad:
            self._lbl_peak_rad.text = f"{peak_rad:.0f} kW"
        if self._lbl_balance:
            if balance > 0:
                self._lbl_balance.text = f"+{balance:.0f} kW surplus"
                self._lbl_balance.name = "value"
            else:
                self._lbl_balance.text = f"{balance:.0f} kW DEFICIT"
                self._lbl_balance.name = "danger"

        # Thermal feasibility
        status, ratio, msg = check_thermal_feasibility(heat_load, peak_rad)
        if self._lbl_thermal:
            self._lbl_thermal.text = msg
            self._lbl_thermal.name = (
                "value" if status == "ok" else ("warn" if status == "warn" else "danger")
            )

        # Orbit readouts are updated by _refresh_orbit_readouts() — no duplication here
