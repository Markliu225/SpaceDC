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

from .physics.state import SimState
from .physics.constellation import (
    HAS_SGP4,
    ConstellationData,
    build_dawn_dusk_constellation,
    load_tle_file,
    scene_position_for_satellite,
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
        build_constellation,
        update_constellation_positions,
        get_selected_catalog_number_from_path,
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
from .ui.telemetry_panel import TelemetryPanel, HUDOverlay
from .ui.trend_chart import TrendChartPanel
from .ui.satellite_status_window import SatelliteStatusWindow
from .ui.view_switcher import ViewSwitcher
from .ui.component_info_popup import ComponentInfoPopup


# ── Prim paths ──────────────────────────────────────────────
WORLD_ROOT = "/World"
SATELLITE_PATH = "/World/Satellite"
CONSTELLATION_PATH = "/World/Constellation"
SUN_LIGHT_PATH = "/World/Sun/SunLight"
AMBIENT_PATH = "/World/Lights/Ambient"
EARTH_PATH = "/World/Earth"
CLOUDS_PATH = "/World/Clouds"


class SpaceDCExtension(omni.ext.IExt if HAS_KIT else object):
    """
    ORBITAL DC-1 — Space Data Center Digital Twin Extension.

    When running inside Omniverse Kit:
      - Creates the full USD scene (Earth, satellite, lighting)
      - Opens Digital Twin control panel, HUD, telemetry log, trend chart
      - Subscribes to the Kit update loop for simulation ticks
    """

    def __init__(self):
        super().__init__()
        self._state: Optional[SimState] = None
        self._logger: Optional[TelemetryLogger] = None
        self._engine: Optional[SimulationEngine] = None

        # UI panels
        self._dt_panel: Optional[DigitalTwinPanel] = None
        self._telem_panel: Optional[TelemetryPanel] = None
        self._hud: Optional[HUDOverlay] = None
        self._trend: Optional[TrendChartPanel] = None
        self._sat_status: Optional[SatelliteStatusWindow] = None
        self._view_switcher: Optional[ViewSwitcher] = None
        self._component_popup: Optional[ComponentInfoPopup] = None
        self._constellation: Optional[ConstellationData] = None
        self._selected_catalog_number: Optional[str] = None
        self._constellation_epoch_base = datetime.now(timezone.utc)

        # Kit subscription
        self._update_sub = None
        self._selection_sub = None

    # ── Lifecycle ───────────────────────────────────────────

    def on_startup(self, ext_id: str = ""):
        print(f"[SpaceDC] Extension starting up... HAS_KIT={HAS_KIT}, HAS_SCENE={HAS_SCENE}")

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
                    self._scene_built = True
                    print("[SpaceDC] USD scene built OK")
                except Exception as e:
                    print(f"[SpaceDC] ERROR building scene: {e}")
                    import traceback; traceback.print_exc()
            else:
                print("[SpaceDC] Stage not ready at startup, will build on first tick")

        # 4. Create view switcher
        self._view_switcher = ViewSwitcher()

        # 5. Build UI panels
        self._dt_panel = DigitalTwinPanel(
            self._state,
            on_rebuild=self._rebuild_satellite,
            on_state_change=lambda: None,
            on_view_toggle=self._on_view_toggle,
            on_load_constellation=self._load_constellation_from_path,
            on_load_sdc_demo=self._load_sdc_demo_constellation,
            on_clear_constellation=self._clear_constellation,
            default_constellation_path=self._get_default_constellation_path(),
        )
        self._dt_panel.build()

        self._telem_panel = TelemetryPanel(self._logger)
        self._telem_panel.build()

        self._hud = HUDOverlay(self._state, self._logger)
        self._hud.build()

        self._trend = TrendChartPanel(self._state)
        self._trend.build()

        self._sat_status = SatelliteStatusWindow(self._state)
        self._sat_status.build()

        # 5b. Component click-to-inspect popup
        self._component_popup = ComponentInfoPopup(self._state)
        self._component_popup.start()

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
        if self._telem_panel:
            self._telem_panel.destroy()
        if self._hud:
            self._hud.destroy()
        if self._trend:
            self._trend.destroy()
        if self._sat_status:
            self._sat_status.destroy()
        if self._view_switcher:
            self._view_switcher.destroy()
        if self._component_popup:
            self._component_popup.destroy()

        print("[SpaceDC] Extension shutdown complete")

    def _get_default_constellation_path(self) -> str:
        this_dir = os.path.dirname(os.path.abspath(__file__))
        ext_root = os.path.normpath(os.path.join(this_dir, "..", "..", ".."))
        return os.path.join(ext_root, "data", "orbits", "sample_tle.tle")

    def _current_constellation_time(self) -> datetime:
        return self._constellation_epoch_base + timedelta(seconds=self._state.met_seconds)

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
        self._load_sdc_demo_constellation(auto=True)

    def _load_sdc_demo_constellation(self, auto: bool = False) -> None:
        if not HAS_SCENE or not HAS_KIT:
            return
        stage = omni.usd.get_context().get_stage()
        if not stage:
            return

        from .scene.earth_builder import EARTH_RADIUS

        if self._view_switcher and self._view_switcher.mode == "satellite":
            self._view_switcher.switch_to_orbit(stage)

        constellation = build_dawn_dusk_constellation(
            count=6,
            altitude_km=575.0,
            inclination_deg=97.8,
        )

        self._constellation = constellation
        self._selected_catalog_number = None
        self._constellation_epoch_base = datetime.now(timezone.utc)
        build_constellation(stage, CONSTELLATION_PATH, constellation.satellites, EARTH_RADIUS, None)
        update_constellation_positions(
            stage,
            CONSTELLATION_PATH,
            constellation.satellites,
            EARTH_RADIUS,
            self._current_constellation_time(),
        )
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
            self._view_switcher.switch_to_orbit(stage)

        self._constellation = constellation
        self._selected_catalog_number = None
        self._constellation_epoch_base = datetime.now(timezone.utc)
        build_constellation(stage, CONSTELLATION_PATH, constellation.satellites, EARTH_RADIUS, None)
        update_constellation_positions(
            stage,
            CONSTELLATION_PATH,
            constellation.satellites,
            EARTH_RADIUS,
            self._current_constellation_time(),
        )
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
            orbit_prim = stage.GetPrimAtPath(f"{WORLD_ROOT}/OrbitRing")
            if orbit_prim and orbit_prim.IsValid():
                try:
                    from pxr import UsdGeom
                    UsdGeom.Imageable(orbit_prim).MakeVisible()
                except Exception:
                    pass
            self._set_detail_satellite_visible(stage, True)

        self._constellation = None
        self._selected_catalog_number = None
        self._set_default_tracked_target()
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
        update_constellation_positions(
            stage,
            CONSTELLATION_PATH,
            self._constellation.satellites,
            EARTH_RADIUS,
            self._current_constellation_time(),
        )
        self._sync_detail_satellite_to_selected(stage)
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
        catalog_number = get_selected_catalog_number_from_path(paths[0])
        if catalog_number:
            self._select_constellation_satellite(catalog_number, switch_to_micro=True)

    # ── Kit update callback ─────────────────────────────────

    def _on_kit_update(self, event):
        """Called every frame by Omniverse Kit."""
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
                    print("[SpaceDC] USD scene built OK (deferred)")
                    self._load_default_constellation()
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
        # Keep the global Earth lighting stable. The previous behavior tied the
        # whole scene's sun/dome balance to whether the currently simulated
        # satellite was in eclipse, which made the terminator wobble and caused
        # stray light on the night side of Earth.
        update_eclipse_lighting(stage, False, SUN_LIGHT_PATH)
        update_environment_for_eclipse(stage, False, SUN_LIGHT_PATH, AMBIENT_PATH)
        update_earth_rotation(stage, EARTH_PATH, CLOUDS_PATH, result["earth_rot_y"])

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
        """Refresh HUD and trend chart."""
        if self._hud:
            self._hud.update()
        if self._trend:
            self._trend.update()
        if self._sat_status:
            self._sat_status.update()
        if self._component_popup:
            self._component_popup.update()

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
        if self._constellation:
            self._set_detail_satellite_visible(stage, new_mode == "satellite" and bool(self._selected_catalog_number))
        self._logger.add_log(
            "info",
            f"[View] Switched to {'SATELLITE (micro)' if new_mode == 'satellite' else 'ORBIT (macro)'} view",
            self._state.met_seconds,
        )
        return new_mode
