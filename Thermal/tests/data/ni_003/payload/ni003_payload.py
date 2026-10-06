"""NI-003 payload module: it must never be imported by the scene loader.

The asset ``assets/power_controller_payload_model.json`` names ``ni003_payload:execute`` as its thermal ``model_id``,
the way a plug-in hook would. Thermal design 9.3 says the model name is a controlled lookup key and ``model_id`` does
not permit arbitrary code execution, so the loader must reject the id without importing this module. The probe
``probe_no_exec.py`` puts this folder on ``sys.path`` so that an attempted import would succeed, and imports the
module itself only as a positive control. Importing it writes the marker text to the file named by the environment
variable ``NI003_SENTINEL``; without that variable it does nothing.
"""

from __future__ import annotations

import os
from pathlib import Path

MARKER = "NI003-MODEL-ID-PAYLOAD-IMPORTED"
_target = os.environ.get("NI003_SENTINEL")
if _target:
    Path(_target).write_text(MARKER, encoding="utf-8")


def execute(*args, **kwargs):
    """Entry point named by the payload model_id; writes the marker again if it is ever called."""

    if _target:
        Path(_target).write_text(MARKER + " execute", encoding="utf-8")
    return MARKER
