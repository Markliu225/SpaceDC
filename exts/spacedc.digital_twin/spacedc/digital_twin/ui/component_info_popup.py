"""
============================================================
  component_info_popup.py — Click-to-inspect satellite component
============================================================

  When the user clicks a satellite sub-prim in the viewport, a
  floating info card appears showing the component name, category,
  static specs, and live telemetry values pulled from SimState.

  Uses ``omni.usd.get_context().get_selection()`` change events
  (Kit's native viewport pick → USD selection pipeline).
"""
from __future__ import annotations

from typing import Optional, List, Tuple

try:
    import omni.ui as ui
    import omni.usd
    HAS_KIT = True
except ImportError:
    HAS_KIT = False

from ..physics.state import SimState
from ..physics.constants import CELL_TECHS, COOLANTS, WORKLOADS


# ── Style ───────────────────────────────────────────────────
_POPUP_STYLE = {
    "Window": {"background_color": 0xEE18140A, "border_color": 0xFFD8B400,
               "border_width": 1.5, "border_radius": 6},
    "Label::title":  {"color": 0xFFD8B400, "font_size": 16},
    "Label::key":    {"color": 0xFFD8C4B0, "font_size": 13},
    "Label::val":    {"color": 0xFF82E57A, "font_size": 13},
    "Label::desc":   {"color": 0xFF807060, "font_size": 12},
    "Label::close":  {"color": 0xFF6B6BFF, "font_size": 14},
}

# ── Prim-path → component category mapping ─────────────────
# We match on the first path segment under /World/Satellite/

_COMPONENT_MAP = {
    "Bus":          ("Main Bus (Server Rack)",      "bus"),
    "GoldBand":     ("Gold MLI Thermal Band",       "bus"),
    "ServerFace":   ("Server Face / Grille",        "bus"),
    "SolarWings":   ("Solar Array Wing",            "solar"),
    "Radiators":    ("Radiator Panel",              "radiator"),
    "Antenna":      ("High-Gain Antenna",           "antenna"),
    "StarTracker":  ("Star Tracker",                "star_tracker"),
    "Thruster":     ("Thruster Nozzle",             "thruster"),
    "DockingRing":  ("Docking Ring",                "docking"),
}


class ComponentInfoPopup:
    """
    Listens for USD selection changes.  When a prim under
    ``/World/Satellite`` is selected, shows a floating info card.
    """

    def __init__(self, state: SimState):
        self._state = state
        self._window: Optional[ui.Window] = None
        self._sel_sub = None
        self._value_labels: dict = {}
        self._current_category: Optional[str] = None
        self._update_sub = None

    # ── lifecycle ───────────────────────────────────────────

    def start(self):
        """Subscribe to USD selection-changed events."""
        if not HAS_KIT:
            return
        ctx = omni.usd.get_context()
        events = ctx.get_stage_event_stream()
        self._sel_sub = events.create_subscription_to_pop_by_type(
            int(omni.usd.StageEventType.SELECTION_CHANGED),
            self._on_selection_changed,
            name="spacedc.component_info",
        )
        print("[SpaceDC] ComponentInfoPopup: listening for selection changes")

    def destroy(self):
        self._sel_sub = None
        self._update_sub = None
        if self._window:
            self._window.destroy()
            self._window = None

    # ── Selection handler ───────────────────────────────────

    def _on_selection_changed(self, event):
        """Called when the user clicks in the viewport and selection changes."""
        ctx = omni.usd.get_context()
        sel = ctx.get_selection()
        paths: List[str] = sel.get_selected_prim_paths()

        if not paths:
            self._hide()
            return

        # Take the first selected prim
        prim_path: str = paths[0]

        # Only care about satellite sub-prims
        if not prim_path.startswith("/World/Satellite/"):
            self._hide()
            return

        # Resolve component category from path
        info = self._resolve_component(prim_path)
        if info is None:
            self._hide()
            return

        title, category, sub_label = info
        self._current_category = category
        self._show(title, category, sub_label, prim_path)

    # ── Path resolution ─────────────────────────────────────

    def _resolve_component(self, prim_path: str) -> Optional[Tuple[str, str, str]]:
        """
        Map a full prim path like ``/World/Satellite/SolarWings/Left/Wing_2/Panel_1``
        to (display_title, category_key, sub_label).
        """
        # Strip prefix
        rel = prim_path.replace("/World/Satellite/", "")
        parts = rel.split("/")
        top = parts[0]

        # Exact key match
        if top in _COMPONENT_MAP:
            title, cat = _COMPONENT_MAP[top]
            return title, cat, rel

        # Prefix match (StarTracker_0, Thruster_2, …)
        for prefix, (title, cat) in _COMPONENT_MAP.items():
            if top.startswith(prefix):
                return title, cat, rel

        # Deep match: user clicked a child (e.g. SolarWings/Left/Wing_0/Panel_1)
        # — walk up until we find a match
        for prefix, (title, cat) in _COMPONENT_MAP.items():
            if rel.startswith(prefix):
                return title, cat, rel

        return None

    # ── Build / refresh the popup window ────────────────────

    def _show(self, title: str, category: str, sub_label: str, prim_path: str):
        """Build or refresh the floating info card."""
        self._value_labels.clear()

        if self._window:
            self._window.destroy()

        self._window = ui.Window(
            title,
            width=360,
            height=0,           # auto-height
            flags=(
                ui.WINDOW_FLAGS_NO_RESIZE
                | ui.WINDOW_FLAGS_NO_SCROLLBAR
            ),
            padding_x=10,
            padding_y=8,
        )

        with self._window.frame:
            with ui.VStack(spacing=5, style=_POPUP_STYLE):
                # Header
                ui.Label(title, name="title", height=22,
                         alignment=ui.Alignment.CENTER)
                ui.Label(f"Prim: {prim_path}", name="desc", height=16,
                         word_wrap=True)
                ui.Separator(height=2)

                # Category-specific info rows
                rows = self._get_info_rows(category, sub_label)
                for key, val in rows:
                    with ui.HStack(height=18, spacing=4):
                        ui.Label(key, name="key", width=160)
                        lbl = ui.Label(str(val), name="val")
                        # Store for live updates
                        self._value_labels[key] = lbl

                ui.Separator(height=2)
                # Close hint
                ui.Label("Click elsewhere to dismiss", name="desc",
                         height=16, alignment=ui.Alignment.CENTER)

        self._window.visible = True

    def _hide(self):
        if self._window:
            self._window.visible = False
        self._current_category = None

    # ── Per-category info rows ──────────────────────────────

    def _get_info_rows(self, category: str, sub_label: str) -> List[Tuple[str, str]]:
        """Return (key, value) pairs for the info card."""
        s = self._state

        if category == "bus":
            wl = WORKLOADS.get(s.current_workload, {})
            return [
                ("Dimensions",          "14 × 10 × 16 cm (model)"),
                ("GPU Model",           wl.get("gpuModel", "—")),
                ("GPU Count",           f"{wl.get('gpuCount', 0):,}"),
                ("GPU Utilization",     f"{s.gpu_util}%"),
                ("GPU Temperature",     f"{s.gpu_temp:.1f} °C"),
                ("Compute",             f"{s.flops:.1f} ExaFLOPS"),
                ("Workload",            wl.get("name", "—")),
                ("Total Compute Power", f"{wl.get('totalComputekW', 0):,.0f} kW"),
            ]

        elif category == "solar":
            tech = CELL_TECHS.get(s.current_cell_tech, {})
            # Try to identify which wing from sub_label
            wing_idx = self._parse_wing_index(sub_label)
            wing_info = self._get_wing_info(wing_idx)
            return [
                ("Wing Count",       f"{s.wing_count} (L{(s.wing_count+1)//2} + R{s.wing_count//2})"),
                ("Wing Area",        f"{s.wing_area:.0f} m² / wing"),
                ("Total Array Area", f"{s.wing_area * s.wing_count:.0f} m²"),
                ("Cell Technology",  tech.get("name", "—")),
                ("BOL Efficiency",   tech.get("bolEff", "—")),
                ("EOL Efficiency",   tech.get("eolEff", "—")),
                ("Temp Coeff",       tech.get("tcoefStr", "—")),
                ("Current Output",   f"{s.solar_pwr:.1f} kW (total)"),
                ("Array Temp",       f"{s.arr_temp:.1f} °C"),
                ("Selected Wing",    wing_info),
            ]

        elif category == "radiator":
            cool = COOLANTS.get(s.current_coolant, {})
            panel_idx = self._parse_panel_index(sub_label)
            panel_info = self._get_panel_info(panel_idx)
            return [
                ("Panel Count",       f"{s.rad_count}"),
                ("Panel Area",        f"{s.rad_area:.1f} m² / panel"),
                ("Total Rad Area",    f"{s.rad_area * s.rad_count:.0f} m²"),
                ("Emissivity ε",      f"{s.rad_epsilon:.2f}"),
                ("Coolant",           cool.get("name", "—")),
                ("Coolant Flow",      f"{cool.get('flow', 0):.1f} kg/s"),
                ("Coolant Tin/Tout",  f"{cool.get('tIn', 0)}C -> {cool.get('tOut', 0)}C"),
                ("Heat Rejected",     f"{s.rad_pwr:.1f} kW (total)"),
                ("Selected Panel",    panel_info),
            ]

        elif category == "antenna":
            return [
                ("Type",            "High-Gain Parabolic + Feed"),
                ("Dish Diameter",   f"{14*0.32:.1f} cm (model)"),
                ("Band",            "Ka-band (26.5-40 GHz)"),
                ("Data Rate",       "10 Gbps downlink"),
                ("Pointing",        "2-axis gimbal"),
                ("Status",          "Nominal"),
            ]

        elif category == "star_tracker":
            return [
                ("Type",            "Active Pixel Star Tracker"),
                ("Count",           "2 (+/-X redundant)"),
                ("FOV",             "20 x 20 deg"),
                ("Accuracy",        "< 5 arcsec (3s)"),
                ("Update Rate",     "10 Hz"),
                ("Status",          "Tracking"),
            ]

        elif category == "thruster":
            return [
                ("Type",            "Bi-propellant RCS thruster"),
                ("Count",           "4 (corner-mounted)"),
                ("Thrust",          "22 N each"),
                ("Isp",             "290 s"),
                ("Propellant",      "MMH / NTO"),
                ("Status",          "Standby"),
            ]

        elif category == "docking":
            return [
                ("Type",            "IDSS-compatible Docking Port"),
                ("Diameter",        f"{14*0.30:.1f} cm (model)"),
                ("Standard",        "International Docking System Std."),
                ("Capture Range",   "+/-10 deg cone"),
                ("Status",          "Ready"),
            ]

        return [("Component", sub_label)]

    # ── Helpers to extract wing / panel index ───────────────

    @staticmethod
    def _parse_wing_index(sub_label: str) -> Optional[int]:
        """Extract wing index from path like 'SolarWings/Left/Wing_2/Panel_1'."""
        for part in sub_label.split("/"):
            if part.startswith("Wing_"):
                try:
                    return int(part.split("_")[1])
                except (IndexError, ValueError):
                    pass
        return None

    @staticmethod
    def _parse_panel_index(sub_label: str) -> Optional[int]:
        """Extract panel index from 'Radiators/Left/Panel_1'."""
        for part in sub_label.split("/"):
            if part.startswith("Panel_"):
                try:
                    return int(part.split("_")[1])
                except (IndexError, ValueError):
                    pass
        return None

    def _get_wing_info(self, idx: Optional[int]) -> str:
        if idx is None:
            return "—"
        wings = self._state.wings
        if 0 <= idx < len(wings):
            w = wings[idx]
            return f"Wing {w.name}: {w.output:.1f} kW, {w.temp:.0f}°C, η={w.efficiency:.3f}"
        return f"Wing #{idx}"

    def _get_panel_info(self, idx: Optional[int]) -> str:
        if idx is None:
            return "—"
        panels = self._state.rad_panels
        if 0 <= idx < len(panels):
            p = panels[idx]
            return f"Panel #{p.id}: {p.q_rad:.1f} kW, {p.surf_temp:.0f}°C, ε={p.emissivity:.2f}"
        return f"Panel #{idx}"

    # ── Live update (called from extension tick) ────────────

    def update(self):
        """Refresh dynamic values in the popup if visible."""
        if not self._window or not self._window.visible:
            return
        if not self._current_category:
            return

        s = self._state

        # Update only the dynamic values
        if self._current_category == "bus":
            self._set("GPU Utilization",     f"{s.gpu_util}%")
            self._set("GPU Temperature",     f"{s.gpu_temp:.1f} °C")
            self._set("Compute",             f"{s.flops:.1f} ExaFLOPS")

        elif self._current_category == "solar":
            self._set("Current Output",  f"{s.solar_pwr:.1f} kW (total)")
            self._set("Array Temp",      f"{s.arr_temp:.1f} °C")

        elif self._current_category == "radiator":
            self._set("Heat Rejected",   f"{s.rad_pwr:.1f} kW (total)")

    def _set(self, key: str, val: str):
        lbl = self._value_labels.get(key)
        if lbl:
            lbl.text = val
