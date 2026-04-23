"""Load mock cases from data/cases/*. Phase 3 will implement the maritime case state machine."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import json

CASES_DIR = Path(__file__).parent.parent / "data" / "cases"


def load_case(case_id: str) -> dict[str, Any]:
    path = CASES_DIR / case_id / "case.json"
    if not path.exists():
        return {"id": case_id, "stages": []}
    return json.loads(path.read_text(encoding="utf-8"))
