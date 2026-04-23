"""space.demo.selection — pick handling.

On USD selection changes, push a ``selection_changed`` message back through
space.demo.messaging so the web UI can update.
"""
from __future__ import annotations

import logging

import omni.ext  # type: ignore

log = logging.getLogger("space.demo.selection")


class SpaceDemoSelectionExtension(omni.ext.IExt):
    def on_startup(self, ext_id: str) -> None:
        log.info("[selection] startup %s", ext_id)
        # TODO(phase-2): subscribe to omni.usd selection events; emit selection_changed.

    def on_shutdown(self) -> None:
        log.info("[selection] shutdown")
