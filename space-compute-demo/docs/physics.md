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
| `S₀` | 1361 W/m² | Solar constant **at 1 AU** (`_SOLAR_CONSTANT_W_M2`); per-tick flux is `S = S₀/d_AU²` at the true Earth–Sun distance |
| `σ` | 5.67×10⁻⁸ W/m²K⁴ | Stefan–Boltzmann constant |
| `q_IR` | 237 W/m² | Mean Earth outgoing longwave flux (`geodyn.EARTH_IR_W_M2`) |
| `a` | 0.30 | Earth albedo (`geodyn.EARTH_ALBEDO`) |
| `IDLE_FRAC` | 0.15 | GPU idle floor as a fraction of TDP |
| `cards` | 8 | GPU cards per satellite (`_GPU_CARDS_PER_SAT`) |
| `P_platform` | 600 W | Bus / platform housekeeping load |
| `C_th` | 160 000 J/K | Lumped thermal mass (`THERMAL_MASS_J_PER_K`) |
| `E_batt` | derived Wh | Battery capacity = pack mass × chemistry density (default Li-ion L = 8000 Wh); see §5 |
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

The Sun is the **real analytic Sun** (`services/geodyn.py:sun_teme` — Vallado mean-element model, ≤0.05° vs the STK ephemeris), evaluated at the absolute epoch `DEMO_EPOCH + t·60`. Eclipse is the **conical umbra/penumbra model**: `illum ∈ [0,1]` is the visible fraction of the solar disc behind the Earth's limb (`geodyn.sun_visible_fraction` — apparent-disc overlap, same construction as STK's dual-cone shadow; STK-benchmarked event timing ≤5 s). With the satellite position `r` and Sun unit vector `ŝ(t)`:

```
cos θ  = (r · ŝ) / |r|
illum  = visible solar-disc fraction (1 full sun · 0 umbra · smooth through penumbra)
sunlit = illum ≥ 0.5
```

**Incidence is attitude-dependent.** The panel normal `n̂` is set by the commanded pointing mode (`attitude_mode`), and incidence is its projection onto the sun — `max(0, n̂ · ŝ)` — gated to 0 in eclipse:

```
sun       incidence = 1                       (SADA holds the array sun-normal — always full power when lit)
free      incidence = 0.95   (1.0 on dawn-dusk SSO)   (default sun-tracking array; pointing/temperature losses)
nadir     n̂ = r̂            incidence = max(0, r̂·ŝ)   (body-fixed array rides local vertical — swings 0…1 over the orbit)
velocity  n̂ = v̂            incidence = max(0, v̂·ŝ)   (array along-track — edge-on to the sun for part of every orbit)
inertial  n̂ = unit(r×v)    incidence = max(0, n̂·ŝ)   (orbit-normal array — quasi-constant while sunlit)
```

So sun-pointing guarantees continuous daylight power, while a body-fixed attitude (nadir/velocity/inertial) collects only the geometric projection and can fall to 0 even in full sun — the physical answer to "different attitudes collect different solar". The velocity vector comes from the same SGP4 state as the position (`propagate_tracked_rv`).

(Earlier builds reused `max(0, cos θ)` — the angle to the *position vector* — as the *only* incidence model, i.e. nadir for every design. That averaged only ≈0.22 over an orbit, so no plausible array could ever close the power budget and the battery pinned at 0. The sun/free tracking modes fix that; nadir/velocity/inertial remain available as honest body-fixed geometries.)

`sun_factor = max(0, cos θ)` (0 in eclipse) is still exported to drive the Kit key-light. Generated power is panel efficiency × area × true flux × incidence × eclipse fraction × the cell's **temperature derating** (single-node model: panels share the bus temperature, so a hot satellite genuinely generates less — the thermal→power loop that mirrors the thermal→compute one):

```
P_solar = η · A_solar · (S₀/d_AU²) · incidence · illum · η_T
η_T     = clamp(1 + k · (T − 25 °C), 0, 1.25)          (datasheet linear derating)
```

`η` (at the 25 °C reference) and `k` come from the chosen cell material: **Si 0.22 / −0.45 %·K⁻¹ · GaAs 0.32 / −0.20 %·K⁻¹ · Perovskite 0.38 / −0.30 %·K⁻¹**. The steady-state design checks (§8) evaluate at the 25 °C reference (η_T = 1).

**The whole fleet runs the same array.** `FleetSnapshot.solar_total_w` (the Overview energy chart) and the ground-target solar histogram score EVERY satellite with the same `_panel_incidence` above — the constellation flies the active design, so it shares the design's attitude, cells, area, η(T) and deployment fraction (`_array_scale_w`). The histogram bins the same per-sat `illum · incidence` collection factor, so its bars sum back to the aggregate:

```
solar_total_w = Σ_sats  illum_i · incidence_i · (η · A_solar · S₀/d² · η_T · deploy)
```

so a one-satellite fleet's `solar_total_w` is identically that satellite's `solar_input_w`. Velocity for the ram/orbit-normal modes comes from the fleet propagation itself (`propagate_fleet_rv` — SGP4 returns r and v from one call).

(Until Aug 2026 the aggregate and the histogram used `max(0, r̂·ŝ)` — nadir for every design — while the satellite card ran the model above. **A dawn-dusk SSO is the worst case for that formula**: the Sun is perpendicular to the orbit plane, so r̂ lies in it and r̂·ŝ ≈ 0 all orbit long. A 24-sat LTAN-18 design at β ≈ 71° — permanently sunlit, `eclipse = 0/24` — reported 3.9 kW instead of 172 kW, 44× low, next to a satellite card correctly reading 7.2 kW. Regression-guarded by `tools/validate_fleet_solar.py`.)

---

## 4. Compute power (workload → device power)

GPU utilisation follows a deterministic job schedule (`_WORKLOAD_PROFILES` — a fixed queue of **typed** jobs on a repeating cycle), **not** a sinusoid — so a config change is the only moving variable the user sees. Each schedule block names a concrete job from `ai_workloads.py`:

LLM **serving is the primary business** — inference jobs span a catalog of dense models, each a distinct operating point on the analytic decode law (§4a):

| job | model | phase / shape |
|---|---|---|
| LLM batched inference | Llama-3.3-70B FP8 | decode B=48 ctx 2k |
| LLM interactive serving | Llama-3.3-70B FP8 | decode B=8 ctx 1k |
| LLM eval pass | Llama-3.3-70B FP8 | decode B=24 ctx 4k |
| Chat serving · 70B | Llama-3.3-70B FP8 | decode B=24 ctx 4k |
| Edge chat · 8B | Llama-3.1-8B FP8 | decode B=64 ctx 2k |
| Code assist · Coder-32B | Qwen2.5-Coder-32B FP8 | decode B=16 ctx 8k |
| RAG long-context · 72B | Qwen2.5-72B FP8 | decode B=8 ctx 16k |
| Doc summarization · 24B | Mistral-Small-24B FP8 | decode B=32 ctx 8k |
| Frontier serving · 405B | Llama-3.1-405B FP8 | decode B=12 ctx 4k |
| LLM pretraining / fine-tune | Llama-70B / 8B BF16 | train (k=6, compute-bound) |
| EO imagery batch / burst | ViT-L/16 detector FP8 | MFU 0.35 / 0.45 heuristic |
| housekeeping / checkpoint | — | idle floor |

Profiles compose these into serving mixes: `inference` (batched 70B — the default), `chat_serving` (70B quality tier + 8B edge tier), `frontier` (405B near-flat-out), `code_rag` (32B/72B/24B developer mix), plus the secondary `balanced` / `burst` (EO) and `training` stories.

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

The MFU table above is only the fallback path for vision/idle jobs. **Every LLM block resolves through an analytical performance/power/thermal model**, calibrated and validated against a V100 power-cap measurement study (`tools/validate_llm_perf.py`, 52 checks: phase-boundary/plateau anchors reproduce exactly, ceiling law blind-predicts three workload plateaus, serving-catalog sanity) with the integration proven closed-loop in `tools/validate_llm_engine.py` (32 checks):

- **DVFS power aggregate.** A power budget maps to SM frequency via `P(x) = P_static + χ·x^θ`, `x = f_sm/f_max` (V100 fit: 50 + 155.5·x^2.15). The memory-controller clock is **fixed** — that single fact creates the two phases below.
- **Prefill / training (compute-bound):** `tok/s = T_fmax·x(P)^p`, a single power-law; k = 6 FLOPs/param/token training, k = 2 inference. Compute-bound phases pull their **full budget**.
- **Decode (memory-bound):** each step re-reads all weights + B rows of KV cache → a frequency-immune memory floor `T_mem = (W + B·ctx·kv)/BW_eff`, and `tok/s(P) = B/(T_mem + C_comp·(x^−p − 1))`. Three phases: pseudo-linear → marginal-utility collapse → **bandwidth plateau** `B/T_mem` where extra watts buy nothing. Decode therefore has a **natural draw** below its cap (`P_static + χ·(0.70 + 0.30·duty)`) and the engine bills the payload for the *realized* draw, not the cap.
- **Thermal throttling (the space twist).** The die couples to the satellite structure (the cold plate): `T_die = T_struct + P_gpu·R_th` (H100 ≈ 0.06 K/W, throttle target 85 °C). The driver holds the target by shrinking the budget to `(T_throttle − T_struct)/R_th` — a degraded radiator becomes a *computable* tokens/s loss: structure heats → budget shrinks → clocks + draw fall → heat input falls → **the loop settles in deep throttle** (die pinned at target, alarm `gpu_thermal_throttle`). If the limit drops below the idle floor the die can't be held at all: `gpu_thermal_runaway`, clocks parked.
- **Tensor-parallel group + HBM feasibility.** The fitted cards serve as one ideal TP group: weights, KV and per-step compute shard across `gpu_count` cards, so per-card duty/draw/die-temp match the single-card solve and the aggregate keeps its algebra (`throughput_total = N ×` the full-model single-card solve — the 1/N cancels out of `B/(T_mem + T_comp)` exactly). Communication overhead is *not* modeled, so aggregates are ideal-TP upper bounds. Feasibility *is* enforced: the weight shard must fit per-card HBM (90 % usable), and the decode batch shrinks until the KV shard fits too.
- Per-tick exposure in `workload_detail`: `engine=analytic`, `exec_phase`, `batch`/`context`, `power_cap_w`, realized `power_w_per_gpu`, `freq_frac` (SM clock), `gpu_die_temp_c`, `thermal_throttled`/`thermal_runaway`, `t_mem_ms`/`t_comp_ms`. The dedicated **LLM serving (70B)** workload profile flies a decode-dominant schedule to make all of it observable.

---

## 5. Battery (Wh integration)

The pack capacity is **derived from the chosen chemistry and pack size**, not a fixed constant: `E_batt = mass(size) · density(chemistry)`.

```
size      S 10 kg · M 20 kg · L 32 kg · XL 60 kg
chemistry (Wh/kg, round-trip η):  Li-ion NMC 250/0.95 · LiFePO4 160/0.96 · Li-S 400/0.90 · Solid-State 350/0.97
```

So a denser chemistry or a bigger pack both raise Wh (e.g. Li-ion L = 32·250 = 8.0 kWh; Li-S XL = 60·400 = 24 kWh). Surplus solar charges the battery; a deficit discharges it. The round-trip loss is booked **once, on the charging leg** — only `η` of a surplus watt reaches stored energy, and discharge draws stored energy 1:1 — so over a charge→discharge cycle `energy_out/energy_in = η` (a true round-trip efficiency, not η²):

```
P_net  = P_solar − P_load                        (battery_charge_w, raw electrical net)
P_eff  = P_net · η   if P_net ≥ 0  else  P_net    (charge is taxed; discharge is 1:1)
ΔSOC   = P_eff · dt · k_time / (E_batt · 3600)
SOC    = clamp(SOC + ΔSOC, 0, 1)
```

---

## 6. Thermal (Stefan–Boltzmann radiator + orbital environment)

Heat in is the dissipated electrical power (≈95%, the rest leaves as RF) **plus the orbital thermal environment** — direct solar absorption, Earth albedo and Earth IR — so the temperature swings with the eclipse cycle (STK SEET-benchmarked: sunlit/eclipse segment means within 0.4 K on the reference sphere). With `F = (1−√(1−(R⊕/r)²))/2` the Earth-disc view factor and `S = S₀/d_AU²`:

```
Q_env = α·S·illum·A_rad/4                      (direct solar — convex-body mean projected area)
      + α·a·S·A_rad·F·max(0, cos θ)            (Earth albedo)
      + ε·q_IR·A_rad·F                         (Earth IR — present in eclipse too)
Q_in  = (P_payload + P_platform) · 0.95 + Q_env
Q_out = ε · σ · A_rad · T⁴                     (radiator_power_w, ≥ 0)
dT/dt = (Q_in − Q_out) / C_th
T     = clamp(T + dT/dt · dt · k_time, −80 °C, 95 °C)
```

The radiator coating sets **both** optical properties (`α/ε` is the thermal-control design ratio): **Aluminium ε 0.10 / α 0.25 · White paint 0.85 / 0.25 · OSR 0.92 / 0.08 · Graphite 0.96 / 0.90** (bare aluminium's α/ε = 2.5 makes it a genuinely poor radiator — pick a coating to actually reject heat).

---

## 7. Downlink

Real elevation-mask geometry against the configured ground target (default Singapore 1.3521° N / 103.8198° E, X-band 10° mask), using the same WGS-84 ECEF elevation model as the coverage analytics (`constellations.elevation_deg` — STK-benchmarked access windows to ≤1 s):

```
visible  = elevation(sat sub-point → ground target) ≥ mask
downlink = band rate if visible else 0
```

---

## 8. Design checks (margins)

Steady-state sizing checks shown in the panels, computed from the schedule's **duration-weighted average** workload `ū`:

```
P_demand_avg = [TDP · (IDLE_FRAC + (1−IDLE_FRAC) · ū) · cards] + P_platform
P_supply_avg = 0.95 · 0.5 · (η · A_solar · S)    (tracking losses × sunlit fraction; battery round-trips the night)
P_supply_avg = 1.0 · (η · A_solar · S)           (dawn-dusk SSO — never eclipsed)

Q_peak_demand = (TDP · cards + P_platform) · 0.95            (sustained 100% util)
Q_max_emit    = ε · σ · A_rad · T_ceil⁴ − Q_env_worst,  T_ceil = 60 °C
                (Q_env_worst = §6 environment at full sun, subsolar albedo)
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

- **Real (STK 11-benchmarked, see `tools/stk_benchmark/`):** SGP4/TEME propagation (machine-precision vs STK), WGS-84 geodetic sub-points via true GMST (≤10⁻⁷ °), the analytic Sun (≤0.05°), conical umbra/penumbra eclipse (event timing ≤5 s, sunlit fraction ≤0.1 pp), WGS-84 ground-station elevation and access windows (≤1 s), η·A·S(d)·cos·illum solar generation (24 h energy ≤0.4 % vs STK-derived truth), idle-floor GPU power curve, Wh battery integration, Stefan–Boltzmann radiation with solar/albedo/Earth-IR environment heating (SEET segment means ≤0.4 K), the geometry-driven areas, and the analytical LLM operating point (DVFS power aggregate, memory-floor decode law, ceiling law, thermal-limit throttling — anchored to published V100 power-cap measurements).
- **Simplified for legibility:** a scripted workload trace instead of a real scheduler, single-node lumped thermal mass (no gradients; the GPU die is quasi-static on top of it via R_th), a 60× time acceleration on battery/thermal, spherical-Earth shadow (no oblateness — worth a few seconds at eclipse edges), no atmospheric refraction on elevation, and the dawn-dusk SSO preset still forces permanent sunlight for its demo story. Modern-GPU (H100/B200/MI300X) DVFS exponents and serving-stack fractions are documented assumptions sanity-checked against public serving benchmarks, not fits. Numbers are representative, not flight-grade.

---

## 11. Source map

| Concern | Location |
|---------|----------|
| All physics | `backend/state_engine.py` → `StateEngine` update + `_solar_area_m2` / `_radiator_area_m2` / `_gpu_workload_util` |
| Sun / eclipse / WGS-84 / GMST / view factor | `backend/services/geodyn.py` (STK benchmark: `tools/stk_benchmark/`) |
| Classical elements OE↔RV (osculating broadcast) | `backend/services/elements.py` (NTU CV-001/CV-002 conventions) — validated by `tools/validate_elements.py` |
| LLM perf/power/thermal theory | `backend/llm_perf.py` (GPU_PERF / LLM_PERF catalogs, `solve_operating_point`) — validated by `tools/validate_llm_perf.py` + `tools/validate_llm_engine.py` |
| Typed jobs → operating point | `backend/ai_workloads.py` → `job_detail` (analytic path for LLM jobs) |
| Hardware tables | `_GPU_TABLE`, `_SOLAR_MAT_TABLE`, `_RAD_MAT_TABLE` (state_engine.py) |
| State fields | `backend/models.py` → `SatelliteState`, `TwinGeometry` |
| Config / geometry API | `backend/app.py` → `/satellite_config`, `/twin_geometry` |
| Display | `web/src/components/twin/` (panels, `SubsystemHealthRow`, `TimeSeriesStrip`) |
