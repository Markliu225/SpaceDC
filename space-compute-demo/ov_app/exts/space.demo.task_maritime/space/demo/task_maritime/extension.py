"""space.demo.task_maritime — overlay layer + DrawLines link for the maritime case.

Phase 3 implements:
  * Highlighted ocean AOI under the ground track.
  * Mock remote-sensing image + detection boxes rendered as overlay prims.
  * DrawLines-based sat-to-ground downlink + ground-only path when mode toggles.
"""
from __future__ import annotations

import logging

import omni.ext  # type: ignore

log = logging.getLogger("space.demo.task_maritime")


class SpaceDemoMaritimeTaskExtension(omni.ext.IExt):
    def on_startup(self, ext_id: str) -> None:
        log.info("[task_maritime] startup %s", ext_id)
        # TODO(phase-3): subscribe to task_update; drive overlay prims + DrawLines node.

    def on_shutdown(self) -> None:
        log.info("[task_maritime] shutdown")
