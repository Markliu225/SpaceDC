# Satellite Twin Page — Full Implementation Prompt

## Mission

Build the **Satellite Twin Page** (`/satellite`) in the space-compute-demo project. The page must let a viewer:

1. Pick one satellite (defaulting to Overview's `selectedSatIdx`).
2. **Reconfigure** its GPU / Solar Panel / Radiator via dropdowns in a right-rail Configurator.
3. **Instantly** see both the recomputed telemetry numbers AND the Omniverse 3D scene update to reflect the new hardware (geometry + materials).

The page must look "演示片级" — fancy enough to ship to a customer.

## Locked design decisions — do not relitigate

- **Config tiers**: GPU 4 / Solar 4 sizes × 3 materials / Radiator 3 sizes × 4 materials.
- **Apply mode**: instant — dropdown change fires `set_config` immediately.
- **Visual priority order**: MDL real materials → Flow particles / heat shimmer → (P3 backlog) emissive driver, dolly camera, selection outline.
- **VariantSet topology**: 5 VariantSets, **18 variants total** authored, orthogonal (NOT 576 combinations).

## Workflow rules (CRITICAL — read twice)

1. **STRICT ordering**: Frontend first → git commit → Backend bridge → git commit → Omniverse → git commit. No exceptions. Don't touch Omniverse before frontend is green and committed.
2. **Self-verify every meaningful change.** Run the appropriate verification (table at the bottom). If it fails, fix it before continuing. Never "finish" with a known broken state.
3. **Verification loop is non-negotiable**: you keep iterating run → look → fix until the current phase is fully working. Do not stop mid-way.
4. **Asset policy**: For USD parts, reuse first. Search order:
   - `usd/` (already in stage)
   - `usd/assets/` (LUMID, Satellite_v022)
   - `assets_usd/DigitalTwin/Assets/` (NVIDIA SimReady DGX racks, etc.)
   - `assets_raw/`
     If nothing fits, **write a procedural generator** under `tools/gen_<name>.py` that prints `#usda 1.0` text (same pattern as `tools/gen_orbit_line.py`, `tools/gen_earth_mesh.py`). You may also draw with primitive geometry (Cube / Cylinder / Sphere + Boolean) — fancy materials carry the look.
5. **Numbers**: all values come from the data tables in §3. Do not invent.
6. **TodoWrite**: open a tracked task list at start, mark each item completed as you finish.
7. **Commits**: each phase ends with `git add <relevant files only> && git commit -m "<phase tag>: <summary>"`. Do not stage unrelated noise (`.claude/`, `assets_raw/8k_*`, the two Chinese docs — leave them untracked).

---

## §1 — Existing context (read these first)

```
web/src/pages/OverviewPage.tsx                       — layout pattern (grid + min-h-0)
web/src/components/overview/SatelliteDetail.tsx      — param chip + bar style
web/src/components/overview/SatelliteSelector.tsx    — dropdown pattern
web/src/components/overview/CostPanel.tsx            — tile pattern with lucide icons
web/src/store/useTelemetryStore.ts                   — selectedSatIdx, presets, fleet
web/src/hooks/useFleetStatuses.ts                    — synthesized per-sat telemetry
web/src/design/tokens.ts                             — colors, typography
backend/models.py                                    — Pydantic state contract
backend/state_engine.py                              — 1Hz tick loop
backend/app.py                                       — FastAPI handlers
ov_app/exts/space.demo.scene/.../extension.py        — Kit poll + scene update
usd/satellite.usda                                   — current sat stage (verify what's inside)
usd/components.usda                                  — sat body via apply_assembly.py
```

You MUST read these before writing code so your additions follow the existing patterns.

---

## §2 — Page layout (1440×900)

```
┌────────────────────────────────────────────────────────────────────────┐
│ Header: sat picker · View Mode tabs · LIVE/PAUSED  56px                │
├──────────────────────────────────────────────┬─────────────────────────┤
│                                              │ Configurator (col-4)    │
│                                              │  Section: GPU           │
│                                              │   Dropdown + 3 stats    │
│                                              │  Section: Solar         │
│  EarthViewport / SceneEmbed (col-8)          │   2 dropdowns + stats   │
│                                              │  Section: Radiator      │
│  Locked to satellite camera preset           │   2 dropdowns + stats   │
│                                              │  ─────────────────      │
│                                              │  Live deltas:           │
│                                              │   ΔSolarIn · ΔMass      │
│                                              │   ΔCompute · ΔPayback   │
├──────────────────────────────────────────────┴─────────────────────────┤
│ TimeSeriesStrip · 5 sparklines, last 120s          col-12 · 160px      │
├────────────────────────────────────────────────────────────────────────┤
│ SubsystemHealthRow · 4 cards (Power · Thermal · Compute · Comms)  120px│
└────────────────────────────────────────────────────────────────────────┘
```

Grid rows: `56px minmax(0,1fr) 160px 120px`. Use `gridTemplateColumns: 'repeat(12, minmax(0,1fr))'`.

---

## §3 — Data tables (authoritative)

### GPU

| id | label | pflops_per_card | tdp_w | cost_k | color |
|---|---|---|---|---|---|
| H100 | H100 SXM | 0.98 | 700 | 30 | #4A5568 |
| H200 | H200 SXM | 1.50 | 700 | 40 | #3B82F6 |
| B200 | B200 | 2.50 | 1000 | 45 | #0F172A |
| MI300X | MI300X | 1.30 | 750 | 28 | #DC2626 |

Card count per satellite: **8** (one DGX rack).

### Solar — material

| id | label | efficiency | density_kg_m2 | tint | label_short |
|---|---|---|---|---|---|
| Si | Silicon | 0.22 | 2.5 | #1E3A8A | Si |
| GaAs | Gallium Arsenide | 0.32 | 3.0 | #4C1D95 | GaAs |
| Perovskite | Perovskite Tandem | 0.38 | 1.8 | iridescent | PvT |

### Solar — size

| id | label | area_m2_per_panel | panel_count |
|---|---|---|---|
| S | Small | 4 | 2 |
| M | Medium | 8 | 2 |
| L | Large | 12 | 2 |
| XL | Extra Large | 16 | 4 |

### Radiator — material

| id | label | emissivity | density_kg_m2 | tint |
|---|---|---|---|---|
| Aluminum | Bare Aluminum | 0.10 | 4.0 | #C0C0C0 |
| WhitePaint | White Paint | 0.85 | 4.4 | #F0F0F0 |
| OSR | Optical Solar Reflector | 0.92 | 4.6 | #D4D4D8 |
| Graphite | Graphite Composite | 0.96 | 3.6 | #18181B |

### Radiator — size

| id | label | area_m2_per_panel |
|---|---|---|
| Compact | Compact | 1 |
| Standard | Standard | 2 |
| Wide | Wide | 4 |

(Two radiator panels per sat — East + West.)

### Physics recompute (demo formulas)

```
SOLAR_CONSTANT_W_M2 = 1361

solar_input_w =
    material.efficiency
  × size.area_m2_per_panel
  × size.panel_count
  × SOLAR_CONSTANT_W_M2
  × max(0, cos_alpha)            # 1 if sunlit, 0 if eclipse
  × (sunlit ? 1 : 0)

payload_power_w = gpu.tdp_w × 8 × gpu_utilization

# Radiator dissipation; STEFAN_BOLTZMANN × ε × A × T⁴ inverted:
# For demo we use a linear surrogate:
peak_temp_c = 28 + (50 × gpu_utilization) / (radiator.emissivity × 2 × radiator.area_m2_per_panel)

compute_pflops_per_sat = gpu.pflops_per_card × 8

launch_mass_kg =
    300                                # bus mass baseline
  + 2 × solar.panel_count × solar.area_m2_per_panel × solar.density_kg_m2
  + 2 × radiator.area_m2_per_panel × radiator.density_kg_m2

capex_per_sat_usd_m =
    3.0                                # bus baseline
  + gpu.cost_k × 8 / 1000              # 8 cards
  + 0.05 × solar.panel_count × solar.area_m2_per_panel   # solar in M$
  + 0.02 × 2 × radiator.area_m2_per_panel                # radiator in M$
```

Baseline reference config for "Δ vs baseline" deltas: `{gpu: H100, solar: {Si, M}, radiator: {Aluminum, Standard}}`.

---

## §4 — Phase 1: Frontend

### Files to create

```
web/src/pages/SatelliteTwinPage.tsx
web/src/data/satConfigOptions.ts
web/src/components/twin/Configurator.tsx
web/src/components/twin/ConfigDropdown.tsx
web/src/components/twin/ConfigDelta.tsx
web/src/components/twin/SubsystemHealthRow.tsx
web/src/components/twin/TimeSeriesStrip.tsx
web/src/components/twin/ViewModeTabs.tsx
web/src/hooks/useSatConfig.ts       # local + remote satellite config state
```

### Files to modify

```
web/src/types/messages.ts            # add SatelliteConfig interface
web/src/store/demoStore.ts           # add setSatelliteConfig action; sendSetConfig command
web/src/hooks/useBackendBridge.ts    # bridge state_update → config; POST /satellite_config
web/src/App.tsx (or wherever routes live) — register /satellite route
```

### Configurator behavior

- 3 sections (GPU / Solar / Radiator), each with a section header + lucide icon.
- Dropdowns reuse the `SatelliteSelector` listbox/popover pattern (anchored button + absolutely positioned listbox, click-outside close).
- Each dropdown shows the selected option's label + 2-3 inline stats (efficiency / density / cost).
- Below all dropdowns: a "Live Deltas" 4-row block — for each of (SolarIn, Mass, Compute, Payback) show baseline → current with up/down arrow chip colored ok/warn.
- Change fires immediately:
  1. `useDemoStore.sendSetConfig({gpu, solar_material, solar_size, radiator_material, radiator_size})`
  2. Local optimistic update to `useTelemetryStore.satConfig` (so deltas refresh without waiting for backend)

### TimeSeriesStrip behavior

- 5 sparklines side by side: Solar W, Payload W, Battery SOC, Temp °C, GPU Util %.
- Each holds a 120-element circular buffer (1Hz × 120s window).
- When `satConfig` changes mid-stream, draw a 1px dashed vertical "scar" at that x position with a tooltip showing what changed.

### SubsystemHealthRow

- 4 cards: Power / Thermal / Compute / Comms.
- Each shows a status badge (nominal/warn/fault), 2 key metrics, and a 1-line root cause hint.
- Status derives from current config + telemetry:
  - Power: `solar_input_w >= payload_power_w + 600` ⇒ nominal; otherwise warn.
  - Thermal: `peak_temp_c < 70` ⇒ nominal, `< 85` ⇒ warn, else fault.
  - Compute: always nominal if sat is online (placeholder).
  - Comms: based on `downlink_mbps > 0`.

### ViewModeTabs

- 4 tabs: Structure / Power / Thermal / Compute.
- Phase 1: only Structure is enabled. Others are visually rendered but `disabled` with a small "Soon" badge.
- Selected tab is the page's local UI state (lift later if needed).

### Visual style

- Match Overview's tokens — Card primitive, Dot, Num, Sparkline.
- Tile padding for Configurator sections: dense Card.
- Color the Configurator section headers with lucide icons:
  - GPU → Cpu
  - Solar → Sun
  - Radiator → Snowflake (cold dissipation)

### Verification

```
cd web
npx tsc --noEmit                          # must be EXIT 0
npx vite build                            # must succeed
npx vite dev                              # dev server background
node web/snap_satellite.mjs               # write this — playwright nav to localhost:5174/satellite, screenshot
```

Write `web/snap_satellite.mjs` modeled on `web/snap_overview.mjs`. Open the screenshot, verify:

- Configurator visible with 3 sections
- Time series strip rendering 5 sparklines
- Subsystem row showing 4 cards
- No console errors in the browser

If anything wrong, FIX IT. Re-snap. Repeat.

### Commit checkpoint

```
git add web/src/...                       # ONLY web files
git commit -m "twin page: configurator + deltas + time-series + subsystem row"
```

---

## §5 — Phase 2: Backend bridge

### Files to modify

```
backend/models.py                # add SatelliteConfig pydantic model
backend/state_engine.py          # _config field, set_config() mutator, apply to physics
backend/app.py                   # /satellite_config GET/POST, ws set_config handler
```

### `SatelliteConfig` Pydantic model

```python
class SatelliteConfig(BaseModel):
    gpu: GpuType = "H100"
    solar_material: Literal["Si", "GaAs", "Perovskite"] = "Si"
    solar_size: Literal["S", "M", "L", "XL"] = "M"
    radiator_material: Literal["Aluminum", "WhitePaint", "OSR", "Graphite"] = "Aluminum"
    radiator_size: Literal["Compact", "Standard", "Wide"] = "Standard"
```

### `StateEngine` changes

- Add `self._config = SatelliteConfig()` in `__init__`.
- Add `set_config(self, cfg: dict)`: merge into existing `self._config` via `model_copy(update=cfg)`.
- In `_update_placeholder_physics`: use the formulas in §3 to recompute `solar_input_w`, `payload_power_w`, `temperature_c` based on `_config`.
- Add `self._config` to `StatePacket` (extend `StatePacket` model).

### `app.py` additions

- `GET /satellite_config` → `engine.snapshot().satellite_config.model_dump()` (Kit polls this).
- `POST /satellite_config` → body is partial `SatelliteConfig`, calls `engine.set_config(body)`, returns ok.
- WS `set_config` handler:
  ```python
  elif t == "set_config":
      engine.set_config(p)
      await _ack(ws, env.request_id, True)
      await manager.broadcast(_envelope("state_update", engine.snapshot().model_dump()))
  ```

### Verification

```
cd backend
python -m uvicorn app:app --port 8001 &    # background
sleep 2
curl http://localhost:8001/satellite_config  # expect default config
curl -X POST http://localhost:8001/satellite_config -H "Content-Type: application/json" \
     -d '{"gpu": "B200", "solar_size": "XL"}'
curl http://localhost:8001/state | jq .satellite_config  # expect updated
curl http://localhost:8001/state | jq .satellite.solar_input_w  # expect higher number
```

Then in Web (still running):

- Open /satellite, change GPU dropdown to B200.
- Check that `solar_input_w` / `payload_power_w` / `temperature_c` numerically update in the time-series strip within 1Hz tick.

Fix anything broken. Re-verify.

### Commit checkpoint

```
git add backend/ web/src/hooks/useBackendBridge.ts web/src/store/demoStore.ts web/src/types/messages.ts
git commit -m "backend: SatelliteConfig + /satellite_config + set_config ws handler"
```

---

## §6 — Phase 3: Omniverse

### Step 6.1 — audit existing satellite.usda

Read `usd/satellite.usda` first. Document what's there:

- Which prims exist?
- Does the satellite already have solar panels / radiators / DGX rack as named prims?
- What materials are bound?

Based on the audit, decide:

- (A) Existing prims have semantic names → just add VariantSet authoring on top.
- (B) Prims are anonymous → first rename / wrap them under a clean semantic hierarchy.

### Step 6.2 — VariantSet authoring

Target prim structure:

```
/World/Satellite
    variantSets = ["gpu"]
    /DGX_Rack
        /GPU_01 .. /GPU_08         # 8 GPU cards — material override per gpu variant
    /SolarPanelWing_N
        variantSets = ["solar_size", "solar_material"]
        # size variants swap geometry references (S/M/L/XL)
        # material variants swap MaterialBindingAPI
    /SolarPanelWing_S
        variantSets = ["solar_size", "solar_material"]
    /Radiator_East
        variantSets = ["radiator_size", "radiator_material"]
    /Radiator_West
        variantSets = ["radiator_size", "radiator_material"]
```

Authoring approach (recommended):

- Write `tools/gen_satellite_variants.py` — a Python script that prints USDA text for the variant authoring layers. Same pattern as existing tools.
- Output: `usd/satellite_variants.usda` — a sublayer that adds the VariantSets without rewriting the existing satellite stage.
- Reference it from `usd/satellite.usda` as a sublayer.

### Step 6.3 — Geometry assets

For each piece, search order then create if missing:

- **GPU cards (4 variants)**: Search `assets_usd/DigitalTwin/Assets/Datacenter/Server_Nodes/`. The DGX_A100 asset likely has GPU cards already — reuse, with material recolor for the 4 variants. If unavailable, generate a parametric card (cube + heatsink fins) via `tools/gen_gpu_card.py`.
- **Solar panels (4 sizes)**: 99% chance no asset exists. Generate via `tools/gen_solar_panel.py` — a flat Mesh (Cube scaled to (W, H, 0.05)) with grid pattern UV. Output 4 .usdc files: `usd/assets/solar_panel_{S,M,L,XL}.usdc`.
- **Radiators (3 sizes)**: Same — generate via `tools/gen_radiator.py`. Flat panels with edge stiffeners (extruded boundary).

### Step 6.4 — MDL materials

For each material slot, prefer Omniverse stock materials:

- Solar materials:
  - Si → OmniPBR with deep blue albedo + ridge normal map (search `omni_core_materials_*`)
  - GaAs → OmniPBR with purple-black metallic
  - Perovskite → OmniSurface with thin_film_thickness for iridescence
- Radiator materials:
  - Aluminum → OmniPBR metallic 1.0, roughness 0.15
  - WhitePaint → OmniPBR diffuse 0.95 white, metallic 0
  - OSR → OmniPBR with silver albedo + glass overlay (or stock "Silver_Coating")
  - Graphite → OmniPBR carbon-black with anisotropy
- GPU cards: 4 variants of OmniPBR with the color tints from §3.

Materials live under `/Looks` in the variants layer. Each VariantSet's material variant rebinds `material:binding`.

### Step 6.5 — Kit extension wiring

In `ov_app/exts/space.demo.scene/space/demo/scene/extension.py`:

```python
# Track last-applied config so we only call SetVariantSelection on change.
self._last_config: dict | None = None

# In _on_poll, after pulling /state, also pull /satellite_config:
async def _poll_config(self):
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{self._backend_http}/satellite_config") as r:
            return await r.json()

# After fetching cfg:
def _apply_config(self, cfg: dict):
    if cfg == self._last_config:
        return
    stage = omni.usd.get_context().get_stage()
    sat   = stage.GetPrimAtPath("/World/Satellite")
    if not sat.IsValid():
        return
    # GPU variant on /World/Satellite
    sat.GetVariantSet("gpu").SetVariantSelection(cfg["gpu"])
    for wing in ("SolarPanelWing_N", "SolarPanelWing_S"):
        p = stage.GetPrimAtPath(f"/World/Satellite/{wing}")
        if p.IsValid():
            p.GetVariantSet("solar_size").SetVariantSelection(cfg["solar_size"])
            p.GetVariantSet("solar_material").SetVariantSelection(cfg["solar_material"])
    for rad in ("Radiator_East", "Radiator_West"):
        p = stage.GetPrimAtPath(f"/World/Satellite/{rad}")
        if p.IsValid():
            p.GetVariantSet("radiator_size").SetVariantSelection(cfg["radiator_size"])
            p.GetVariantSet("radiator_material").SetVariantSelection(cfg["radiator_material"])
    self._last_config = cfg
```

Hook `_apply_config` into the existing _on_poll cadence (it already runs 5Hz).

### Step 6.6 — Flow particles (heat shimmer)

Add a `Flow Emitter` over each radiator's center. Use the Kit Flow SDK or `omni.flowusd`:

- Velocity field: vertical ±0.5 m/s with turbulence.
- Density: 0.3 at base, decaying.
- Color: alpha-only (transparent heat distortion).
- Visibility: tied to a USD attribute `outputs:thermalActive` we toggle from the extension when the temp passes 50°C.

This is the "fancy" tier. If Flow setup is hard, fall back to an animated noise-displacement decal shader over the radiator surface — looks similar.

### Verification

```
# 1. USD smoke test — load via headless pxr.Usd if available, or via Kit's USDPython:
ov_app/launch_kit.ps1 -Verify usd/satellite.usda
# Wait for ws live, watch console — no MaterialError, no VariantSet not found.

# 2. Programmatic variant change test (from outside Kit):
curl -X POST http://localhost:8001/satellite_config -d '{"gpu": "B200"}'
# Within 1 sec the Kit console should log "applied config gpu=B200"

# 3. Capture screenshot via the existing snap_*.mjs:
node web/snap_satellite.mjs --view=satellite
# Inspect screenshot — sat must look visually different for B200 vs H100 (color change)
```

If material doesn't visibly change → debug material binding paths. If geometry doesn't change → debug variant payload references. If nothing renders → check stage loaded correctly.

### Commit checkpoint

```
git add usd/ tools/gen_*.py ov_app/exts/space.demo.scene/
git commit -m "twin: VariantSet wiring + Kit _apply_config + Flow heat shimmer"
```

---

## §7 — Verification table (quick reference)

| Phase | Command | Expected |
|---|---|---|
| Web tsc | `cd web && npx tsc --noEmit` | EXIT 0 |
| Web build | `npx vite build` | "✓ built in …" |
| Web visual | `node web/snap_satellite.mjs` | screenshot looks right |
| Backend up | `curl http://localhost:8001/health` | `{"ok": true, …}` |
| Backend config | `curl http://localhost:8001/satellite_config` | default cfg |
| End-to-end | POST cfg → curl /state | reflects within 1Hz |
| USD load | Kit launches without `[error]` lines about missing prims | clean log |
| Kit variant | POST cfg → Kit log shows "applied config" | log line present |
| Visual | snap shows different sat for B200 vs H100 | distinct colors |

---

## §8 — Termination criteria (all must hold)

- [ ] `/satellite` route renders without errors at 1440×900.
- [ ] All 3 Configurator dropdowns work and live deltas update.
- [ ] `set_config` envelope round-trips: change dropdown → state_update broadcasts new numbers → time series records the change with a scar.
- [ ] Kit visually swaps GPU / solar / radiator within 1 second of config change.
- [ ] Flow heat shimmer (or fallback) visible on radiators when GPU util > 50%.
- [ ] tsc clean, vite build clean, Kit log clean (no errors).
- [ ] 3 commits on `main` (or feature branch if requested): web-only / backend-only / usd+kit.

If any item fails, you DO NOT stop. Loop: diagnose → fix → re-verify → continue.

---

## §9 — If stuck

- Search for similar pattern in the repo before inventing.
- Read the design docs: `docs/设计文档.md`, `docs/功能文档.md`, `docs/api_spec.md`, `docs/ui_page_spec.md`, `docs/kit_setup.md`, `docs/asset_pipeline.md`.
- If a Kit feature won't load, check `ov_app/launch_kit.ps1` for env vars, then `ov_app/exts/*/config/extension.toml` for deps.
- For USD authoring questions, look at existing `tools/gen_*.py` for the print-USDA pattern.
