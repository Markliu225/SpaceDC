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
from ..physics.business_network import BUSINESS_WORKLOADS
from ..physics.state import SimState
from ..physics.thermal_model import compute_peak_rad_capacity, check_thermal_feasibility
from ..physics.solar_array_model import compute_peak_solar

# ── Unified dark-space style ────────────────────────────────
PANEL_STYLE = {
    "Window": {"background_color": 0xFF0A1018},
    "Label":           {"color": 0xFFB0C4D8, "font_size": 13},
    "Label::header":   {"color": 0xFF00B4D8, "font_size": 14},
    "Label::value":    {"color": 0xFF7AE582, "font_size": 13},
    "Label::warn":     {"color": 0xFFFFB347, "font_size": 13},
    "Label::danger":   {"color": 0xFFFF6B6B, "font_size": 13},
    "Label::muted":    {"color": 0xFF607080, "font_size": 12},
    "Button":          {"background_color": 0xFF142030, "color": 0xFFB0C4D8,
                        "border_color": 0xFF1E3448, "border_width": 1,
                        "border_radius": 4, "font_size": 13},
    "Button:hovered":  {"background_color": 0xFF1A2A40, "border_color": 0xFF00B4D8},
    "Separator":       {"color": 0xFF1A2A3A},
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
        on_view_toggle: Optional[Callable] = None,
        on_load_constellation: Optional[Callable] = None,
        on_load_sdc_demo: Optional[Callable] = None,
        on_clear_constellation: Optional[Callable] = None,
        on_load_business_constellation: Optional[Callable] = None,
        on_clear_business_constellation: Optional[Callable] = None,
        on_assign_business_workload: Optional[Callable] = None,
        on_clear_business_workload: Optional[Callable] = None,
        on_apply_topology_preset: Optional[Callable] = None,
        on_add_topology_link: Optional[Callable] = None,
        on_remove_topology_link: Optional[Callable] = None,
        on_clear_topology: Optional[Callable] = None,
        default_constellation_path: str = "",
        default_business_path: str = "",
    ):
        self._state = state
        self._on_rebuild = on_rebuild        # called when 3D model needs rebuild
        self._on_state_change = on_state_change
        self._on_view_toggle = on_view_toggle  # called to switch orbit/satellite view
        self._on_load_constellation = on_load_constellation
        self._on_load_sdc_demo = on_load_sdc_demo
        self._on_clear_constellation = on_clear_constellation
        self._on_load_business_constellation = on_load_business_constellation
        self._on_clear_business_constellation = on_clear_business_constellation
        self._on_assign_business_workload = on_assign_business_workload
        self._on_clear_business_workload = on_clear_business_workload
        self._on_apply_topology_preset = on_apply_topology_preset
        self._on_add_topology_link = on_add_topology_link
        self._on_remove_topology_link = on_remove_topology_link
        self._on_clear_topology = on_clear_topology
        self._default_constellation_path = default_constellation_path
        self._default_business_path = default_business_path
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
        self._lbl_phase = None
        self._lbl_target = None
        self._lbl_source = None
        self._lbl_met = None
        self._lbl_speed = None
        self._lbl_battery = None
        self._lbl_solar_live = None
        self._lbl_gpu = None

        # View toggle button reference
        self._view_btn = None
        self._constellation_path_field = None
        self._business_path_field = None
        self._business_sat_field = None
        self._business_workload_combo = None
        self._topology_source_field = None
        self._topology_target_field = None
        self._lbl_business_available = None
        self._lbl_business_links = None
        self._lbl_business_status = None
        self._lbl_business_count = None
        self._lbl_topology_available = None
        self._lbl_topology_links = None
        self._lbl_topology_status = None
        self._lbl_topology_count = None
        self._business_workload_keys = list(BUSINESS_WORKLOADS.keys())
        self._business_available_text = "Load business TLE to configure workloads."
        self._business_links_text = "No active demand links."
        self._business_status_text = "Business orchestration idle."
        self._business_link_count = 0
        self._topology_available_text = "Load a constellation to author topology."
        self._topology_links_text = "No active links."
        self._topology_status_text = "Topology idle."
        self._topology_link_count = 0

    def build(self):
        if not HAS_OMNI_UI:
            print("[SpaceDC] omni.ui not available — skipping DT panel")
            return

        self._window = ui.Window(
            "SpaceDC Digital Twin",
            width=340,
            height=680,
        )
        with self._window.frame:
            with ui.ScrollingFrame():
                with ui.VStack(spacing=6, style=PANEL_STYLE):
                    self._build_header()
                    ui.Separator(height=2)
                    self._build_overview_section()
                    ui.Separator(height=2)
                    self._build_controls_section()
                    ui.Separator(height=2)
                    self._build_orbit_section()  # <--- 新增
                    ui.Separator(height=2)
                    self._build_constellation_section()
                    ui.Separator(height=2)
                    self._build_business_section()
                    ui.Separator(height=2)
                    self._build_topology_section()
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
            "ORBITAL DC-1  //  Space Data Center",
            name="header",
            alignment=ui.Alignment.CENTER,
            height=28,
        )
        ui.Label(
            "Digital Twin Control Panel",
            name="muted",
            alignment=ui.Alignment.CENTER,
            height=20,
        )

    def _build_overview_section(self):
        ui.Label("MISSION OVERVIEW", name="header", height=20)
        with ui.VStack(spacing=3):
            with ui.HStack(height=18):
                ui.Label("Phase:", width=58)
                self._lbl_phase = ui.Label("SUNLIT PASS", name="value")
            with ui.HStack(height=18):
                ui.Label("Target:", width=58)
                self._lbl_target = ui.Label(self._state.tracked_satellite_name, name="value")
            with ui.HStack(height=18):
                ui.Label("Source:", width=58)
                self._lbl_source = ui.Label(self._state.tracked_satellite_source, name="muted")
            with ui.HStack(height=18):
                ui.Label("MET:", width=58)
                self._lbl_met = ui.Label(self._format_met(self._state.met_seconds), name="value")
            with ui.HStack(height=18):
                ui.Label("Speed:", width=58)
                self._lbl_speed = ui.Label(f"{self._state.speed}x", name="value")
            with ui.HStack(height=18):
                ui.Label("Battery:", width=58)
                self._lbl_battery = ui.Label(f"{self._state.bat_soc:.0f}%", name="value")
            with ui.HStack(height=18):
                ui.Label("Solar:", width=58)
                self._lbl_solar_live = ui.Label(f"{self._state.solar_pwr:.0f} kW", name="value")
            with ui.HStack(height=18):
                ui.Label("Compute:", width=58)
                self._lbl_gpu = ui.Label(
                    f"{self._state.gpu_util}% / {self._state.gpu_temp:.0f} C",
                    name="value",
                )

    def _build_controls_section(self):
        ui.Label("MISSION CONTROLS", name="header", height=20)
        with ui.HStack(height=28, spacing=4):
            self._view_btn = ui.Button(
                "Satellite Close-up",
                height=26,
                width=150,
                clicked_fn=self._on_view_btn_clicked,
            )
            for spd in [1, 10, 60]:
                ui.Button(
                    f"{spd}x",
                    width=38,
                    clicked_fn=lambda s=spd: self._set_speed(s),
                )

    def _on_view_btn_clicked(self):
        """Handle view toggle button click."""
        if self._on_view_toggle:
            new_mode = self._on_view_toggle()
            if self._view_btn and new_mode:
                if new_mode == "satellite":
                    self._view_btn.text = "Orbit Overview"
                else:
                    self._view_btn.text = "Satellite Close-up"

    def _get_constellation_path(self) -> str:
        if not self._constellation_path_field:
            return self._default_constellation_path
        try:
            return self._constellation_path_field.model.get_value_as_string()
        except Exception:
            return self._default_constellation_path

    def _on_load_constellation_clicked(self):
        if self._on_load_constellation:
            path = self._get_constellation_path().strip()
            if path:
                self._on_load_constellation(path)

    def _on_load_sample_constellation_clicked(self):
        if self._on_load_sdc_demo:
            self._on_load_sdc_demo()

    def _on_clear_constellation_clicked(self):
        if self._on_clear_constellation:
            self._on_clear_constellation()

    def _get_business_path(self) -> str:
        if not self._business_path_field:
            return self._default_business_path
        try:
            return self._business_path_field.model.get_value_as_string()
        except Exception:
            return self._default_business_path

    def _on_load_business_constellation_clicked(self):
        if self._on_load_business_constellation:
            path = self._get_business_path().strip()
            if path:
                self._on_load_business_constellation(path)

    def _on_clear_business_constellation_clicked(self):
        if self._on_clear_business_constellation:
            self._on_clear_business_constellation()

    def _get_selected_business_workload_key(self) -> str:
        if not self._business_workload_combo or not self._business_workload_keys:
            return self._business_workload_keys[0] if self._business_workload_keys else ""
        try:
            index = self._business_workload_combo.model.get_item_value_model().as_int
        except Exception:
            index = 0
        index = max(0, min(index, len(self._business_workload_keys) - 1))
        return self._business_workload_keys[index]

    def _on_assign_business_workload_clicked(self):
        if self._on_assign_business_workload:
            self._on_assign_business_workload(
                self._get_topology_field_value(self._business_sat_field),
                self._get_selected_business_workload_key(),
            )

    def _on_clear_business_workload_clicked(self):
        if self._on_clear_business_workload:
            self._on_clear_business_workload(
                self._get_topology_field_value(self._business_sat_field),
            )

    def _build_speed_controls(self):
        ui.Label("SIMULATION SPEED", name="header", height=20)
        with ui.HStack(height=24, spacing=4):
            for spd in [1, 10, 60, 600]:
                btn = ui.Button(
                    f"{spd}×",
                    width=60,
                    clicked_fn=lambda s=spd: self._set_speed(s),
                )

    def _build_orbit_section(self):
        return

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

    def _build_constellation_section(self):
        ui.Label("CONSTELLATION", name="header", height=24)
        ui.Label("Compute TLE", name="muted", height=18)
        if hasattr(ui, "StringField"):
            self._constellation_path_field = ui.StringField(height=22, width=300)
            if self._default_constellation_path:
                self._constellation_path_field.model.set_value(self._default_constellation_path)
        else:
            ui.Label(
                self._clip_text(self._default_constellation_path or "Use Load Sample", 40),
                name="muted",
            )

        with ui.HStack(height=26, spacing=4):
            ui.Button("Load File", width=96, clicked_fn=self._on_load_constellation_clicked)
            ui.Button("Sample", width=96, clicked_fn=self._on_load_sample_constellation_clicked)
            ui.Button("Clear", width=96, clicked_fn=self._on_clear_constellation_clicked)

    def _build_business_section(self):
        ui.Label("BUSINESS SATELLITES", name="header", height=24)
        ui.Label("Business TLE", name="muted", height=18)
        if hasattr(ui, "StringField"):
            self._business_path_field = ui.StringField(height=22, width=300)
            if self._default_business_path:
                self._business_path_field.model.set_value(self._default_business_path)
        else:
            ui.Label(self._clip_text(self._default_business_path or "Use sample business TLE", 40), name="muted")

        with ui.HStack(height=26, spacing=4):
            ui.Button("Load Biz TLE", width=148, clicked_fn=self._on_load_business_constellation_clicked)
            ui.Button("Clear Biz", width=148, clicked_fn=self._on_clear_business_constellation_clicked)

        ui.Label("Business Nodes", name="muted", height=18)
        self._lbl_business_available = ui.Label(self._business_available_text, name="muted", height=18)

        if hasattr(ui, "StringField"):
            ui.Label("Satellite ID", name="muted", height=18)
            self._business_sat_field = ui.StringField(width=300, height=22)
            ui.Label("Workload", name="muted", height=18)
            workload_names = [BUSINESS_WORKLOADS[key].name for key in self._business_workload_keys]
            self._business_workload_combo = ui.ComboBox(0, *workload_names, width=300, height=22)
        else:
            ui.Label("Manual business workload assignment unavailable in this UI build.", name="warn", height=20)

        with ui.HStack(height=24, spacing=4):
            ui.Button("Set Workload", width=148, clicked_fn=self._on_assign_business_workload_clicked)
            ui.Button("Clear Workload", width=148, clicked_fn=self._on_clear_business_workload_clicked)

        with ui.HStack(height=18):
            ui.Label("Links:", width=48)
            self._lbl_business_count = ui.Label(str(self._business_link_count), name="value")
        ui.Label("Routing", name="muted", height=18)
        self._lbl_business_links = ui.Label(self._business_links_text, name="muted", height=32)
        ui.Label("Status", name="muted", height=18)
        self._lbl_business_status = ui.Label(self._business_status_text, name="value", height=18)

    def _build_topology_section(self):
        ui.Label("NETWORK TOPOLOGY", name="header", height=24)
        ui.Label("Available", name="muted", height=18)
        self._lbl_topology_available = ui.Label(self._topology_available_text, name="muted", height=18)

        with ui.HStack(height=24, spacing=4):
            ui.Button("Ring", width=148, clicked_fn=lambda: self._on_topology_preset_clicked("ring"))
            ui.Button("Chain", width=148, clicked_fn=lambda: self._on_topology_preset_clicked("chain"))
        with ui.HStack(height=24, spacing=4):
            ui.Button("Star", width=148, clicked_fn=lambda: self._on_topology_preset_clicked("star"))
            ui.Button("Mesh", width=148, clicked_fn=lambda: self._on_topology_preset_clicked("mesh"))

        if hasattr(ui, "StringField"):
            ui.Label("Link Endpoint A", name="muted", height=18)
            self._topology_source_field = ui.StringField(width=300, height=22)
            ui.Label("Link Endpoint B", name="muted", height=18)
            self._topology_target_field = ui.StringField(width=300, height=22)
        else:
            ui.Label("Manual link entry unavailable in this UI build.", name="warn", height=20)

        with ui.HStack(height=24, spacing=4):
            ui.Button("Add Link", width=148, clicked_fn=self._on_add_topology_link_clicked)
            ui.Button("Remove Link", width=148, clicked_fn=self._on_remove_topology_link_clicked)
        ui.Button("Clear All", width=300, height=24, clicked_fn=self._on_clear_topology_clicked)

        with ui.HStack(height=18):
            ui.Label("Count:", width=48)
            self._lbl_topology_count = ui.Label(str(self._topology_link_count), name="value")
        ui.Label("Links", name="muted", height=18)
        self._lbl_topology_links = ui.Label(self._topology_links_text, name="muted", height=32)
        ui.Label("Status", name="muted", height=18)
        self._lbl_topology_status = ui.Label(self._topology_status_text, name="value", height=18)

    def _build_solar_section(self):
        ui.Label("SATELLITE DESIGN", name="header", height=24)
        ui.Label("Solar Array", name="muted", height=18)

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
        ui.Label("Thermal Control", name="muted", height=18)

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
        ui.Label("Compute Workload", name="muted", height=18)

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
        ui.Label("DESIGN SUMMARY", name="header", height=24)

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
        if self._lbl_speed:
            self._lbl_speed.text = f"{speed}x"
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
        self._trigger_rebuild()
        self._update_summary()

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

    def update_topology_info(
        self,
        available_text: str,
        links_text: str,
        status_text: str,
        link_count: int,
    ):
        self._topology_available_text = self._clip_text(available_text, 42)
        self._topology_links_text = self._clip_text(links_text, 42)
        self._topology_status_text = self._clip_text(status_text, 42)
        self._topology_link_count = link_count
        if self._lbl_topology_available:
            self._lbl_topology_available.text = self._topology_available_text
        if self._lbl_topology_links:
            self._lbl_topology_links.text = self._topology_links_text
        if self._lbl_topology_status:
            self._lbl_topology_status.text = self._topology_status_text
        if self._lbl_topology_count:
            self._lbl_topology_count.text = str(link_count)

    def update_business_info(
        self,
        available_text: str,
        links_text: str,
        status_text: str,
        link_count: int,
    ):
        self._business_available_text = self._clip_text(available_text, 42)
        self._business_links_text = self._clip_text(links_text, 42)
        self._business_status_text = self._clip_text(status_text, 42)
        self._business_link_count = link_count
        if self._lbl_business_available:
            self._lbl_business_available.text = self._business_available_text
        if self._lbl_business_links:
            self._lbl_business_links.text = self._business_links_text
        if self._lbl_business_status:
            self._lbl_business_status.text = self._business_status_text
        if self._lbl_business_count:
            self._lbl_business_count.text = str(link_count)

    def _get_topology_field_value(self, field) -> str:
        if not field:
            return ""
        try:
            return field.model.get_value_as_string().strip()
        except Exception:
            return ""

    def _on_topology_preset_clicked(self, preset_key: str):
        if self._on_apply_topology_preset:
            self._on_apply_topology_preset(preset_key)

    def _on_add_topology_link_clicked(self):
        if self._on_add_topology_link:
            self._on_add_topology_link(
                self._get_topology_field_value(self._topology_source_field),
                self._get_topology_field_value(self._topology_target_field),
            )

    def _on_remove_topology_link_clicked(self):
        if self._on_remove_topology_link:
            self._on_remove_topology_link(
                self._get_topology_field_value(self._topology_source_field),
                self._get_topology_field_value(self._topology_target_field),
            )

    def _on_clear_topology_clicked(self):
        if self._on_clear_topology:
            self._on_clear_topology()

    def _trigger_rebuild(self):
        self._notify_change()
        if self._on_rebuild:
            self._on_rebuild()

    def _notify_change(self):
        if self._on_state_change:
            self._on_state_change()

    def update_live_status(self):
        if not HAS_OMNI_UI or not self._window:
            return

        s = self._state
        if self._lbl_phase:
            self._lbl_phase.text = "ECLIPSE PASS" if s.eclipse else "SUNLIT PASS"
            self._lbl_phase.name = "warn" if s.eclipse else "value"
        if self._lbl_target:
            label = s.tracked_satellite_name or "ORBITAL DC-1"
            if s.tracked_satellite_id and s.tracked_satellite_id != "SIM-001":
                label = f"{label} ({s.tracked_satellite_id})"
            self._lbl_target.text = self._clip_text(label, 34)
        if self._lbl_source:
            self._lbl_source.text = self._clip_text(s.tracked_satellite_source, 34)
        if self._lbl_met:
            self._lbl_met.text = self._format_met(s.met_seconds)
        if self._lbl_speed:
            self._lbl_speed.text = f"{s.speed}x"
        if self._lbl_battery:
            self._lbl_battery.text = f"{s.bat_soc:.0f}%"
            self._lbl_battery.name = "danger" if s.bat_soc < 20 else ("warn" if s.bat_soc < 35 else "value")
        if self._lbl_solar_live:
            self._lbl_solar_live.text = f"{s.solar_pwr:.0f} kW"
        if self._lbl_gpu:
            self._lbl_gpu.text = f"{s.gpu_util}% / {s.gpu_temp:.0f} C"
            self._lbl_gpu.name = "danger" if s.gpu_temp > 95 else ("warn" if s.gpu_temp > 85 else "value")

    @staticmethod
    def _format_met(seconds: float) -> str:
        total = max(0, int(seconds))
        hours = total // 3600
        minutes = (total % 3600) // 60
        secs = total % 60
        return f"T+{hours:03d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def _clip_text(text: str, limit: int) -> str:
        value = str(text or "").strip()
        if len(value) <= limit:
            return value
        return value[: max(0, limit - 1)] + "…"

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
