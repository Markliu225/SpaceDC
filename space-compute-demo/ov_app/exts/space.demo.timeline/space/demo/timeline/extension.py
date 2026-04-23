"""space.demo.timeline — owns the Kit-side sim clock mirror.

Backend is the authoritative clock; this extension mirrors the sim_time from
state_update into a local value other extensions can read, and hooks the Kit
playback tick so time-based scene updates can advance even between state packets
(interpolation).
"""
from __future__ import annotations

import logging

import omni.ext  # type: ignore

log = logging.getLogger("space.demo.timeline")


class SpaceDemoTimelineExtension(omni.ext.IExt):
    sim_time_s: float = 0.0

    def on_startup(self, ext_id: str) -> None:
        log.info("[timeline] startup %s", ext_id)
        # TODO(phase-1 step 7): subscribe via space.demo.messaging.on('state_update', ...)

    def on_shutdown(self) -> None:
        log.info("[timeline] shutdown")
