"""space.demo.camera — named presets + smooth switch.

Presets resolve to camera prims at ``/World/Cameras/<Preset>``; this extension
listens for ``change_camera`` messages and sets the active viewport camera.
"""
from __future__ import annotations

import logging

import omni.ext  # type: ignore

log = logging.getLogger("space.demo.camera")

PRESETS = {
    "overview":  "/World/Cameras/Overview",
    "satellite": "/World/Cameras/Satellite",
    "task":      "/World/Cameras/Task",
    "compare":   "/World/Cameras/Compare",
}


class SpaceDemoCameraExtension(omni.ext.IExt):
    def on_startup(self, ext_id: str) -> None:
        log.info("[camera] startup %s", ext_id)
        # TODO(phase-1 step 7): subscribe via messaging.on('change_camera', ...)

    def on_shutdown(self) -> None:
        log.info("[camera] shutdown")

    def set_camera(self, preset: str) -> None:
        prim = PRESETS.get(preset)
        if not prim:
            log.warning("[camera] unknown preset %s", preset)
            return
        try:
            import omni.kit.viewport.utility as vp  # type: ignore
            vp.get_active_viewport().camera_path = prim
            log.info("[camera] active -> %s", prim)
        except Exception as exc:  # noqa: BLE001
            log.error("[camera] failed to set camera %s: %s", prim, exc)
