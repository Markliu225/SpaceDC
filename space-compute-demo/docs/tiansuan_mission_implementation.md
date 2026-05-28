# 天数天算 Mission Scene — Full Implementation Prompt

## Mission

Build the **天数天算 (compute-in-space) mission scene** on a new `/mission`
page. It choreographs a single end-to-end task that proves the product
thesis: data captured in orbit is computed in orbit, and only the tiny
result comes down.

One task cycle, staged across multiple satellites:

```
AOI acquired → Sensor sat captures 5 GB → ISL routes to Compute Hub →
Hub runs inference (5 GB → 2 MB) → result downlinks via GSL to a Ground
Station → delivered (ship detections shown)
```

The 3D choreography lives in Omniverse (data packet flying along ISL/GSL
beams, AOI highlight on Earth, Hub GPU pulse). The Web `/mission` page
drives it (Start Task, time controls, sat selection) and shows the live
mission status (phase rail, data-volume shrink, latency clock, cast,
event log).

## Locked design decisions — do not relitigate

- **Scope**: single-task choreography. NO dual 天数天算/天数地算 split
  view. (A static "ground compute would have taken ~40 min" callout is
  allowed as a one-line caption, but no second animated path.)
- **Page**: new route `/mission`.
- **3D**: choreography authored in Omniverse on the overview (geo-scale)
  stage, gated behind a `/World/MissionGroup` that's only visible while a
  mission is active.
- **Cast**: roles assigned by the backend over the active constellation —
  one Sensor sat (nearest the AOI), one Compute Hub (the designated DGX
  data-center sat), one Ground Station.
- **Timeline**: phase durations are real animation seconds (not
  sim-time-scaled) so the beats are legible regardless of orbit speed.

## Workflow rules (CRITICAL)

1. **STRICT ordering**: Frontend (`/mission` page + mission store/types)
   first → git commit → Backend MissionEngine → git commit → Omniverse
   choreography → git commit.
2. **Self-verify every meaningful change** (table in §7). Never finish on
   a known-broken state.
3. **Verification loop is non-negotiable**: run → look → fix until the
   current phase is green.
4. **Asset policy**: reuse first (overview.usda Earth + fleet, existing
   BasisCurves ring authoring in space.demo.scene). Author new prims
   procedurally only where nothing fits; follow the existing
   `tools/gen_*.py` print-USDA pattern and the scene-extension's runtime
   prim authoring (UsdGeom.Points / BasisCurves) pattern.
5. **Numbers**: from §3 tables. Do not invent.
6. **TodoWrite**: track every step.
7. **Commits**: stage only relevant files. Leave `.claude/`, the Chinese
   design docs, and the 8K Earth textures untracked.

---

## §1 — Existing context (read first)

```
web/src/pages/OverviewPage.tsx                 — grid layout pattern
web/src/pages/TaskExecutionPage.tsx            — existing task page + 7-phase rail
web/src/pages/SatelliteTwinPage.tsx            — recent 4-row layout + hooks usage
web/src/store/demoStore.ts                     — WS commands + lastState
web/src/store/useTelemetryStore.ts             — fleet, presets, selectedSatIdx
web/src/hooks/useBackendBridge.ts              — state_update → store mirror
web/src/hooks/useFleetPositions.ts             — Walker ECI → lat/lon (Web side)
web/src/components/overview/EarthViewport.tsx  — Omniverse stream embed
web/src/App.tsx                                — route registration
backend/models.py                              — StatePacket, TaskState
backend/state_engine.py                        — 1Hz tick, fleet propagation, snapshot
backend/app.py                                 — WS handlers, /constellations
backend/services/constellations.py            — Walker presets, propagate_fleet
ov_app/exts/space.demo.scene/.../extension.py  — fleet render, ring authoring,
                                                 _on_poll / _on_update, swap_stage
usd/overview.usda                              — Earth + ConstellationGroup + camera
```

You MUST read these before writing code.

---

## §2 — `/mission` page layout (1440×900)

```
┌────────────────────────────────────────────────────────────────────────┐
│ Header: "天数天算 MISSION" · Start Task · ▶❚❚ time controls       56px  │
├──────────────────────────────────────────────┬─────────────────────────┤
│                                              │ Mission Status (col-4)  │
│                                              │  Phase rail (7 phases)  │
│  EarthViewport / SceneEmbed (col-8)          │  Current phase detail   │
│  geo-scale: Earth + fleet + AOI + data       │  ─────────────────      │
│  packet + ISL/GSL beams                      │  Data volume: 5GB→2MB   │
│                                              │  Latency clock (s)      │
│                                              │  Targets found: N       │
│                                              │  ─────────────────      │
│                                              │  Cast:                  │
│                                              │   Sensor  SAT-xx        │
│                                              │   Hub     SAT-yy        │
│                                              │   Ground  GS-zz         │
├──────────────────────────────────────────────┴─────────────────────────┤
│ Event log — capture / route / infer / downlink / deliver    col-12·150 │
└────────────────────────────────────────────────────────────────────────┘
```

Grid rows: `56px minmax(0,1fr) 150px`. Columns `repeat(12, minmax(0,1fr))`.

The viewport binds the overview (geo) camera preset since the mission spans
the whole constellation. On mount: `changeCamera('overview')` (or a new
`'mission'` preset — see §6).

---

## §3 — Mission phases + data tables (authoritative)

### Phase state machine

| phase     | label          | duration_s | backend effect                              | 3D choreography |
|-----------|----------------|-----------|----------------------------------------------|-----------------|
| idle      | Idle           | —         | waiting for start                            | MissionGroup hidden |
| acquire   | AOI Acquired   | 2         | pick sensor = fleet sat nearest AOI lat/lon  | AOI ring pulses on Earth |
| capture   | Capturing      | 3         | data_volume_mb = 5120; targets_found = 0     | sensor flashes; packet spawns BIG at sensor |
| route     | ISL Routing    | 4         | packet en route sensor→hub                   | packet flies sensor→hub along ISL beam |
| compute   | Inferencing    | 5         | data_volume_mb 5120→2 (ease); targets_found rolls 0→N | hub GPU pulse; packet shrinks |
| downlink  | Downlinking    | 3         | result en route hub→ground                   | small packet flies hub→ground via GSL beam |
| deliver   | Delivered      | 2         | alerts set; result frozen                    | ground station flashes; result card |

After `deliver`, return to `idle` (auto-loop OR wait for next Start — see
decision in §5).

`phase_progress` ∈ [0,1] advances within each phase; the Kit choreography
interpolates the packet position by `phase_progress`.

### Constants

```
RAW_DATA_MB        = 5120        # one maritime capture
RESULT_MB          = 2           # detections payload after inference
TARGETS_FOUND      = 7           # ships detected (demo)
GROUND_COMPUTE_REF_S = 2460      # 41 min — static caption only ("天数地算 would be ~41 min")
SPACE_COMPUTE_LATENCY_S ≈ sum(capture..deliver durations) = 17 s demo
```

### Cast assignment

- **Sensor**: fleet sat whose sub-sat lat/lon is nearest the AOI at task
  start (great-circle distance over the propagated fleet).
- **Hub**: a designated "compute hub" — for the demo, the fleet sat with
  index 0 (plane 0 / sat 0), OR the sat nearest the geometric centre of
  the visible fleet. Pick one and document it.
- **Ground Station**: nearest of a small hard-coded GS list (e.g. Svalbard
  78.2N/15.4E, Reykjavik 64.1N/-21.9W, Guam 13.4N/144.8E) to the hub's
  sub-sat point.

### AOI

Hard-code a maritime AOI for the demo: **Pacific NW, lat 38.0, lon -145.0**
(open ocean). One AOI is enough for single-task scope.

---

## §4 — Phase 1: Frontend

### Files to create

```
web/src/pages/MissionPage.tsx
web/src/store/useMissionStore.ts          # or extend useTelemetryStore
web/src/hooks/useMissionFeed.ts           # mirror state_update.mission -> store
web/src/components/mission/PhaseRail.tsx
web/src/components/mission/MissionStatus.tsx
web/src/components/mission/DataVolumeBar.tsx
web/src/components/mission/LatencyClock.tsx
web/src/components/mission/MissionCast.tsx
web/src/components/mission/MissionEventLog.tsx  # or reuse overview EventLog
web/snap_mission.mjs
```

### Files to modify

```
web/src/types/messages.ts     # add MissionState interface + StatePacket.mission
web/src/store/demoStore.ts     # add startMission()/stopMission() WS commands
web/src/App.tsx                # register /mission route
web/src/components/AppShell.tsx  # add "Mission" nav link
```

### Behaviour (Phase 1 = local mock until backend lands)

- PhaseRail: 7 chips (idle excluded or shown faint), current phase
  highlighted, completed phases checkmarked. Pattern: TaskExecutionPage's
  existing rail.
- DataVolumeBar: animates 5 GB → 2 MB during `compute` (log-scale bar so
  the 2500× shrink reads).
- LatencyClock: counts up from `capture` start; freezes at `deliver`.
  Caption underneath: "天数地算 ≈ 41 min" (static, grey).
- MissionCast: Sensor / Hub / Ground rows; click a sat row → set
  `selectedSatIdx` (reuse store) so it highlights in 3D later.
- Start Task button → `demoStore.startMission()`. Phase 1: also drive a
  local mock phase timer so the page animates before backend exists.

### Verification

```
cd web
npx tsc --noEmit                 # EXIT 0
npx vite build                   # success
npx vite --port 5174 &           # dev server
node web/snap_mission.mjs        # nav /mission, click Start, screenshot mid-task
```

snap_mission.mjs (model on snap_satellite.mjs): nav to /mission, click
Start Task, wait ~6 s, screenshot — verify phase rail advances, data bar
shrinks, clock ticks, cast populated, no console errors.

### Commit

```
git add web/src/pages/MissionPage.tsx web/src/components/mission/ \
        web/src/store/useMissionStore.ts web/src/hooks/useMissionFeed.ts \
        web/src/types/messages.ts web/src/store/demoStore.ts \
        web/src/App.tsx web/src/components/AppShell.tsx web/snap_mission.mjs
git commit -m "mission page: phase rail + data-volume + latency + cast (Phase 1)"
```

---

## §5 — Phase 2: Backend MissionEngine

### Files to modify

```
backend/models.py        # MissionState model + StatePacket.mission
backend/state_engine.py  # MissionEngine sub-state-machine + role assignment
backend/app.py           # ws start_mission / stop_mission handlers
web/src/hooks/useMissionFeed.ts  # switch from local mock to state_update.mission
```

### `MissionState` model

```python
class MissionState(BaseModel):
    active: bool = False
    phase: Literal["idle","acquire","capture","route","compute","downlink","deliver"] = "idle"
    phase_progress: float = 0.0           # 0..1 within current phase
    elapsed_s: float = 0.0                # since capture start
    data_volume_mb: float = 0.0           # current packet size
    targets_found: int = 0
    sensor_idx: int = -1                  # fleet index
    hub_idx: int = -1
    aoi_lat: float = 38.0
    aoi_lon: float = -145.0
    ground_lat: float = 78.2              # chosen GS
    ground_lon: float = 15.4
    ground_id: str = ""
```

Add `mission: MissionState` to `StatePacket`.

### MissionEngine

- A sub-object of StateEngine (or methods on it) advancing the phase
  machine each tick using **wall-clock seconds** (track a phase start
  monotonic timestamp; `phase_progress = clamp(elapsed/duration, 0, 1)`;
  when ≥1, advance to next phase).
- `start_mission()`: set active, phase=acquire, pick sensor (nearest fleet
  sat to AOI using propagate_fleet + lat/lon), hub (index 0 or fleet
  centre), nearest GS. Reset data_volume/targets.
- `stop_mission()`: reset to idle.
- During `compute`: `data_volume_mb` eases 5120 → 2 by phase_progress;
  `targets_found` rolls 0 → 7.
- During `capture`: data_volume_mb = 5120.
- Decide loop vs one-shot: recommend **one-shot** (return to idle, wait for
  next Start) so the operator controls the beat. Document the choice.

### app.py

```python
elif t == "start_mission":
    engine.start_mission()
    await _ack(ws, env.request_id, True)
    await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
elif t == "stop_mission":
    engine.stop_mission()
    await _ack(ws, env.request_id, True)
```

### Verification

```
cd backend && python -m uvicorn app:app --port 8001 &
# trigger via ws or a quick python client:
python -c "import asyncio,json,time,websockets; ..."   # send start_mission
# poll /state, watch mission.phase advance acquire->...->deliver over ~17s
curl -s http://localhost:8001/state | jq .mission
```

Then in the live Web page: Start Task → phase rail + clock now driven by
backend (mock path disabled).

### Commit

```
git add backend/ web/src/hooks/useMissionFeed.ts
git commit -m "backend: MissionEngine phase machine + role assignment (Phase 2)"
```

---

## §6 — Phase 3: Omniverse choreography

Authored on the **overview stage** (geo view). All new prims live under a
gated group so the Overview page doesn't show mission clutter when idle.

### Step 6.1 — USD scaffold (usd/overview.usda)

Add a hidden group + reference it from the scene extension at runtime
(preferred — keep authoring in the extension like the fleet rings):

```
/World/MissionGroup            (visibility = invisible by default)
    /AOI         (a flat ring/disc decal on the Earth surface)
    /Packet      (UsdGeom.Points or small emissive sphere — the data blob)
    /ISLBeam     (BasisCurves sensor→hub)
    /GSLBeam     (BasisCurves hub→ground)
```

Materials: emissive cyan for ISL, warm white for GSL, amber for AOI,
bright cyan blob that the extension recolours/scales.

### Step 6.2 — Scene extension driver

In `ov_app/exts/space.demo.scene/.../extension.py`, add a mission driver
that runs on the overview stage (where the fleet is already rendered):

- Read `state.mission` in `_on_poll` (cache phase / progress / indices).
- In `_on_update` (per-frame, overview stage), when `mission.active`:
  * Show `/World/MissionGroup`; hide when idle.
  * Compute sensor & hub positions from the already-computed fleet
    positions (`compute_fleet_positions` output, indexed by
    `sensor_idx` / `hub_idx`).
  * Convert `ground_lat/lon` and `aoi_lat/lon` to scene-unit points on the
    Earth surface (reuse the lat/lon→ECI math; Earth radius in scene units
    = read from earth_mesh.usda / same SCENE_KM_PER_UNIT scale the fleet
    uses).
  * Phase-specific:
    - `acquire`: pulse AOI ring (scale/emissive by sin(time)).
    - `capture`: place Packet at sensor pos, full size.
    - `route`: Packet pos = lerp(sensor, hub, phase_progress); draw ISLBeam
      sensor→hub.
    - `compute`: Packet at hub; scale Packet down by phase_progress
      (5GB→2MB ⇒ radius shrinks); pulse hub emissive.
    - `downlink`: Packet pos = lerp(hub, ground, phase_progress); draw
      GSLBeam hub→ground; Packet small.
    - `deliver`: flash ground point; hide Packet after.

- Packet = a single UsdGeom.Points prim (1 point, widths drives size) or a
  small UsdGeom.Sphere; reposition each frame. Beams = BasisCurves rebuilt
  per frame between the two endpoints (cheap, 2 points).

### Step 6.3 — Camera (optional)

The overview camera frames the whole Earth + fleet, which is fine. If the
sensor/hub/ground are too spread to read, add a `'mission'` camera preset
(same overview stage, pulled slightly back) and have MissionPage call
`changeCamera('mission')`. Otherwise reuse `'overview'`.

### Verification

```
# backend + vite up; launch Kit:
cd ov_app && ./launch_kit.ps1 -Headless
# switch to overview/mission preset, start a mission via ws, then:
node web/snap_mission.mjs        # captures the /mission page (WebRTC stream)
# Inspect screenshot per phase — AOI lit, packet visibly travelling along
# the ISL beam, shrinking at the hub, descending to the ground station.
# Kit log: add a one-line phase log so routing/compute/downlink are visible.
```

If the packet doesn't move → check sensor_idx/hub_idx vs fleet length and
the lerp. If beams don't render → check BasisCurves point count + widths.
If nothing shows → MissionGroup visibility gate.

### Commit

```
git add usd/overview.usda ov_app/exts/space.demo.scene/
git commit -m "mission: Omniverse choreography — AOI + data packet + ISL/GSL beams (Phase 3)"
```

---

## §7 — Verification table

| Phase | Command | Expected |
|---|---|---|
| Web tsc | `cd web && npx tsc --noEmit` | EXIT 0 |
| Web build | `npx vite build` | "✓ built" |
| Web visual | `node web/snap_mission.mjs` | phase rail advances, clock ticks |
| Backend up | `curl localhost:8001/health` | ok |
| Mission RPC | ws start_mission → `curl .../state \| jq .mission` | phase advances acquire→deliver |
| Kit choreography | launch Kit, start mission, snap | packet travels sensor→hub→ground |

---

## §8 — Termination criteria (all must hold)

- [ ] `/mission` renders at 1440×900, nav link works.
- [ ] Start Task drives the 7-phase machine; phase rail + latency clock +
      data-volume bar all animate; targets_found rolls to 7.
- [ ] Backend `mission` round-trips over WS; phases advance on the
      backend clock.
- [ ] In Omniverse: AOI lights on the Earth, a data packet visibly travels
      sensor → hub (shrinking at the hub) → ground station along ISL/GSL
      beams; MissionGroup hidden when idle.
- [ ] Cast panel shows Sensor / Hub / Ground; selecting one highlights it.
- [ ] tsc clean, vite build clean, Kit log clean.
- [ ] 3 commits: web / backend / usd+kit.

If any item fails: diagnose → fix → re-verify → continue. Do not stop.

---

## §9 — If stuck

- Reuse the fleet ring authoring + `compute_fleet_positions` in
  space.demo.scene for positions; don't re-derive orbits.
- lat/lon → scene point: mirror the ECI math in useFleetPositions.ts /
  orbit_catalog; Earth radius in scene units from earth_mesh.usda.
- Phase machine timing: wall-clock monotonic per-phase start, not
  sim-time, so beats are stable.
- Read `docs/satellite_twin_implementation.md` for the proven
  VariantSet / Kit-poll / snap-verify patterns and the same prose style.
