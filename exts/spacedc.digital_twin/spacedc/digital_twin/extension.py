"""
============================================================
  extension.py — Omniverse Extension entry point
  The main SpaceDC Digital Twin Extension for NVIDIA Omniverse Kit.
============================================================

  Lifecycle:
    on_startup()  → Build scene, init simulation, open UI panels
    on_shutdown() → Tear down subscriptions and UI

  This is the master orchestrator that wires together:
    - Physics models  (physics/)
    - USD scene       (scene/)
    - UI panels       (ui/)
    - Simulation loop (simulation_engine.py)
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    import omni.ext
    import omni.kit.app
    import omni.usd
    import omni.ui as ui
    HAS_KIT = True
except ImportError:
    HAS_KIT = False

try:
    import carb
    HAS_CARB = True
except ImportError:
    HAS_CARB = False

from .physics.state import SimState
from .physics.constellation import (
    HAS_SGP4,
    ConstellationData,
    build_dawn_dusk_constellation,
    load_tle_file,
    scene_position_for_satellite,
)
from .physics.topology import (
    TopologyLink,
    add_link,
    available_satellite_text,
    link_summary_text,
    preset_links,
    remove_link,
    resolve_satellite_reference,
)
from .physics.business_network import (
    BUSINESS_WORKLOADS,
    BusinessSatelliteConfig,
    DemandAssignment,
    ComputeNodeState,
    analyze_business_demands,
    business_assignment_text,
    business_available_text,
    clear_business_workload,
    compute_status_text,
    default_business_configs,
    set_business_workload,
)
from .physics.telemetry import TelemetryLogger
from .simulation_engine import SimulationEngine

# Conditional scene imports (need pxr)
try:
    from .scene.earth_builder import (
        build_earth_scene, update_satellite_position, update_eclipse_lighting,
        set_prim_translation,
        update_orbit_ring,
    )
    from .scene.constellation_builder import (
        BUSINESS_BLUE,
        build_constellation,
        update_constellation_positions,
        get_selected_catalog_number_from_path,
    )
    from .scene.topology_builder import (
        build_topology_links,
        clear_topology_links,
        update_topology_links,
    )
    from .scene.business_orchestration_builder import (
        apply_business_workload_styles,
        apply_compute_node_status,
        build_business_demand_links,
        clear_business_demand_links,
        update_business_demand_links,
    )
    from .scene.satellite_builder import build_satellite
    from .scene.environment import (
        setup_environment, update_environment_for_eclipse, update_earth_rotation,
    )
    HAS_SCENE = True
    print("[SpaceDC] Scene modules imported OK")
except ImportError as e:
    HAS_SCENE = False
    print(f"[SpaceDC] WARNING: Scene modules import failed: {e}")
except Exception as e:
    HAS_SCENE = False
    print(f"[SpaceDC] WARNING: Scene modules error: {e}")

from .ui.dt_panel import DigitalTwinPanel
from .ui.trend_chart import TrendChartPanel
from .ui.view_switcher import ViewSwitcher


# ── Prim paths ──────────────────────────────────────────────
WORLD_ROOT = "/World"
SATELLITE_PATH = "/World/Satellite"
CONSTELLATION_PATH = "/World/Constellation"
BUSINESS_CONSTELLATION_PATH = "/World/BusinessConstellation"
TOPOLOGY_PATH = "/World/Constellation/Topology"
DEMAND_LINKS_PATH = "/World/Mission/DemandLinks"
SUN_LIGHT_PATH = "/World/Sun/SunLight"
AMBIENT_PATH = "/World/Lights/Ambient"
EARTH_PATH = "/World/Earth"
CLOUDS_PATH = "/World/Clouds"
DOME_PATH = "/World/Lights/DomeLight"
KNOWN_LIGHT_PATHS = {
    SUN_LIGHT_PATH,
    AMBIENT_PATH,
    DOME_PATH,
    "/World/Satellite/MicroKeyLight",
    "/World/Satellite/MicroFillLight",
}
PAYLOAD_INSPECTION_HIDE_PRIMS = (
    "BodyShell",
    "TopDetailDark",
    "TopDetailMetal",
    "TopDetailGlass",
)


class SpaceDCExtension(omni.ext.IExt if HAS_KIT else object):
    """
    ORBITAL DC-1 — Space Data Center Digital Twin Extension.

    When running inside Omniverse Kit:
      - Creates the full USD scene (Earth, satellite, lighting)
      - Opens a single consolidated Digital Twin control panel
      - Subscribes to the Kit update loop for simulation ticks
    """

    def __init__(self):
        super().__init__()
        self._state: Optional[SimState] = None
        self._logger: Optional[TelemetryLogger] = None
        self._engine: Optional[SimulationEngine] = None

        # UI panels
        self._dt_panel: Optional[DigitalTwinPanel] = None
        self._trend: Optional[TrendChartPanel] = None
        self._view_switcher: Optional[ViewSwitcher] = None
        self._constellation: Optional[ConstellationData] = None
        self._business_constellation: Optional[ConstellationData] = None
        self._selected_catalog_number: Optional[str] = None
        self._topology_links: list[TopologyLink] = []
        self._business_configs: dict[str, BusinessSatelliteConfig] = {}
        self._business_assignments: list[DemandAssignment] = []
        self._compute_node_states: dict[str, ComputeNodeState] = {}
        self._topology_status_text: str = "Load a constellation to author topology links."
        self._business_status_text: str = "Load business satellites to start demand routing."
        self._constellation_epoch_base = datetime.now(timezone.utc)
        self._payload_inspection_open: bool = False

        # Kit subscription
        self._update_sub = None
        self._selection_sub = None
        self._viewport_style_applied = False

    # ── Lifecycle ───────────────────────────────────────────

    def on_startup(self, ext_id: str = ""):
        print(f"[SpaceDC] Extension starting up... HAS_KIT={HAS_KIT}, HAS_SCENE={HAS_SCENE}")
        self._apply_viewport_style()

        # 1. Create state & logger
        self._state = SimState()
        self._state.initialize()
        self._logger = TelemetryLogger()

        # 2. Create simulation engine
        self._engine = SimulationEngine(self._state, self._logger)
        self._engine.set_callbacks(
            on_scene_update=self._on_scene_tick,
            on_ui_update=self._on_ui_tick,
        )

        # 3. Build USD scene
        self._scene_built = False
        if HAS_SCENE and HAS_KIT:
            stage = omni.usd.get_context().get_stage()
            if stage:
                try:
                    build_earth_scene(stage, WORLD_ROOT)
                    build_satellite(
                        stage, SATELLITE_PATH,
                        self._state.wing_count, self._state.wing_area,
                        self._state.rad_count, self._state.rad_area,
                    )
                    setup_environment(stage, WORLD_ROOT)
                    self._disable_non_spacedc_lights(stage)
                    self._scene_built = True
                    print("[SpaceDC] USD scene built OK")
                except Exception as e:
                    print(f"[SpaceDC] ERROR building scene: {e}")
                    import traceback; traceback.print_exc()
            else:
                print("[SpaceDC] Stage not ready at startup, will build on first tick")

        # 4. Create view switcher
        self._view_switcher = ViewSwitcher()
        if self._scene_built and HAS_SCENE and HAS_KIT:
            stage = omni.usd.get_context().get_stage()
            if stage:
                self._view_switcher.ensure_background_cards(stage)
                self._view_switcher.switch_to_orbit(stage)

        # 5. Build UI panels
        self._dt_panel = DigitalTwinPanel(
            self._state,
            on_rebuild=self._rebuild_satellite,
            on_state_change=lambda: None,
            on_view_toggle=self._on_view_toggle,
            on_load_constellation=self._load_constellation_from_path,
            on_load_sdc_demo=lambda: self._load_constellation_from_path(self._get_default_constellation_path()),
            on_clear_constellation=self._clear_constellation,
            on_load_business_constellation=self._load_business_constellation_from_path,
            on_clear_business_constellation=self._clear_business_constellation,
            on_assign_business_workload=self._assign_business_workload,
            on_clear_business_workload=self._clear_business_workload,
            on_apply_topology_preset=self._apply_topology_preset,
            on_add_topology_link=self._add_topology_link,
            on_remove_topology_link=self._remove_topology_link,
            on_clear_topology=self._clear_topology,
            default_constellation_path=self._get_default_constellation_path(),
            default_business_path=self._get_default_business_path(),
        )
        self._dt_panel.build()
        print(f"[SpaceDC] Orbits dir resolved: {self._get_orbits_dir()}")
        print(f"[SpaceDC] Default compute TLE: {self._get_default_constellation_path()}")
        print(f"[SpaceDC] Default business TLE: {self._get_default_business_path()}")
        self._dt_panel.update_live_status()
        self._sync_topology_ui()
        self._sync_business_ui()
        self._trend = TrendChartPanel(self._state)
        self._trend.build()

        # 6. Subscribe to Kit update loop
        if HAS_KIT:
            ctx = omni.usd.get_context()
            events = ctx.get_stage_event_stream()
            self._selection_sub = events.create_subscription_to_pop_by_type(
                int(omni.usd.StageEventType.SELECTION_CHANGED),
                self._on_selection_changed,
                name="spacedc.constellation.selection",
            )
            app = omni.kit.app.get_app()
            self._update_sub = app.get_update_event_stream().create_subscription_to_pop(
                self._on_kit_update, name="spacedc.digital_twin.update"
            )

        if self._scene_built:
            self._load_default_constellation()
            self._load_default_business_constellation()

        self._logger.add_log("ok", "SpaceDC Digital Twin initialized.", 0)
        print("[SpaceDC] Extension startup complete ✓")

    def on_shutdown(self):
        print("[SpaceDC] Extension shutting down...")

        # Unsubscribe from update loop
        if self._update_sub:
            self._update_sub = None
        if self._selection_sub:
            self._selection_sub = None

        # Destroy UI
        if self._dt_panel:
            self._dt_panel.destroy()
        if self._trend:
            self._trend.destroy()
        if self._view_switcher:
            self._view_switcher.destroy()

        print("[SpaceDC] Extension shutdown complete")

    def _get_default_constellation_path(self) -> str:
        path = self._resolve_tle_path("", "sample_tle.tle")
        if path:
            return path
        return os.path.join(self._get_orbits_dir(), "sample_tle.tle")

    def _get_default_business_path(self) -> str:
        path = self._resolve_tle_path("", "sample_business_tle.tle")
        if path:
            return path
        return os.path.join(self._get_orbits_dir(), "sample_business_tle.tle")

    def _get_orbits_dir_candidates(self) -> list[str]:
        candidates: list[str] = []

        env_orbits_dir = str(os.environ.get("SPACEDC_ORBITS_DIR", "")).strip()
        if env_orbits_dir:
            candidates.append(env_orbits_dir)

        env_source_root = str(os.environ.get("SPACEDC_SOURCE_ROOT", "")).strip()
        if env_source_root:
            candidates.append(os.path.join(env_source_root, "exts", "spacedc.digital_twin", "data", "orbits"))

        cwd = os.getcwd()
        if cwd:
            candidates.append(os.path.join(cwd, "..", "SpaceDC", "exts", "spacedc.digital_twin", "data", "orbits"))
            candidates.append(os.path.join(cwd, "exts", "spacedc.digital_twin", "data", "orbits"))

        this_dir = os.path.dirname(os.path.abspath(__file__))
        ext_root = os.path.normpath(os.path.join(this_dir, "..", "..", ".."))
        candidates.append(os.path.join(ext_root, "data", "orbits"))

        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = os.path.normpath(candidate)
            folded = normalized.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            deduped.append(normalized)
        return deduped

    def _get_orbits_dir(self) -> str:
        candidates = self._get_orbits_dir_candidates()
        for candidate in candidates:
            if os.path.isdir(candidate):
                return candidate
        return candidates[0] if candidates else ""

    def _resolve_tle_path(self, path: str, default_filename: str) -> str:
        raw = str(path or "").strip()
        candidates: list[str] = []

        if not raw:
            for base_dir in self._get_orbits_dir_candidates():
                candidates.append(os.path.join(base_dir, default_filename))
        else:
            if os.path.isdir(raw):
                candidates.append(os.path.join(raw, default_filename))
            else:
                candidates.append(raw)
                if not os.path.isabs(raw):
                    for base_dir in self._get_orbits_dir_candidates():
                        candidates.append(os.path.join(base_dir, raw))

        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = os.path.normpath(candidate)
            folded = normalized.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            deduped.append(normalized)

        for candidate in deduped:
            if os.path.isfile(candidate):
                return candidate
        return deduped[0] if deduped else ""

    def _apply_viewport_style(self) -> None:
        """Hide Kit editor overlays so the scene reads like a clean simulation view."""
        if not HAS_CARB:
            return
        try:
            settings = carb.settings.get_settings()
            bool_settings = {
                "/app/viewport/grid/enabled": False,
                "/app/viewport/outline/enabled": False,
                "/app/viewport/defaults/guide/grid/visible": False,
                "/app/viewport/defaults/guide/axis/visible": False,
                "/app/viewport/defaults/hud/visible": False,
                "/app/viewport/defaults/scene/cameras/visible": False,
                "/app/viewport/defaults/scene/lights/visible": False,
                "/persistent/app/viewport/grid/enabled": False,
                "/persistent/app/viewport/outline/enabled": False,
                "/persistent/app/viewport/defaults/guide/grid/visible": False,
                "/persistent/app/viewport/defaults/guide/axis/visible": False,
                "/persistent/app/viewport/defaults/hud/visible": False,
                "/persistent/app/viewport/defaults/scene/cameras/visible": False,
                "/persistent/app/viewport/defaults/scene/lights/visible": False,
            }
            for key, value in bool_settings.items():
                settings.set_bool(key, value)
            auto_rig_settings = [
                "/exts/omni.kit.viewport.menubar.lighting/autoLightRig/enabled",
                "/exts/omni.kit.viewport.menubar.lighting/autoLightRig/enableWithoutMenu",
                "/persistent/exts/omni.kit.viewport.menubar.lighting/autoLightRig/enabled",
                "/persistent/exts/omni.kit.viewport.menubar.lighting/autoLightRig/enableWithoutMenu",
            ]
            for key in auto_rig_settings:
                settings.set_bool(key, False)
            if not self._viewport_style_applied:
                print("[SpaceDC] Viewport overlays disabled (grid/axis/hud/outline)")
                self._viewport_style_applied = True
        except Exception as e:
            print(f"[SpaceDC] WARNING: Failed to apply viewport style: {e}")

    def _current_constellation_time(self) -> datetime:
        return self._constellation_epoch_base + timedelta(seconds=self._state.met_seconds)

    def _sync_topology_ui(self) -> None:
        if not self._dt_panel:
            return
        self._dt_panel.update_topology_info(
            available_satellite_text(self._constellation),
            link_summary_text(self._topology_links, self._constellation),
            self._topology_status_text,
            len(self._topology_links),
        )

    def _sync_business_ui(self) -> None:
        if not self._dt_panel:
            return
        self._dt_panel.update_business_info(
            business_available_text(self._business_constellation, self._business_configs),
            business_assignment_text(
                self._business_assignments,
                self._business_constellation,
                self._constellation,
            ),
            self._business_status_text if self._business_status_text else compute_status_text(self._compute_node_states, self._constellation),
            len(self._business_assignments),
        )

    def _refresh_topology_scene(self, stage=None) -> None:
        if not HAS_SCENE or not HAS_KIT:
            return
        if stage is None:
            stage = omni.usd.get_context().get_stage()
        if not stage:
            return

        from .scene.earth_builder import EARTH_RADIUS

        if not self._constellation or not self._topology_links:
            clear_topology_links(stage, TOPOLOGY_PATH)
            return

        build_topology_links(
            stage,
            TOPOLOGY_PATH,
            self._topology_links,
            self._constellation,
            EARTH_RADIUS,
            self._current_constellation_time(),
            self._selected_catalog_number,
        )

    def _refresh_business_scene(self, stage=None) -> None:
        if not HAS_SCENE or not HAS_KIT:
            return
        if stage is None:
            stage = omni.usd.get_context().get_stage()
        if not stage:
            return

        from .scene.earth_builder import EARTH_RADIUS

        try:
            if self._business_constellation:
                update_constellation_positions(
                    stage,
                    BUSINESS_CONSTELLATION_PATH,
                    self._business_constellation.satellites,
                    EARTH_RADIUS,
                    self._current_constellation_time(),
                )
                apply_business_workload_styles(
                    stage,
                    BUSINESS_CONSTELLATION_PATH,
                    self._business_constellation,
                    self._business_configs,
                )

            self._business_assignments, self._compute_node_states = analyze_business_demands(
                self._business_constellation,
                self._business_configs,
                self._constellation,
                self._current_constellation_time(),
            )

            if self._constellation:
                apply_compute_node_status(
                    stage,
                    CONSTELLATION_PATH,
                    self._constellation,
                    self._compute_node_states,
                )

            update_business_demand_links(
                stage,
                DEMAND_LINKS_PATH,
                self._business_assignments,
                self._business_constellation,
                self._constellation,
                EARTH_RADIUS,
                self._current_constellation_time(),
            )

            compute_text = compute_status_text(self._compute_node_states, self._constellation)
            if self._business_constellation and self._constellation:
                self._business_status_text = compute_text
            elif self._business_constellation:
                self._business_status_text = "Business satellites loaded. Waiting for compute constellation."
            else:
                self._business_status_text = "Load business satellites to start demand routing."
        except Exception as e:
            import traceback

            print(f"[SpaceDC] ERROR refreshing business scene: {e}")
            traceback.print_exc()
            self._business_assignments = []
            self._compute_node_states = {}
            clear_business_demand_links(stage, DEMAND_LINKS_PATH)
            if self._constellation:
                apply_compute_node_status(stage, CONSTELLATION_PATH, self._constellation, {})
            self._business_status_text = f"Business routing error: {type(e).__name__}"
        self._sync_business_ui()

    def _clear_topology_state(self, status_text: str) -> None:
        self._topology_links = []
        self._topology_status_text = status_text
        self._sync_topology_ui()
        if HAS_SCENE and HAS_KIT:
            stage = omni.usd.get_context().get_stage()
            if stage:
                clear_topology_links(stage, TOPOLOGY_PATH)

    def _apply_topology_preset(self, preset_key: str) -> None:
        if not self._constellation or not self._constellation.satellites:
            self._topology_status_text = "Load a constellation first."
            self._sync_topology_ui()
            return
        self._topology_links = preset_links(self._constellation.satellites, preset_key)
        self._topology_status_text = f"Applied {preset_key} topology preset."
        self._sync_topology_ui()
        self._refresh_topology_scene()
        if self._logger:
            self._logger.add_log("info", f"[Topology] Applied {preset_key} preset ({len(self._topology_links)} links).", self._state.met_seconds)

    def _add_topology_link(self, source_ref: str, target_ref: str) -> None:
        if not self._constellation:
            self._topology_status_text = "Load a constellation first."
            self._sync_topology_ui()
            return
        source_id = resolve_satellite_reference(source_ref, self._constellation)
        target_id = resolve_satellite_reference(target_ref, self._constellation)
        if not source_id or not target_id:
            self._topology_status_text = "Could not resolve one or both satellite IDs."
            self._sync_topology_ui()
            return
        self._topology_links, added = add_link(self._topology_links, source_id, target_id)
        self._topology_status_text = (
            f"Added link {source_id} ↔ {target_id}."
            if added else
            f"Link {source_id} ↔ {target_id} already exists or is invalid."
        )
        self._sync_topology_ui()
        self._refresh_topology_scene()
        if self._logger:
            self._logger.add_log("info" if added else "warn", f"[Topology] {self._topology_status_text}", self._state.met_seconds)

    def _remove_topology_link(self, source_ref: str, target_ref: str) -> None:
        if not self._constellation:
            self._topology_status_text = "Load a constellation first."
            self._sync_topology_ui()
            return
        source_id = resolve_satellite_reference(source_ref, self._constellation)
        target_id = resolve_satellite_reference(target_ref, self._constellation)
        if not source_id or not target_id:
            self._topology_status_text = "Could not resolve one or both satellite IDs."
            self._sync_topology_ui()
            return
        self._topology_links, removed = remove_link(self._topology_links, source_id, target_id)
        self._topology_status_text = (
            f"Removed link {source_id} ↔ {target_id}."
            if removed else
            f"No active link found for {source_id} ↔ {target_id}."
        )
        self._sync_topology_ui()
        self._refresh_topology_scene()
        if self._logger:
            self._logger.add_log("info" if removed else "warn", f"[Topology] {self._topology_status_text}", self._state.met_seconds)

    def _clear_topology(self) -> None:
        self._clear_topology_state("Cleared all topology links.")
        if self._logger:
            self._logger.add_log("info", "[Topology] Cleared all topology links.", self._state.met_seconds)

    def _load_default_business_constellation(self) -> None:
        if self._business_constellation is not None:
            return
        default_path = self._get_default_business_path()
        if os.path.isfile(default_path):
            self._load_business_constellation_from_path(default_path, auto=True)

    def _load_business_constellation_from_path(self, path: str, auto: bool = False) -> None:
        if not HAS_SCENE or not HAS_KIT:
            return
        path = self._resolve_tle_path(path, "sample_business_tle.tle")
        if not path or not os.path.isfile(path):
            self._business_status_text = f"Business TLE file not found: {path}"
            self._sync_business_ui()
            if self._logger and not auto:
                self._logger.add_log("warn", f"[Business] File not found: {path}", self._state.met_seconds)
            return

        try:
            constellation = load_tle_file(path)
        except Exception as e:
            self._business_status_text = f"Failed to load business TLE: {e}"
            self._sync_business_ui()
            if self._logger:
                self._logger.add_log("danger", f"[Business] Failed to load TLE: {e}", self._state.met_seconds)
            return

        if not constellation.satellites:
            self._business_status_text = "No valid business TLE records found."
            self._sync_business_ui()
            return

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return

        from .scene.earth_builder import EARTH_RADIUS

        self._business_constellation = constellation
        self._business_configs = default_business_configs(constellation)
        self._business_status_text = f"Loaded {len(constellation.satellites)} business satellites."

        build_constellation(
            stage,
            BUSINESS_CONSTELLATION_PATH,
            constellation.satellites,
            EARTH_RADIUS,
            None,
            uniform_color=BUSINESS_BLUE,
        )
        self._refresh_business_scene(stage)

        if self._logger and not auto:
            self._logger.add_log(
                "ok",
                f"[Business] Loaded {len(constellation.satellites)} satellites from {os.path.basename(path)}.",
                self._state.met_seconds,
            )

    def _clear_business_constellation(self) -> None:
        if HAS_SCENE and HAS_KIT:
            stage = omni.usd.get_context().get_stage()
            if stage:
                stage.RemovePrim(BUSINESS_CONSTELLATION_PATH)
                clear_business_demand_links(stage, DEMAND_LINKS_PATH)
                if self._constellation:
                    apply_compute_node_status(stage, CONSTELLATION_PATH, self._constellation, {})

        self._business_constellation = None
        self._business_configs = {}
        self._business_assignments = []
        self._compute_node_states = {}
        self._business_status_text = "Business satellites cleared."
        self._sync_business_ui()
        if self._logger:
            self._logger.add_log("info", "[Business] Cleared business satellites.", self._state.met_seconds)

    def _assign_business_workload(self, business_ref: str, workload_key: str) -> None:
        if not self._business_constellation:
            self._business_status_text = "Load business satellites first."
            self._sync_business_ui()
            return
        business_id = resolve_satellite_reference(business_ref, self._business_constellation)
        if not business_id:
            self._business_status_text = "Could not resolve business satellite ID."
            self._sync_business_ui()
            return
        if workload_key not in BUSINESS_WORKLOADS:
            self._business_status_text = f"Unknown workload: {workload_key}"
            self._sync_business_ui()
            return

        self._business_configs = set_business_workload(self._business_configs, business_id, workload_key)
        self._business_status_text = f"Assigned {BUSINESS_WORKLOADS[workload_key].name} to {business_id}."
        self._refresh_business_scene()
        if self._logger:
            self._logger.add_log("info", f"[Business] {self._business_status_text}", self._state.met_seconds)

    def _clear_business_workload(self, business_ref: str) -> None:
        if not self._business_constellation:
            self._business_status_text = "Load business satellites first."
            self._sync_business_ui()
            return
        business_id = resolve_satellite_reference(business_ref, self._business_constellation)
        if not business_id:
            self._business_status_text = "Could not resolve business satellite ID."
            self._sync_business_ui()
            return
        self._business_configs = clear_business_workload(self._business_configs, business_id)
        self._business_status_text = f"Cleared workload assignment for {business_id}."
        self._refresh_business_scene()
        if self._logger:
            self._logger.add_log("info", f"[Business] {self._business_status_text}", self._state.met_seconds)

    def _disable_non_spacedc_lights(self, stage) -> None:
        """Turn off stage lights we did not create, such as auto-inserted light rigs."""
        if not stage:
            return
        try:
            from pxr import UsdGeom
        except ImportError:
            return

        disabled = 0
        light_types = {"DistantLight", "DomeLight", "SphereLight", "RectLight", "DiskLight", "CylinderLight"}
        for prim in stage.Traverse():
            if prim.GetTypeName() not in light_types:
                continue
            path_str = str(prim.GetPath())
            if path_str in KNOWN_LIGHT_PATHS:
                continue
            changed = False
            intensity_attr = prim.GetAttribute("inputs:intensity")
            if intensity_attr and intensity_attr.IsValid():
                current = intensity_attr.Get()
                if current is None or abs(float(current)) > 1e-6:
                    intensity_attr.Set(0.0)
                    changed = True
            try:
                imageable = UsdGeom.Imageable(prim)
                if imageable.ComputeVisibility() != UsdGeom.Tokens.invisible:
                    imageable.MakeInvisible()
                    changed = True
            except Exception:
                pass
            if changed:
                disabled += 1

        if disabled:
            print(f"[SpaceDC] Disabled {disabled} non-SpaceDC stage light(s)")

    def _set_detail_satellite_visible(self, stage, visible: bool) -> None:
        if not HAS_SCENE or not stage:
            return
        try:
            from pxr import UsdGeom
        except ImportError:
            return
        prim = stage.GetPrimAtPath(SATELLITE_PATH)
        if prim and prim.IsValid():
            imageable = UsdGeom.Imageable(prim)
            if visible:
                imageable.MakeVisible()
            else:
                imageable.MakeInvisible()

    def _set_payload_inspection(self, stage, enabled: bool) -> None:
        if not HAS_SCENE or not HAS_KIT or not stage:
            return
        try:
            from pxr import UsdGeom
        except ImportError:
            return

        asset_root = stage.GetPrimAtPath(f"{SATELLITE_PATH}/Bus/Fit/AssetRoot")
        if asset_root and asset_root.IsValid():
            for prim_name in PAYLOAD_INSPECTION_HIDE_PRIMS:
                prim = stage.GetPrimAtPath(f"{SATELLITE_PATH}/Bus/Fit/AssetRoot/{prim_name}")
                if prim and prim.IsValid():
                    imageable = UsdGeom.Imageable(prim)
                    if enabled:
                        imageable.MakeInvisible()
                    else:
                        imageable.MakeVisible()

        self._payload_inspection_open = enabled
        if self._view_switcher:
            self._view_switcher.set_micro_camera_inspection(stage, enabled)

    def _handle_detail_satellite_selection(self, prim_path: str) -> bool:
        # Payload inspection via direct click is temporarily disabled because
        # the current selection-driven interaction is not stable enough.
        # Keep returning False so constellation marker selection still works.
        return False

    def _set_default_tracked_target(self) -> None:
        self._state.tracked_satellite_name = "ORBITAL DC-1"
        self._state.tracked_satellite_id = "SIM-001"
        self._state.tracked_satellite_source = "Internal Orbit Model"
        self._state.tracked_altitude_km = self._state.orbit_altitude
        self._state.tracked_inclination_deg = self._state.orbit_inclination
        self._state.tracked_period_s = self._state.orbit_period

    def _load_default_constellation(self) -> None:
        if self._constellation is not None:
            return
        default_path = self._get_default_constellation_path()
        if os.path.isfile(default_path):
            self._load_constellation_from_path(default_path, auto=True)
        else:
            self._load_sdc_demo_constellation(auto=True)

    def _load_sdc_demo_constellation(self, auto: bool = False) -> None:
        if not HAS_SCENE or not HAS_KIT:
            return
        stage = omni.usd.get_context().get_stage()
        if not stage:
            return

        from .scene.earth_builder import EARTH_RADIUS

        if self._view_switcher and self._view_switcher.mode == "satellite":
            self._set_payload_inspection(stage, False)
            self._view_switcher.switch_to_orbit(stage)

        constellation = build_dawn_dusk_constellation(
            count=6,
            altitude_km=575.0,
            inclination_deg=97.8,
        )

        self._constellation = constellation
        self._selected_catalog_number = None
        self._constellation_epoch_base = datetime.now(timezone.utc)
        self._clear_topology_state("Loaded SDC demo. Use NETWORK TOPOLOGY to add links.")
        build_constellation(stage, CONSTELLATION_PATH, constellation.satellites, EARTH_RADIUS, None)
        update_constellation_positions(
            stage,
            CONSTELLATION_PATH,
            constellation.satellites,
            EARTH_RADIUS,
            self._current_constellation_time(),
        )
        self._refresh_business_scene(stage)
        self._set_detail_satellite_visible(stage, False)
        self._set_default_tracked_target()

        orbit_prim = stage.GetPrimAtPath(f"{WORLD_ROOT}/OrbitRing")
        if orbit_prim and orbit_prim.IsValid():
            try:
                from pxr import UsdGeom
                UsdGeom.Imageable(orbit_prim).MakeInvisible()
            except Exception:
                pass

        if self._logger and not auto:
            self._logger.add_log(
                "ok",
                "[Constellation] Loaded synchronized dawn-dusk SDC demo (6 sats).",
                self._state.met_seconds,
            )

    def _load_constellation_from_path(self, path: str, auto: bool = False) -> None:
        if not HAS_SCENE or not HAS_KIT:
            return
        path = self._resolve_tle_path(path, "sample_tle.tle")
        if not path or not os.path.isfile(path):
            if self._logger and not auto:
                self._logger.add_log("warn", f"[Constellation] File not found: {path}", self._state.met_seconds)
            return

        try:
            constellation = load_tle_file(path)
        except Exception as e:
            if self._logger:
                self._logger.add_log("danger", f"[Constellation] Failed to load TLE: {e}", self._state.met_seconds)
            return

        if not constellation.satellites:
            if self._logger:
                self._logger.add_log("warn", "[Constellation] No valid TLE records found.", self._state.met_seconds)
            return

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return

        from .scene.earth_builder import EARTH_RADIUS

        if self._view_switcher and self._view_switcher.mode == "satellite":
            self._set_payload_inspection(stage, False)
            self._view_switcher.switch_to_orbit(stage)

        self._constellation = constellation
        self._selected_catalog_number = None
        self._constellation_epoch_base = datetime.now(timezone.utc)
        self._clear_topology_state(f"Loaded {len(constellation.satellites)} satellites. Add links or apply a preset.")
        build_constellation(stage, CONSTELLATION_PATH, constellation.satellites, EARTH_RADIUS, None)
        update_constellation_positions(
            stage,
            CONSTELLATION_PATH,
            constellation.satellites,
            EARTH_RADIUS,
            self._current_constellation_time(),
        )
        self._refresh_business_scene(stage)
        self._set_detail_satellite_visible(stage, False)
        self._set_default_tracked_target()

        orbit_prim = stage.GetPrimAtPath(f"{WORLD_ROOT}/OrbitRing")
        if orbit_prim and orbit_prim.IsValid():
            try:
                from pxr import UsdGeom
                UsdGeom.Imageable(orbit_prim).MakeInvisible()
            except Exception:
                pass

        if self._logger:
            mode = "SGP4" if HAS_SGP4 else "Kepler fallback"
            self._logger.add_log(
                "ok",
                f"[Constellation] Loaded {len(constellation.satellites)} satellites from {os.path.basename(path)} ({mode}).",
                self._state.met_seconds,
            )

    def _clear_constellation(self) -> None:
        if not HAS_SCENE or not HAS_KIT:
            return
        stage = omni.usd.get_context().get_stage()
        if stage:
            stage.RemovePrim(CONSTELLATION_PATH)
            stage.RemovePrim(TOPOLOGY_PATH)
            orbit_prim = stage.GetPrimAtPath(f"{WORLD_ROOT}/OrbitRing")
            if orbit_prim and orbit_prim.IsValid():
                try:
                    from pxr import UsdGeom
                    UsdGeom.Imageable(orbit_prim).MakeVisible()
                except Exception:
                    pass
            self._set_detail_satellite_visible(stage, True)
            self._set_payload_inspection(stage, False)

        self._constellation = None
        self._selected_catalog_number = None
        self._topology_links = []
        self._topology_status_text = "Topology cleared with constellation."
        self._sync_topology_ui()
        if HAS_SCENE and HAS_KIT:
            stage = omni.usd.get_context().get_stage()
            if stage:
                clear_business_demand_links(stage, DEMAND_LINKS_PATH)
        self._set_default_tracked_target()
        self._refresh_business_scene()
        if self._logger:
            self._logger.add_log("info", "[Constellation] Cleared loaded TLE satellites.", self._state.met_seconds)

    def _select_constellation_satellite(self, catalog_number: str, switch_to_micro: bool = True) -> None:
        if not self._constellation:
            return
        sat = self._constellation.get(catalog_number)
        if not sat:
            return

        source_label = (
            "Synthetic Dawn-Dusk SDC"
            if self._constellation.source_path.startswith("builtin:")
            else "TLE / Constellation Layer"
        )
        self._selected_catalog_number = catalog_number
        self._payload_inspection_open = False
        self._state.tracked_satellite_name = sat.name
        self._state.tracked_satellite_id = sat.catalog_number or sat.safe_id
        self._state.tracked_satellite_source = source_label
        self._state.tracked_altitude_km = sat.mean_altitude_km
        self._state.tracked_inclination_deg = sat.inclination_deg
        self._state.tracked_period_s = sat.period_seconds

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return

        from .scene.earth_builder import EARTH_RADIUS

        build_constellation(stage, CONSTELLATION_PATH, self._constellation.satellites, EARTH_RADIUS, catalog_number)
        self._refresh_topology_scene(stage)
        self._refresh_business_scene(stage)
        update_constellation_positions(
            stage,
            CONSTELLATION_PATH,
            self._constellation.satellites,
            EARTH_RADIUS,
            self._current_constellation_time(),
        )
        self._sync_detail_satellite_to_selected(stage)
        self._set_payload_inspection(stage, False)
        self._set_detail_satellite_visible(stage, True)

        if self._logger:
            self._logger.add_log(
                "info",
                f"[Constellation] Selected {sat.label} for micro-detail view.",
                self._state.met_seconds,
            )

        if switch_to_micro and self._view_switcher:
            self._view_switcher.switch_to_satellite(stage)

    def _sync_detail_satellite_to_selected(self, stage) -> None:
        if not self._constellation or not self._selected_catalog_number:
            return
        sat = self._constellation.get(self._selected_catalog_number)
        if not sat:
            return

        from .scene.earth_builder import EARTH_RADIUS

        x, y, z = scene_position_for_satellite(sat, self._current_constellation_time(), EARTH_RADIUS)
        set_prim_translation(stage, SATELLITE_PATH, x, y, z)

    def _on_selection_changed(self, event):
        if not HAS_KIT:
            return
        ctx = omni.usd.get_context()
        sel = ctx.get_selection()
        paths = sel.get_selected_prim_paths()
        if not paths:
            return
        if self._handle_detail_satellite_selection(paths[0]):
            return
        catalog_number = get_selected_catalog_number_from_path(paths[0])
        if catalog_number:
            self._select_constellation_satellite(catalog_number, switch_to_micro=True)

    # ── Kit update callback ─────────────────────────────────

    def _on_kit_update(self, event):
        """Called every frame by Omniverse Kit."""
        self._apply_viewport_style()
        # Deferred scene build if stage wasn't ready at startup
        if not self._scene_built and HAS_SCENE and HAS_KIT:
            stage = omni.usd.get_context().get_stage()
            if stage:
                try:
                    build_earth_scene(stage, WORLD_ROOT)
                    build_satellite(
                        stage, SATELLITE_PATH,
                        self._state.wing_count, self._state.wing_area,
                        self._state.rad_count, self._state.rad_area,
                    )
                    setup_environment(stage, WORLD_ROOT)
                    self._disable_non_spacedc_lights(stage)
                    if self._view_switcher:
                        self._view_switcher.ensure_background_cards(stage)
                        self._view_switcher.switch_to_orbit(stage)
                    print("[SpaceDC] USD scene built OK (deferred)")
                    self._load_default_constellation()
                    self._load_default_business_constellation()
                except Exception as e:
                    print(f"[SpaceDC] ERROR building scene (deferred): {e}")
                    import traceback; traceback.print_exc()
                finally:
                    # Mark as built (or failed) so we don't retry every frame
                    self._scene_built = True

        if self._engine:
            self._engine.tick()

    # ── Scene update callback ───────────────────────────────

    def _on_scene_tick(self, result: dict):
        """Move satellite, update lighting, rotate Earth."""
        if not HAS_SCENE or not HAS_KIT:
            return

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return
        if self._view_switcher:
            self._view_switcher.ensure_background_cards(stage)
        self._disable_non_spacedc_lights(stage)

        # Dynamic orbit radius in scene units: EARTH_RADIUS * (Re + alt) / Re
        from .scene.earth_builder import EARTH_RADIUS
        re_km = 6371.0
        dynamic_radius = EARTH_RADIUS * (re_km + self._state.orbit_altitude) / re_km

        if self._constellation:
            update_constellation_positions(
                stage,
                CONSTELLATION_PATH,
                self._constellation.satellites,
                EARTH_RADIUS,
                self._current_constellation_time(),
            )
            update_topology_links(
                stage,
                TOPOLOGY_PATH,
                self._topology_links,
                self._constellation,
                EARTH_RADIUS,
                self._current_constellation_time(),
                self._selected_catalog_number,
            )
            if self._selected_catalog_number:
                self._sync_detail_satellite_to_selected(stage)
            else:
                self._set_detail_satellite_visible(stage, False)
        else:
            update_satellite_position(
                stage, SATELLITE_PATH, self._state.sim_time,
                orbit_radius=dynamic_radius,
                orbit_inclination=self._state.orbit_inclination,
                orbit_period=self._state.orbit_period
            )
        self._refresh_business_scene(stage)
        # Keep the global Earth lighting stable. The previous behavior tied the
        # whole scene's sun/dome balance to whether the currently simulated
        # satellite was in eclipse, which made the terminator wobble and caused
        # stray light on the night side of Earth.
        update_eclipse_lighting(stage, False, SUN_LIGHT_PATH)
        update_environment_for_eclipse(stage, False, SUN_LIGHT_PATH, AMBIENT_PATH)
        update_earth_rotation(stage, EARTH_PATH, CLOUDS_PATH, result["earth_rot_y"])

        if self._view_switcher:
            self._view_switcher.sync_scene_visibility(stage)

        # Track satellite with camera in micro view
        if self._view_switcher and self._view_switcher.mode == "satellite":
            from pxr import Gf as _Gf
            if self._constellation and self._selected_catalog_number:
                sat = self._constellation.get(self._selected_catalog_number)
                sx, sy, sz = scene_position_for_satellite(
                    sat,
                    self._current_constellation_time(),
                    EARTH_RADIUS,
                )
            else:
                from .physics.orbital_mechanics import get_orbit_position
                sx, sy, sz = get_orbit_position(
                    self._state.sim_time,
                    orbit_radius=dynamic_radius,
                    tilt_deg=self._state.orbit_inclination,
                    orbit_period=self._state.orbit_period,
                )
            sat_pos = _Gf.Vec3d(sx, sy, sz)
            self._view_switcher.update_micro_camera(stage, sat_pos)

    # ── UI update callback ──────────────────────────────────

    def _on_ui_tick(self, result: dict):
        """Refresh the consolidated control panel."""
        if self._dt_panel:
            self._dt_panel.update_live_status()
        if self._trend:
            self._trend.update()

    # ── Satellite rebuild (DT parameter change) ─────────────

    def _rebuild_satellite(self):
        """Rebuild satellite 3D model after DT parameter change."""
        if not HAS_SCENE or not HAS_KIT:
            return

        stage = omni.usd.get_context().get_stage()
        if stage:
            # Switch viewport away from MicroCam BEFORE the prim is deleted
            if self._view_switcher:
                self._view_switcher.before_satellite_rebuild()
            self._payload_inspection_open = False

            build_satellite(
                stage, SATELLITE_PATH,
                self._state.wing_count, self._state.wing_area,
                self._state.rad_count, self._state.rad_area,
            )
            # Rebuild destroys /World/Satellite children — restore camera & lights
            if self._view_switcher:
                self._view_switcher.on_satellite_rebuilt(stage)

            if self._constellation and self._selected_catalog_number:
                self._sync_detail_satellite_to_selected(stage)
                self._set_detail_satellite_visible(stage, self._view_switcher.mode == "satellite")
            else:
                # Update orbit ring to match current altitude & inclination
                update_orbit_ring(
                    stage,
                    self._state.orbit_altitude,
                    self._state.orbit_inclination,
                    WORLD_ROOT,
                )
            self._logger.add_log(
                "info",
                f"[DT] Rebuilt: {self._state.wing_count}W, {self._state.rad_count}R, "
                f"alt={self._state.orbit_altitude:.0f}km, inc={self._state.orbit_inclination:.1f}°",
                self._state.met_seconds,
            )

    # ── View toggle (orbit ↔ satellite) ─────────────────────

    def _on_view_toggle(self) -> str:
        """
        Toggle between orbit and satellite camera views.
        Returns the new mode string so the UI button can update its label.
        """
        if not self._view_switcher or not HAS_SCENE or not HAS_KIT:
            return "orbit"

        stage = omni.usd.get_context().get_stage()
        if not stage:
            return "orbit"

        if self._constellation and not self._selected_catalog_number and self._view_switcher.mode == "orbit":
            self._logger.add_log("info", "[Constellation] Select a satellite marker first.", self._state.met_seconds)
            return "orbit"

        # Compute current satellite position so camera can snap to it immediately
        sat_pos = None
        try:
            from pxr import Gf as _Gf
            from .scene.earth_builder import EARTH_RADIUS
            if self._constellation and self._selected_catalog_number:
                sat = self._constellation.get(self._selected_catalog_number)
                sx, sy, sz = scene_position_for_satellite(
                    sat,
                    self._current_constellation_time(),
                    EARTH_RADIUS,
                )
            else:
                from .physics.orbital_mechanics import get_orbit_position
                re_km = 6371.0
                dynamic_radius = EARTH_RADIUS * (re_km + self._state.orbit_altitude) / re_km
                sx, sy, sz = get_orbit_position(
                    self._state.sim_time,
                    orbit_radius=dynamic_radius,
                    tilt_deg=self._state.orbit_inclination,
                    orbit_period=self._state.orbit_period,
                )
            sat_pos = _Gf.Vec3d(sx, sy, sz)
        except Exception:
            pass

        self._view_switcher.toggle(stage, sat_pos)
        new_mode = self._view_switcher.mode
        if new_mode == "orbit":
            self._set_payload_inspection(stage, False)
        if self._constellation:
            self._set_detail_satellite_visible(stage, new_mode == "satellite" and bool(self._selected_catalog_number))
        self._logger.add_log(
            "info",
            f"[View] Switched to {'SATELLITE (micro)' if new_mode == 'satellite' else 'ORBIT (macro)'} view",
            self._state.met_seconds,
        )
        return new_mode
