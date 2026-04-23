# space-compute-demo

Omniverse + Web digital twin for a 1MW-class space compute data center.

## Architecture

```
Browser (React) ──WebRTC──► Omniverse Kit App (USD Viewer)
      │                              │
      └────────── WebSocket ─────────┤
                                     ▼
                            Backend (FastAPI)
                         physics + state engine
```

- **web/** — React + TS + Zustand + ECharts UI shell (port 5173)
- **backend/** — FastAPI state engine + WebSocket broadcast (port 8000)
- **ov_app/** — Kit application + custom extensions (port 8211 streaming)
- **usd/** — scene stage, layers, variants
- **assets_raw/** — imported CAD (STEP / FBX / glTF)
- **assets_usd/** — converted USD
- **data/** — configs, mock cases
- **docs/** — specs (exec book, api, ui, pipeline)

## Getting started

```
# backend
cd backend && python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8001

# web
cd web && npm install && npm run dev
```

Kit app setup — see [docs/kit_setup.md](docs/kit_setup.md) (TBD).

## Status

Phase 1 in progress — streaming skeleton + minimal message loop.
