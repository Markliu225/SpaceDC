"""NI-003 probe: load scenes whose model_id or USD file carries code under a Python audit hook and report what ran.

    python probe_no_exec.py <sentinel path>

Prints one JSON line. The ``payload`` folder is put on ``sys.path`` so that an attempted import of the module named
by the payload ``model_id`` would succeed. Two windows are watched: loading ``scenes/sat01_payload_model.json``
(thermal model_id ``ni003_payload:execute``) and assembling ``scenes/sat01_payload_usd.json`` (registered models, Python
source text in a custom USD attribute and in the layer metadata). In each window the hook records ``import``,
``compile``, ``exec`` and process or library loading events and whether they carry a payload marker; afterwards the
sentinel file and ``sys.modules`` are inspected. Two positive controls then import the payload module and execute the
USD source text on purpose, to show that the hook and the sentinel detect execution when it happens.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
sys.path.insert(0, str(HERE / "payload"))
sys.dont_write_bytecode = True  # the positive control must not leave a compiled payload next to the test data

SENTINEL = Path(sys.argv[1])
os.environ["NI003_SENTINEL"] = str(SENTINEL)
MARKERS = ("NI003-USD-PAYLOAD-EXECUTED", "NI003-MODEL-ID-PAYLOAD-IMPORTED", "ni003_payload")
SPAWN_EVENTS = ("os.system", "subprocess.Popen", "os.exec", "os.posix_spawn", "os.spawn", "os.startfile",
                "ctypes.dlopen", "pickle.find_class", "marshal.loads", "marshal.load")

window: dict = {"name": None}
events: list[dict] = []


def _has_marker(value: object) -> bool:
    try:
        text = value.decode("utf-8", "replace") if isinstance(value, (bytes, bytearray)) else repr(value)
    except Exception:  # noqa: BLE001
        return False
    return any(marker in text for marker in MARKERS)


def hook(event: str, args: tuple) -> None:
    name = window["name"]
    if name is None:
        return
    try:
        if event == "import":
            events.append({"window": name, "event": event, "module": str(args[0]), "marker": _has_marker(args[0])})
        elif event == "exec":
            code = args[0]
            marker = _has_marker(getattr(code, "co_consts", ())) or _has_marker(getattr(code, "co_filename", ""))
            events.append({"window": name, "event": event, "filename": str(getattr(code, "co_filename", "?")),
                           "marker": marker})
        elif event == "compile":
            events.append({"window": name, "event": event, "filename": str(args[1]), "marker": _has_marker(args[0])})
        elif event in SPAWN_EVENTS:
            events.append({"window": name, "event": event, "args": repr(args)[:200], "marker": _has_marker(args)})
    except Exception:  # noqa: BLE001  (the hook must never break the probed code)
        pass


sys.addaudithook(hook)

from pxr import Usd  # noqa: E402

from sdtwin_sim import scene as sc  # noqa: E402
from thermal import assemble_thermal_parameters  # noqa: E402

SCENES = HERE / "scenes"


def window_events(name: str) -> dict:
    selected = [e for e in events if e["window"] == name]
    return {
        "count": len(selected),
        "with_marker": sum(1 for e in selected if e["marker"]),
        "imports": sorted({e["module"] for e in selected if e["event"] == "import"}),
        "exec": sum(1 for e in selected if e["event"] == "exec"),
        "compile": sum(1 for e in selected if e["event"] == "compile"),
        "spawn_or_load": sum(1 for e in selected if e["event"] in SPAWN_EVENTS),
    }


def surfaces(params) -> list:
    return [(s.surface_id, s.node_id, s.area_m2, tuple(float(v) for v in s.normal_body), s.absorptivity,
             s.emissivity) for s in params.surfaces]


def state() -> dict:
    return {"sentinel_exists": SENTINEL.exists(),
            "sentinel_text": SENTINEL.read_text(encoding="utf-8") if SENTINEL.exists() else None,
            "module_loaded": "ni003_payload" in sys.modules}


result: dict = {"sentinel_before": SENTINEL.exists()}
base = sc.assemble_scene(HERE.parent / "simready" / "sat01_scene.json")
base_params = assemble_thermal_parameters(*base.thermal_inputs())

window["name"] = "payload_model"
try:
    sc.load_scene(SCENES / "sat01_payload_model.json")
    outcome = {"rejected": False, "error_type": None, "message": None}
except Exception as exc:  # noqa: BLE001
    outcome = {"rejected": True, "error_type": type(exc).__name__, "message": str(exc)}
window["name"] = None
outcome.update(state())
outcome["events"] = window_events("payload_model")
result["payload_model"] = outcome

window["name"] = "payload_usd"
try:
    assembly = sc.assemble_scene(SCENES / "sat01_payload_usd.json")
    params = assemble_thermal_parameters(*assembly.thermal_inputs())
    same = (params.C_J_K.tobytes() == base_params.C_J_K.tobytes()
            and params.R_K_W.tobytes() == base_params.R_K_W.tobytes()
            and surfaces(params) == surfaces(base_params))
    outcome = {"accepted": True, "same_parameters_as_sat01": bool(same), "error": None,
               "controller_asset": assembly.provenance["instances"]["Controller01"]["asset_id"]}
except Exception as exc:  # noqa: BLE001
    outcome = {"accepted": False, "same_parameters_as_sat01": False, "error": f"{type(exc).__name__}: {exc}"}
window["name"] = None
outcome.update(state())
outcome["events"] = window_events("payload_usd")
result["payload_usd"] = outcome

window["name"] = "control_import"
importlib.import_module("ni003_payload")
window["name"] = None
result["control_import"] = {**state(), "events": window_events("control_import")}
SENTINEL.unlink(missing_ok=True)

stage = Usd.Stage.Open(str(HERE / "geometry" / "power_controller_payload.usda"))
code_text = stage.GetPrimAtPath("/PowerController/Housing").GetAttribute("sdtwin:thermal_model_code").Get()
window["name"] = "control_exec"
exec(code_text, {})  # noqa: S102  positive control: the probe itself executes the USD text on purpose
window["name"] = None
result["control_exec"] = {**state(), "events": window_events("control_exec"), "code_text": str(code_text)}
SENTINEL.unlink(missing_ok=True)

print(json.dumps(result))
