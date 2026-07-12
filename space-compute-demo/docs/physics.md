# Physics Model

**English** · [中文](physics.zh-CN.md)

This document specifies the real-time physics that drives the digital twin. Everything here lives in [`backend/state_engine.py`](../backend/state_engine.py) and runs in the engine tick loop; the web UI only displays the broadcast results.

- **Tick rate** — `TICK_HZ = 1.0` (one physics step per wall-clock second).
- **Time acceleration** — battery and thermal integration use `PHYS_TIME_SCALE = 60`, i.e. 1 wall-second advances 60 seconds of those dynamics so changes are legible during a demo. Orbit + workload run at wall-clock.
- **Flow** — each tick recomputes the satellite state from (a) the orbit/sun geometry, (b) the reconfigurable hardware loadout `SatelliteConfig` (GPU, solar/radiator **material**), and (c) the deployable `TwinGeometry` (solar count, radiator size/ratio). The packet is broadcast over WebSocket at 5 Hz.

All symbols below are SI unless noted.

---

## 1. Constants

| Symbol | Value | Meaning |
|--------|-------|---------|
| `S` | 1361 W/m² | Solar constant (`_SOLAR_CONSTANT_W_M2`) |
| `σ` | 5.67×10⁻⁸ W/m²K⁴ | Stefan–Boltzmann constant |
| `T_bg` | 250 K | Effective deep-space + Earth-IR background |
| `IDLE_FRAC` | 0.15 | GPU idle floor as a fraction of TDP |
| `cards` | 8 | GPU cards per satellite (`_GPU_CARDS_PER_SAT`) |
| `P_platform` | 600 W | Bus / platform housekeeping load |
| `C_th` | 160 000 J/K | Lumped thermal mass (`THERMAL_MASS_J_PER_K`) |
| `E_batt` | 1500 Wh | Battery capacity (default; `battery_capacity_wh`) |
| `k_time` | 60 | Battery/thermal time-acceleration (`PHYS_TIME_SCALE`) |

---

## 2. Geometry → areas

Areas are derived from the live `TwinGeometry` so editing the deployables (Feature 3) changes the physics immediately. They mirror the constants in [`tools/gen_twin_satellite.py`](../tools/gen_twin_satellite.py) (backbone-metre → stage-metre scale `1.8`).

**Solar.** One "cluster" is a 2×2 grid filling one big-panel footprint:

```
A_cluster = (0.981 · 1.45 · 1.8) · (0.777 · 1.05 · 1.8) ≈ 3.76 m²
A_solar   = clusters_per_side · 2 · A_cluster
```

**Radiator.** Two dedicated ±Z panels, both faces radiating:

```
long  = radiator_long · 1.8                       [m]
short = (radiator_long / radiator_ratio) · 1.8    [m]
A_rad = 2 panels · 2 faces · (long · short) = 4 · long · short
```

So solar scales only with the side count (panels are added along the sides), and the radiator scales independently with its size/ratio.

---

## 3. Solar power (illumination → generation)

The sun is fixed in the inertial frame at unit direction `ŝ = (0.648, −0.648, 0.398)`. With the satellite position `r`:

```
cos θ = (r · ŝ) / |r|
sunlit = cos θ > −0.05            (small dawn/dusk margin)
```

The wings ride a sun-tracking drive (SADA), like every real orbital power system: while sunlit the cells hold near-normal incidence, so

```
incidence = 0.95  if sunlit else 0          (pointing/temperature losses)
incidence = 1.0   on the dawn-dusk SSO      (never eclipsed, sun-normal)
```

(Earlier builds reused `max(0, cos θ)` — the angle to the *position vector* — as panel incidence. That averaged only ≈0.22 over an orbit, so no plausible array could ever close the power budget and the battery pinned at 0.)

`sun_factor = max(0, cos θ)` is still exported to drive the Kit key-light. Generated power is panel efficiency × area × flux × incidence:

```
P_solar = η · A_solar · S · incidence
```

`η` comes from the chosen cell material: **Si 0.22 · GaAs 0.32 · Perovskite 0.38**.

---

## 4. Compute power (workload → device power)

GPU utilisation follows a deterministic job schedule (`_WORKLOAD_PROFILES` — a fixed queue of **typed** jobs on a repeating cycle), **not** a sinusoid — so a config change is the only moving variable the user sees. Each schedule block names a concrete job from `ai_workloads.py`:

| job | model | precision | nominal MFU | throughput law |
|---|---|---|---|---|
| LLM pretraining | Llama-3.3-70B | BF16 | 0.45 | tok/s = MFU·peak / (6·params) |
| LLM adapter fine-tune | Llama-3.1-8B | BF16 | 0.45 | tok/s = MFU·peak / (6·params) |
| LLM batched inference | Llama-3.3-70B | FP8 | 0.18 | tok/s = MFU·peak / (2·params) |
| LLM interactive serving | Llama-3.3-70B | FP8 | 0.05 | (bandwidth-bound) |
| EO imagery batch / burst | ViT-L/16 detector | FP8 | 0.35 / 0.45 | frames/s = MFU·peak / 0.30 TF |
| housekeeping / checkpoint | — | — | 0 | — |

Peak dense TFLOPS per card (datasheet, no sparsity): H100/H200 989 BF16 · 1979 FP8; B200 2250 · 4500; MI300X 1307 · 2615. MFU scales with the block's duty relative to the job's nominal duty (≤1.2×). The per-card **heat output equals the card's electrical power** — the state exposes the whole thing per tick as `satellite.workload_detail` (job, model, MFU, effective TFLOPS, tok/s or frames/s, W and heat per GPU).

The card count is per design preset (`gpu_count` — e.g. 12×B200 on the twin-truss tower, 4×H100 in the LUMID bus). In eclipse with a low battery the GPUs drop to a power-save floor and the job degrades to housekeeping:

```
util = schedule(t mod cycle)
if (not sunlit) and (SOC < 0.40):  util = min(util, 0.20)
```

Per-card power has an idle floor and scales linearly to TDP — this is the **EPS budget (power cap)** handed to each card:

```
P_cap     = TDP · (IDLE_FRAC + (1 − IDLE_FRAC) · util)
P_payload = P_card · cards          (P_card = realized draw, see 4a)
P_load    = P_payload + P_platform
```

`TDP` and compute come from the GPU model: **H100 0.98 PF / 700 W · H200 1.50 / 700 · B200 2.50 / 1000 · MI300X 1.30 / 750**. For vision/idle jobs the realized draw *is* the cap; LLM jobs resolve it analytically:

### 4a. Analytical LLM engine (`llm_perf.py`) — power cap ∧ thermal limit → DVFS → tokens/s

The MFU table above is only the fallback path for vision/idle jobs. **Every LLM block resolves through an analytical performance/power/thermal model**, calibrated and validated against a V100 power-cap measurement study (`tools/validate_llm_perf.py`, 46 checks: phase-boundary/plateau anchors reproduce exactly, ceiling law blind-predicts three workload plateaus) with the integration proven closed-loop in `tools/validate_llm_engine.py` (24 checks):

- **DVFS power aggregate.** A power budget maps to SM frequency via `P(x) = P_static + χ·x^θ`, `x = f_sm/f_max` (V100 fit: 50 + 155.5·x^2.15). The memory-controller clock is **fixed** — that single fact creates the two phases below.
- **Prefill / training (compute-bound):** `tok/s = T_fmax·x(P)^p`, a single power-law; k = 6 FLOPs/param/token training, k = 2 inference. Compute-bound phases pull their **full budget**.
- **Decode (memory-bound):** each step re-reads all weights + B rows of KV cache → a frequency-immune memory floor `T_mem = (W + B·ctx·kv)/BW_eff`, and `tok/s(P) = B/(T_mem + C_comp·(x^−p − 1))`. Three phases: pseudo-linear → marginal-utility collapse → **bandwidth plateau** `B/T_mem` where extra watts buy nothing. Decode therefore has a **natural draw** below its cap (`P_static + χ·(0.70 + 0.30·duty)`) and the engine bills the payload for the *realized* draw, not the cap.
- **Thermal throttling (the space twist).** The die couples to the satellite structure (the cold plate): `T_die = T_struct + P_gpu·R_th` (H100 ≈ 0.06 K/W, throttle target 85 °C). The driver holds the target by shrinking the budget to `(T_throttle − T_struct)/R_th` — a degraded radiator becomes a *computable* tokens/s loss: structure heats → budget shrinks → clocks + draw fall → heat input falls → **the loop settles in deep throttle** (die pinned at target, alarm `gpu_thermal_throttle`). If the limit drops below the idle floor the die can't be held at all: `gpu_thermal_runaway`, clocks parked.
- **Tensor-parallel group + HBM feasibility.** The fitted cards serve as one ideal TP group: weights, KV and per-step compute shard across `gpu_count` cards, so per-card duty/draw/die-temp match the single-card solve and the aggregate keeps its algebra (`throughput_total = N ×` the full-model single-card solve — the 1/N cancels out of `B/(T_mem + T_comp)` exactly). Communication overhead is *not* modeled, so aggregates are ideal-TP upper bounds. Feasibility *is* enforced: the weight shard must fit per-card HBM (90 % usable), and the decode batch shrinks until the KV shard fits too.
- Per-tick exposure in `workload_detail`: `engine=analytic`, `exec_phase`, `batch`/`context`, `power_cap_w`, realized `power_w_per_gpu`, `freq_frac` (SM clock), `gpu_die_temp_c`, `thermal_throttled`/`thermal_runaway`, `t_mem_ms`/`t_comp_ms`. The dedicated **LLM serving (70B)** workload profile flies a decode-dominant schedule to make all of it observable.

---

## 5. Battery (Wh integration)

Surplus solar charges the battery; a deficit discharges it:

```
P_net = P_solar − P_load                         (battery_charge_w)
ΔSOC  = P_net · dt · k_time / (E_batt · 3600)
SOC   = clamp(SOC + ΔSOC, 0, 1)
```

---

## 6. Thermal (Stefan–Boltzmann radiator)

Heat in is the dissipated electrical power (≈95%, the rest leaves as RF); heat out is grey-body radiation from the radiator area:

```
Q_in  = (P_payload + P_platform) · 0.95
Q_out = ε · σ · A_rad · (T⁴ − T_bg⁴)             (radiator_power_w, ≥ 0)
dT/dt = (Q_in − Q_out) / C_th
T     = clamp(T + dT/dt · dt · k_time, −80 °C, 95 °C)
```

`ε` is the radiator coating: **Aluminium 0.10 · White paint 0.85 · OSR 0.92 · Graphite 0.96** (bare aluminium is a deliberately poor radiator — pick a coating to actually reject heat).

---

## 7. Downlink

A simple ground-pass visibility model:

```
visible = sin(t / 30) > 0.4
downlink = 120 Mbps if visible else 0
```

---

## 8. Design checks (margins)

Steady-state sizing checks shown in the panels, computed from the schedule's **duration-weighted average** workload `ū`:

```
P_demand_avg = [TDP · (IDLE_FRAC + (1−IDLE_FRAC) · ū) · cards] + P_platform
P_supply_avg = 0.95 · 0.5 · (η · A_solar · S)    (tracking losses × sunlit fraction; battery round-trips the night)
P_supply_avg = 1.0 · (η · A_solar · S)           (dawn-dusk SSO — never eclipsed)

Q_peak_demand = (TDP · cards + P_platform) · 0.95            (sustained 100% util)
Q_max_emit    = ε · σ · A_rad · (T_ceil⁴ − T_bg⁴),  T_ceil = 60 °C
```

The supply check uses the **same tracking model** as the per-tick `P_solar`, so a design that passes the check really does hold its battery over an orbit in the running sim (and vice versa).

`margin = supply − demand` (solar) and `Q_max_emit − Q_peak_demand` (thermal) drive the green/red status.

---

## 9. Alarms

| Alarm | Condition |
|-------|-----------|
| `low_battery` | SOC < 0.20 |
| `overtemp` | T > 70 °C |
| `undertemp` | T < −40 °C |
| `eclipse_deficit` | eclipse **and** SOC < 0.35 **and** P_net < 0 |
| `radiator_undersized` | Q_max_emit < 0.9 · Q_peak_demand |
| `solar_undersized` | P_supply_avg < P_demand_avg |
| `gpu_thermal_throttle` | analytic LLM point: thermal limit cuts the realized draw (die held at target) |
| `gpu_thermal_runaway` | analytic LLM point: die can't be held at target even at the idle floor |

---

## 10. What's real vs. simplified

- **Real:** η·A·flux·cos solar generation, idle-floor GPU power curve, Wh battery integration, Stefan–Boltzmann radiation with a lumped thermal mass, the geometry-driven areas, and the analytical LLM operating point (DVFS power aggregate, memory-floor decode law, ceiling law, thermal-limit throttling — anchored to published V100 power-cap measurements) — all respond correctly to config/geometry changes.
- **Simplified for legibility:** fixed inertial sun direction (no seasonal/precession), a scripted workload trace instead of a real scheduler, single-node lumped thermal mass (no gradients; the GPU die is quasi-static on top of it via R_th), a 60× time acceleration on battery/thermal, and a sinusoidal ground-pass model. Modern-GPU (H100/B200/MI300X) DVFS exponents and serving-stack fractions are documented assumptions sanity-checked against public serving benchmarks, not fits. Numbers are representative, not flight-grade.

---

## 11. Source map

| Concern | Location |
|---------|----------|
| All physics | `backend/state_engine.py` → `StateEngine` update + `_solar_area_m2` / `_radiator_area_m2` / `_gpu_workload_util` |
| LLM perf/power/thermal theory | `backend/llm_perf.py` (GPU_PERF / LLM_PERF catalogs, `solve_operating_point`) — validated by `tools/validate_llm_perf.py` + `tools/validate_llm_engine.py` |
| Typed jobs → operating point | `backend/ai_workloads.py` → `job_detail` (analytic path for LLM jobs) |
| Hardware tables | `_GPU_TABLE`, `_SOLAR_MAT_TABLE`, `_RAD_MAT_TABLE` (state_engine.py) |
| State fields | `backend/models.py` → `SatelliteState`, `TwinGeometry` |
| Config / geometry API | `backend/app.py` → `/satellite_config`, `/twin_geometry` |
| Display | `web/src/components/twin/` (panels, `SubsystemHealthRow`, `TimeSeriesStrip`) |
