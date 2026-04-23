"""space.demo.core — bootstrap + initial stage load.

Opens usd/overview.usda at startup. Subsequent stage swapping (on camera
preset change) is handled by space.demo.scene.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

try:
    import omni.ext  # type: ignore
    import omni.usd  # type: ignore
    import omni.kit.app  # type: ignore
    _HAS_KIT = True
except ImportError:
    _HAS_KIT = False

try:
    import carb  # type: ignore
    _HAS_CARB = True
except ImportError:
    _HAS_CARB = False


def _log(msg: str) -> None:
    print(f"[space.demo.core] {msg}", flush=True)
    if _HAS_CARB:
        carb.log_info(f"[space.demo.core] {msg}")


log = logging.getLogger("space.demo.core")

USD_ROOT_ENV = "SPACE_DEMO_USD_ROOT"
INITIAL_STAGE = os.environ.get("SPACE_DEMO_INITIAL_STAGE", "overview.usda")


def _discover_usd_root() -> Optional[Path]:
    env = os.environ.get(USD_ROOT_ENV)
    if env:
        p = Path(env)
        if p.is_dir():
            return p
        if p.is_file():
            return p.parent
        _log(f"USD_ROOT env set to non-existent path: {env}")

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "usd"
        if candidate.is_dir():
            return candidate
    return None


if _HAS_KIT:
    class SpaceDemoCoreExtension(omni.ext.IExt):  # type: ignore[misc]
        def on_startup(self, ext_id: str) -> None:
            _log(f"startup {ext_id}")
            _log(f"env SPACE_DEMO_USD_ROOT={os.environ.get(USD_ROOT_ENV, '<unset>')}")
            usd_dir = _discover_usd_root()
            if not usd_dir:
                _log("no USD root discovered; stage stays empty")
                return
            stage_path = usd_dir / INITIAL_STAGE
            if not stage_path.is_file():
                _log(f"initial stage missing: {stage_path}")
                return
            try:
                omni.usd.get_context().open_stage(str(stage_path))
                _log(f"opened initial stage {stage_path}")
            except Exception as exc:  # noqa: BLE001
                _log(f"failed to open {stage_path}: {exc}")

        def on_shutdown(self) -> None:
            _log("shutdown")
else:
    class SpaceDemoCoreExtension:  # type: ignore[no-redef]
        pass
