# backend

FastAPI state engine — single source of business truth.

## Run

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --reload --port 8001
```

Then:

- `GET http://localhost:8001/health` → sanity.
- `WS  ws://localhost:8001/ws/state` → receives `state_update` @ 1Hz.

> Port **8001** (not 8000) — 8000 may be occupied by an unrelated process on this machine.

## Structure

- `app.py` — FastAPI + WebSocket endpoint + command dispatch.
- `state_engine.py` — tick loop + state mutations. Phase 1 uses placeholder numerics.
- `models.py` — Pydantic models (authoritative per [../docs/api_spec.md](../docs/api_spec.md)).
- `case_loader.py` — reads `data/cases/<case_id>/case.json` (Phase 3).
- `services/` — future physics modules (migrated from `exts/spacedc.digital_twin/physics/`).

## Phase plan

- **Phase 1 (current)**: placeholder sinusoidal physics so UI has something to show.
- **Phase 2**: migrate `orbital_mechanics`, `solar_array_model`, `thermal_model`, `battery_model` from existing Kit extension into `services/`.
- **Phase 3**: maritime task state machine (7 phases).
