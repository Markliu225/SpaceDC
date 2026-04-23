# UI Page Spec — Frozen at Phase 0

Four pages, one shared `AppShell`, one shared `DemoStore` (zustand), one shared state WebSocket.

## AppShell

- Header: project name · sim time · status LED · page nav
- Main slot: page content
- Right side: status cards (per page context)
- Bottom: timeline bar + event log (global)

## Page 1 — OverviewPage

URL: `/`

- Left: `<SceneEmbed>` (AppStreamer, camera preset = `overview`)
- Right: status cards — SatelliteState + GroundStationState
- Bottom: TimelineBar + EventLog

Interactions: object click (→ `select_object`), timeline play/pause/scrub (→ `play`/`pause`/`set_time`), reset.

## Page 2 — SatelliteTwinPage

URL: `/satellite`

- Center: `<SceneEmbed>` (camera preset = `satellite`)
- Top bar: view mode tabs — Structure / Power / Thermal / Compute (→ `set_mode`)
- Right: part status table (populated from `selection_changed`)
- Bottom: PowerChart + ThermalChart + BatteryChart (last N seconds)

## Page 3 — TaskExecutionPage

URL: `/task`

- Top-left: task area map (mock SVG)
- Bottom-left: mock remote-sensing image with detection overlay
- Right: task card + inference status (from `task_update`)
- Bottom: Ground path / Space path dual progress timeline

Interactions: Start Task button (→ `start_task`), mode toggle (→ `set_mode` on_orbit / ground_only).

## Page 4 — ControlComparePage

URL: `/control`

- Left: parameter panel (orbit, sunlit, gpu_type, load, bandwidth, inference_mode)
- Right: output cards (solar_input, payload_power, temp_peak, soc_rate, task_latency, downlink_mb, delivery_time)
- Bottom: LatencyCompareChart + DownlinkCompareChart

Interactions: any control change → `set_parameters`; outputs refresh within 1-3s.

## Shared components

- `<AppShell>` — layout
- `<SceneEmbed>` — AppStreamer wrapper
- `<HeaderBar>`
- `<SidePanel>`
- `<StatusCardGrid>`
- `<TimelineBar>`
- `<EventLog>`
- `<PowerChart>` / `<ThermalChart>` / `<BatteryChart>` / `<LatencyCompareChart>` / `<DownlinkCompareChart>` — ECharts wrappers

## DemoStore (zustand) — sole source of UI truth

```ts
interface DemoStore {
  page: 'overview' | 'satellite' | 'task' | 'control';
  simTimeS: number;
  selectedPrim: string | null;
  parameters: Parameters;
  mode: 'on_orbit' | 'ground_only';
  task: TaskState | null;
  lastState: StatePacket | null;
  viewerConnected: boolean;
  // actions...
  send(msg: ClientMessage): void;
}
```

Forbidden: per-page WebSocket, URL-params-as-state, frontend-derived physics.
