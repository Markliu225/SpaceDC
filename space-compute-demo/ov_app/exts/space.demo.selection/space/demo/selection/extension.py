"""space.demo.selection — bridge USD viewport selection → backend.

When the user clicks a prim in the WebRTC Omniverse stream, USD fires a
SELECTION_CHANGED event. We POST the selected prim path to the backend's
/selection endpoint; the backend then broadcasts a `selection_changed`
envelope on the FastAPI WS so every web client's demoStore.selectedPrim
updates in lockstep. This mirrors how space.demo.scene POSTs
/mission/scene_ready — same fire-and-forget HTTP pattern, no WS plumbing
on the Kit side.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Optional

import carb  # type: ignore
import omni.ext  # type: ignore
import omni.usd  # type: ignore

log = logging.getLogger("space.demo.selection")

# 127.0.0.1, NOT localhost: Windows resolves localhost through an IPv6
# attempt first, costing ~0.2 s per request — at a 5 Hz poll that both
# throttles the loop and makes the eased orbital motion visibly lumpy.
BACKEND_BASE = os.environ.get("SPACE_DEMO_BACKEND_HTTP", "http://127.0.0.1:8001").rstrip("/")
SELECTION_URL = f"{BACKEND_BASE}/selection"


def _post_selection(prim_path: str) -> None:
    """Fire-and-forget POST. Silent on error so a flaky backend never spams
    the Kit log on every click."""
    try:
        body = json.dumps({"prim_path": prim_path}).encode("utf-8")
        req = urllib.request.Request(
            SELECTION_URL, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=0.5):
            pass
    except Exception:
        pass


class SpaceDemoSelectionExtension(omni.ext.IExt):
    def on_startup(self, ext_id: str) -> None:
        log.info("[selection] startup %s", ext_id)
        carb.log_info(f"[space.demo.selection] startup {ext_id}")
        self._last_path: Optional[str] = None
        self._sub = None
        try:
            ctx = omni.usd.get_context()
            self._sub = ctx.get_stage_event_stream().create_subscription_to_pop(
                self._on_stage_event, name="space.demo.selection.stage"
            )
        except Exception as exc:  # noqa: BLE001
            carb.log_warn(f"[space.demo.selection] subscribe failed: {exc}")

    def on_shutdown(self) -> None:
        log.info("[selection] shutdown")
        self._sub = None

    # ----- callbacks -------------------------------------------------------
    def _on_stage_event(self, event) -> None:
        # SELECTION_CHANGED == 4 on every Kit version since 2022; check by
        # name so we don't lock to a numeric enum value.
        try:
            etype = int(event.type)
            sel_changed = int(omni.usd.StageEventType.SELECTION_CHANGED)
        except Exception:
            return
        if etype != sel_changed:
            return
        try:
            ctx = omni.usd.get_context()
            paths = list(ctx.get_selection().get_selected_prim_paths())
        except Exception:
            paths = []
        path = paths[0] if paths else ""
        # De-dupe: rapid drag-clicks fire SELECTION_CHANGED several times for
        # the same prim. POSTing once per real change keeps the WS quiet.
        if path == self._last_path:
            return
        self._last_path = path
        carb.log_info(f"[space.demo.selection] -> backend prim_path={path!r}")
        _post_selection(path)
