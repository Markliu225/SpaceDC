"""Run one NI-003 satellite alone in a fresh interpreter and save what the test compares.

    python run_alone.py Sat01 <output folder>

Writes ``<key>_fingerprint.json`` (canonical JSON text per archive field), ``<key>_arrays.npz`` (state arrays) and
``<key>_info.json`` (status, error, Power call analysis and the hashes of the files the scene references, before and
after the run). Nothing else is loaded or run in this process.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
sys.path.insert(0, str(HERE))

import ni003_support as support  # noqa: E402


def main() -> int:
    key, out_dir = sys.argv[1], Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    spec = support.RUNS[key]
    files = support.referenced_files(spec["scene"])
    before = {str(p): support.sha256(p) for p in files}
    result = support.run_satellite(spec["scene"], spec["run_id"], spec["instance_id"])
    after = {str(p): support.sha256(p) for p in files}
    archive = result["archive"]
    (out_dir / f"{key}_fingerprint.json").write_text(json.dumps(support.fingerprint(archive)), encoding="utf-8")
    np.savez(out_dir / f"{key}_arrays.npz", **support.main_arrays(archive))
    info = {"status": archive.status, "error": result["error"], "run_id": archive.run_id,
            "log": support.analyse_log(result["log"], spec["run_id"], spec["instance_id"]),
            "power_info": result["power_info"], "hash_before": before, "hash_after": after,
            "modules_loaded": sorted(name for name in sys.modules if name.startswith(("sdtwin_sim", "thermal")))}
    (out_dir / f"{key}_info.json").write_text(json.dumps(info, default=str), encoding="utf-8")
    print(json.dumps({"key": key, "status": archive.status}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
