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

import time
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
from .physics.telemetry import TelemetryLogger
from .simulation_engine import SimulationEngine

# Conditional scene imports (need pxr)
try:
    from .scene.earth_builder import (
        build_earth_scene, update_satellite_position, update_eclipse_lighting,
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


# ── Prim paths ──────────────────────────────────────────────
WORLD_ROOT = "/World"
SATELLITE_PATH = "/World/Satellite"
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

        # Kit subscription
        self._update_sub = None

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

        # 4. Build UI panels
        self._dt_panel = DigitalTwinPanel(
            self._state,
            on_rebuild=self._rebuild_satellite,
            on_state_change=lambda: None,
        )
        self._dt_panel.build()

        self._telem_panel = TelemetryPanel(self._logger)
        self._telem_panel.build()

        self._hud = HUDOverlay(self._state, self._logger)
        self._hud.build()

        self._trend = TrendChartPanel(self._state)
        self._trend.build()

        # 5. Subscribe to Kit update loop
        if HAS_KIT:
            app = omni.kit.app.get_app()
            self._update_sub = app.get_update_event_stream().create_subscription_to_pop(
                self._on_kit_update, name="spacedc.digital_twin.update"
            )

        self._logger.add_log("ok", "SpaceDC Digital Twin initialized.", 0)
        print("[SpaceDC] Extension startup complete ✓")

    def on_shutdown(self):
        print("[SpaceDC] Extension shutting down...")

        # Unsubscribe from update loop
        if self._update_sub:
            self._update_sub = None

        # Destroy UI
        if self._dt_panel:
            self._dt_panel.destroy()
        if self._telem_panel:
            self._telem_panel.destroy()
        if self._hud:
            self._hud.destroy()
        if self._trend:
            self._trend.destroy()

        print("[SpaceDC] Extension shutdown complete")

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

        # Use dynamic orbit parameters for scene position
        # Convert altitude KM to scene units (placeholder: ORBIT_RADIUS corresponds to ~550km)
        # For simplicity, we keep visual ORBIT_RADIUS constant or scale it slightly
        from .scene.earth_builder import ORBIT_RADIUS
        dynamic_radius = ORBIT_RADIUS * (1.0 + (self._state.orbit_altitude - 550.0) / 6371.0)
        
        update_satellite_position(
            stage, SATELLITE_PATH, self._state.sim_time,
            orbit_radius=dynamic_radius,
            orbit_inclination=self._state.orbit_inclination,
            orbit_period=self._state.orbit_period
        )
        update_eclipse_lighting(stage, result["eclipse"], SUN_LIGHT_PATH)
        update_environment_for_eclipse(stage, result["eclipse"], SUN_LIGHT_PATH, AMBIENT_PATH)
        update_earth_rotation(stage, EARTH_PATH, CLOUDS_PATH, result["earth_rot_y"])

    # ── UI update callback ──────────────────────────────────

    def _on_ui_tick(self, result: dict):
        """Refresh HUD and trend chart."""
        if self._hud:
            self._hud.update()
        if self._trend:
            self._trend.update()

    # ── Satellite rebuild (DT parameter change) ─────────────

    def _rebuild_satellite(self):
        """Rebuild satellite 3D model after DT parameter change."""
        if not HAS_SCENE or not HAS_KIT:
            return

        stage = omni.usd.get_context().get_stage()
        if stage:
            build_satellite(
                stage, SATELLITE_PATH,
                self._state.wing_count, self._state.wing_area,
                self._state.rad_count, self._state.rad_area,
            )
            self._logger.add_log(
                "info",
                f"[DT] Satellite rebuilt: {self._state.wing_count} wings, {self._state.rad_count} radiators.",
                self._state.met_seconds,
            )
