# API Spec — space-compute-demo

Frozen at Phase 0. Changes require explicit user approval.

## Transport

- **Web ↔ Backend**: WebSocket `ws://host:8001/ws/state` (JSON messages).
- **Web ↔ Kit**: via WebRTC Streaming Library message channel. Messages tunnelled through the same envelope as below.
- **Backend ↔ Kit**: Kit subscribes to the backend WS as a client; Backend is the single source of truth for business state.

## Envelope

All messages share:

```json
{ "type": "<command>", "ts": 1713720000.123, "payload": { ... } }
```

Request/response messages add `request_id` (uuid4 string) and the response carries the same `request_id`.

## Client → Server (Web → Backend / Kit)

| type               | payload                                                       | response      |
|--------------------|---------------------------------------------------------------|---------------|
| `play`             | `{}`                                                          | ack           |
| `pause`            | `{}`                                                          | ack           |
| `reset`            | `{}`                                                          | ack           |
| `set_time`         | `{ "sim_time_s": float }`                                     | ack           |
| `set_parameters`   | `{ "orbit_type"?, "gpu_type"?, "bandwidth_mbps"?, ... }`      | ack           |
| `set_mode`         | `{ "mode": "on_orbit" \| "ground_only" }`                     | ack           |
| `start_task`       | `{ "case_id": "maritime_case_01" }`                           | `task_update` |
| `select_object`    | `{ "prim_path": "/World/Satellite" }`                         | `selection_changed` |
| `change_camera`    | `{ "preset": "overview" \| "satellite" \| "task" \| "compare" }` | `camera_changed` |

## Server → Client (Backend / Kit → Web)

| type                | payload                                                                                     |
|---------------------|---------------------------------------------------------------------------------------------|
| `scene_ready`       | `{ "stage_path": "/World", "object_ids": [...] }` — emitted once per Kit session            |
| `state_update`      | `{ "sim_time_s", "satellite": SatelliteState, "ground_station": GroundStationState }` @1Hz |
| `task_update`       | `{ "task": TaskState }` — on state machine transitions                                      |
| `selection_changed` | `{ "prim_path", "details": {...} }`                                                         |
| `camera_changed`    | `{ "preset", "prim_path" }`                                                                 |
| `error`             | `{ "code", "message", "request_id"? }`                                                      |
| `ack`               | `{ "request_id", "ok": bool, "detail"? }`                                                   |

## Data models

See [models.py](../backend/models.py) — authoritative Pydantic definitions.

## Update cadence

- Logical tick: 1 Hz (backend drives).
- `state_update` broadcast: 1 Hz.
- `task_update`: event-driven (on state machine transitions only).
- Web interpolates between ticks for display; it does not derive physics.
