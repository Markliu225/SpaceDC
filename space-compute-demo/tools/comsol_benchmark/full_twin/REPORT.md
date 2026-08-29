# OrbitWiz lumped thermal model vs COMSOL finite-element reference — written summary

*Status: final (2026-08-30). Both cases solved for 5 orbits (3 + a verified 2-orbit continuation); §7.8 gives the numbers to quote; a Chinese executive summary follows. Figure index: `out/figures_final/FIGURES.md`.*

## 摘要（中文）

**做了什么。** 把 OrbitWiz（`space-compute-demo`）的单节点集总热模型与 COMSOL 6.3 有限元整星模型（固体传热 + 面对面辐射 + 轨道热载荷，半立方体 128，双波段光学，2.7 K 深空，OrbitWiz 自己的 SGP4 轨道与太阳矢量，每个 GPU 封装独立热源，TIM 薄阻层，热管网络为外部设计）做开环对比：冻结热点稳态 + 5 圈轨道瞬态（前 3 圈 + 真正续算 2 圈，严格 BDF-1，Δt = 120 s），两个算例：A = 12×V100（OrbitWiz 中永不降频），B = 12×A100（OrbitWiz 中降频）。全部参数按硬规则溯源到 file:line（`PHASE1_PARAMETERS.md`）；外部来源的材料/热管/TIM 单独标注（`PHASE1_ADDENDUM_materials.md`）。

**主要结果（第 4–5 圈，周期均值；括号内为最大绝对偏差）。**

| 量 | Case A（V100） | Case B（A100） |
|---|---|---|
| 散热板均温：COMSOL vs OrbitWiz 单节点 | 40.2 vs 46.8 °C → **−6.6**（10.6） | 53.9 vs 63.2 °C → **−9.3**（12.9） |
| GPU 基板 vs 单节点 | 59.2 vs 46.8 → **+12.5**（14.0） | 78.3 vs 63.2 → **+15.1**（16.4） |
| 机身 vs 单节点 | 66.2 vs 46.8 → **+19.4**（22.5） | 84.7 vs 63.2 → **+21.5**（25.1） |
| 散热板面内梯度（max − 面积加权均值）均值 / 最大 | 4.0 / 4.8 °C | 5.2 / 5.8 °C |
| 降频线 | COMSOL die 等效在每个高负载块末尾越过 83 °C（占窗口 36 %，最高 86.7 °C）；OrbitWiz 永不（最高 72.7） | OrbitWiz 有 36 % 时间脱离降频；COMSOL die 等效 90.5–103.7 °C，从不脱离 |

**结论。** 单节点落在 COMSOL 的散热板与电子设备之间：比散热板表面高 7–9 °C，比 GPU 基板低 12–15 °C，比机身低 19–22 °C。根源是结构性的——单节点没有机身→散热板的导热通路，无法表示热管/TIM/机身在 2.4–3.1 kW 下产生的 25–30 °C 温降；调 C 或 ε 都救不了，加一个"电子设备"节点并与散热板节点之间加一个热导才行。降频预测因此在"状态"上不同：V100 案例集总模型说永不降频，有限元说每个高负载块末尾降频约 35 分钟；A100 案例集总模型说周期性脱离降频，有限元说从不脱离。动态上，160 kJ/K 的单节点几乎感受不到地影，有限元散热板每次地影摆动 6–12 °C。

**检查结果。** 能量平衡：冻结态吸收 39.7 / 40.1 kW vs 发射 41.1 / 41.7 kW，残差 3.6 / 3.9 %（略超 3 % 目标；残差等于 COMSOL 本版本无法求值的互辐射红外项 Gm2，如实标注而非宣称闭合）。辐射面积 6.273 m² = 两块板双面，精确。温度量级 305–336 K，在 250–350 K 内。**周期性判据（逐圈 ≤ 0.5 °C）对本工况不可能成立**：`inference` 工况周期 21 600 s = 3.875 圈，OrbitWiz 参考曲线自己逐圈就差 5–8 °C；改用"同工况相位、隔一个工况周期"的比较界定残余初始瞬态，并给出逐圈均值与逐圈变化表（§7.7）。第 3 圈起 COMSOL 的逐圈变化（1.5–5.8 °C）已低于或相当于参考自身（4.7–7.6 °C）。

**必须如实交代的两件事。** (1) 轨道瞬态实际从均匀初温（50.4 / 66.6 °C = OrbitWiz t₀ 时的 T_struct）起算，而不是冻结稳态——研究步上的"以 A 解为初值"设置没有传到求解器（`useinitsol` 未开）；第 1 圈按任务丢弃，吸收了大部分升温，但第 2–3 圈仍低估机身/基板偏差约 4–6 °C，所以引用第 4–5 圈。续算第一次也重启了（两步 OTL 研究有两个解存储，取到了载荷存储），已用 `withsol` 预检 + 两步连续性自检（首点差 0.00 °C）修正后重跑。(2) 整条热传输路径（热管数量/间距/k_eff、TIM）是外部设计，机身→散热板温降的大小取决于它；但任何现实的被动设计都不可能把电子设备降到散热板温度。

**交付物。** `caseA.mph` / `caseB.mph`（已求解 A + B + B2，未入库，各 1 GB）；可重跑脚本 `build_comsol.py`、`solve_and_probe.py`、`extend_orbits.py`、`probe_offline.py`、`compare_report.py`、`render_comsol.py`、`fill_sec77.py`、`organize_figures.py`；探针 CSV `out/comsol/*_probes.csv`；对比图与统计 `out/compare/`；40 张编号图与图注索引 `out/figures_final/FIGURES.md`（A 建模 / B 冻结稳态 / C 轨道温度场 / D 对比曲线）。

## 1. What was asked and what was delivered

| Phase | Deliverable | Where |
|---|---|---|
| 0 | COMSOL 6.3.0.290 located, Heat Transfer Module licensed (Surface-to-Surface + Orbital Thermal Loads), MPh 1.3.2 client working | `PHASE1_PARAMETERS.md` §Phase 0 |
| 1 | Layout survey, lumped-network description, **provenance table** (every number → file:line), conflicts, NOT-FOUND list | `PHASE1_PARAMETERS.md`, materials addendum `PHASE1_ADDENDUM_materials.md` |
| 2 | Open-loop traces at 1 s: payload power, sun vector (ECI + body frame), eclipse flag, OrbitWiz temperatures; GPU sweep; dt-equivalence check | `run_orbitwiz.py`, `out/orbitwiz/` |
| 3 | COMSOL model builder (re-runnable, commented), `caseA.mph`, `caseB.mph` | `build_comsol.py`, `geometry_spec.py`, `solve_and_probe.py`, `out/comsol/` |
| 4 | Sanity checks 0–4 | §6 below, `out/comsol/*_solve_log.json` |
| 5 | Probe CSVs, overlay plots, statistics | `compare_report.py`, `out/compare/` |

## 2. Environment (Phase 0)

COMSOL Multiphysics **6.3.0.290** at `D:\Program Files\COMSOL\COMSOL63\Multiphysics`; `license.dat` PACKAGE SSQ_0000 contains `HEATTRANSFER` (Heat Transfer Module: Heat Transfer in Shells, Surface-to-Surface Radiation, Orbital Thermal Loads), `COMSOLCOMPILER`, `CLIENTSERVER`. **MPh 1.3.2** installed into `backend/.venv` (the venv that also holds pxr/USD); `mph.start()` launches `comsolmphserver.exe` and connects in ~10 s. The COMSOL installation is Chinese-locale; all scripts run with `PYTHONIOENCODING=utf-8`.

## 3. What OrbitWiz actually is (Phase 1, condensed — full detail in `PHASE1_PARAMETERS.md`)

* **Assets**: `usd/assets/*.usdz` are scanned/AI-generated meshes with render shaders only — **no mass, density, cp, k, α or ε anywhere in USD**. Stage units: assets `metersPerUnit = 1.0`; the assembled twin stage is `metersPerUnit = 0.01` with a ×180 root scale → asset-metre × 1.8 = stage-metre. All geometry below is in stage metres.
* **Thermal model**: a **single node** (`temperature_c` = bus = cold plate = radiator), C = 160 kJ/K ("picked for legible dynamics"), `Q_out = ε σ (2 panels × 2 faces) T⁴` to 0 K with no orientation, environment = `α S illum A/4 + α·0.3·S·A·F·max(0, r̂·ŝ) + ε·237·A·F`, `F = (1−√(1−(R/r)²))/2`, R = 6371 km. GPU die is algebraic on top: `T_die = T_struct + P·R_th`; the throttle limit (83 °C V100 / 85 °C others) is applied to the die. No conduction paths, no baseplate, no radiator node; the solar array is thermally decoupled. One tick = 60 physical seconds.
* **Scenario on disk**: truss bus, 12 rack slots, radiator 1.98 × 0.792 m panels at ±Z (faces ±Y), 7 solar clusters per side (52.6 m²), `single_iss` TLE (416.7 km, 51.64°, period 5574.2 s), epoch 2024-08-22 12:00 UTC, attitude `free` (array normal = orbit normal, |sin β|).
* **User decisions (2026-08-29)**: A — WhitePaint radiator (ε 0.85 / α 0.25; the engine's un-persisted boot default is bare aluminium, which cannot produce a non-throttling case). B — materials sourced externally by me and flagged as such. C — Check 0 replaced (no USD mass). D — body frame +X = orbit normal (cell normal), +Y = ram (radiator faces), +Z = nadir (spine). E/F — case pair from a sweep; 1-s traces from a dt = 1/60 tick.

## 4. Phase 2 — open-loop traces

`run_orbitwiz.py` drives the engine's own tick (`compare_sim._OfflineTwin` → `StateEngine._update_placeholder_physics`, zero physics duplication) with `dt = 1/60` tick-seconds so every step is one physical second; 8 orbits of spin-up, 4 orbits exported.

* **dt-equivalence** (dt = 1 vs 1/60 over 2 orbits from the same state): max |ΔT_struct| = 0.31 °C; payload differs only by the 60-s-vs-1-s block-edge timing.
* **GPU sweep** (12 cards, WhitePaint, `inference` profile): V100 die max 73.5 °C, never throttles → **Case A**; A100 die 72→85 °C, throttled 81 % of the orbit → **Case B** (has a crossing event); H200/B200 pinned at 85 °C permanently (no crossing) — not usable for a crossing-time comparison.
* Exported columns include the OrbitWiz-predicted structure temperature and die temperature (the references), q_out, the three environment terms, illum/sunlit, sun vector in ECI and body frame, ECI position/velocity.
* **Hot instant** t₀ = 2051 s of the export (sunlit, sun 0.86 along −Y i.e. normal to a radiator face, peak payload block); COMSOL time τ = t − t₀. β ≈ −31°: the Sun shines on the **back (−X) face** of the array throughout the window.

## 5. Phase 3 — the COMSOL model (what was built, what was simplified)

**Geometry** (`geometry_spec.py`, all from the usdz bounding boxes × 1.8 or `gen_twin_satellite.py` constants): spine, two thruster blocks, two tanks (solid Al as drawn); 12 blade chassis extended 37 mm inward to the spine face (rack frames omitted); 12 GPU "packages" = the generator's heat-spreader box on each blade; two radiator panels; two radiator booms (5 mm short of the panel); two solar wings (7 clusters each, no booms). Radiator and array panels are **equivalent-thick shells** (20 mm model thickness with k and ρ scaled by t_real/t_model, t_real = areal density / 2700: 1.63 mm radiator, 0.93 mm array) — thermally identical to thin shells, meshable with swept prisms/tets, and avoids an inter-interface shell–solid coupling. The 95-mm scan thickness of the radiator asset is **not** used.

**Heat-transport design (external, not OrbitWiz)**: OrbitWiz has no conduction model; as drawn, the 25-mm aluminium booms conduct 0.5 W/K and a plain 1.6-mm sheet has a 17-cm fin length — a 3 kW payload cannot reach or use the radiators without heat pipes. Added: per rack a transport bundle (5 pipes, sized from the ACT CCHP 275 W capacity) up the blades' +X side, a connector to the radiator face, a header and 8 spreaders (pitch 0.1016 m, NTRS 19890011820) on each face. Modelled as slender solid blocks (12.7 mm square) with k_eff = 1.6×10⁵ W/mK (ACT R = 0.015 K/W over the 0.305-m test pipe; length-proportional = conservative), solid-aluminium capacity, white-paint optics on their exposed faces (they stand in for embedded pipes under the painted facesheet).

**Physics**: Heat Transfer in Solids (ht) + Orbital Thermal Loads (otl) with the Surface-to-Surface coupling, two spectral bands (solar / ambient), hemicube 128, deep space 2.7 K. Optics: radiator α 0.25 / ε 0.85; array +X face α 0.60 (0.80 − 0.20 electrical) / ε 0.85, −X face α 0.80 / ε 0.85; everything else bare aluminium α 0.25 / ε 0.10 (OrbitWiz coating table). Orbit: **user-defined = the OrbitWiz SGP4 ECI positions** (interpolation table); Sun: user-defined = the OrbitWiz analytic Sun vector; solar irradiance 1331 W/m² (1361/d² on the date — deliberately not the literal 1361); Earth: COMSOL "Earth" (R 6378 km), albedo 0.30, IR 237 W/m², 13-point planet disc. Heat sources: per-package heat rate = 0.95 × OrbitWiz per-card draw (interpolated table); 0.95 × 600 W platform spread over the bus. TIM: thin thermally resistive layer R = 0.06 °C·cm²/W (Honeywell PTM7000) between package and blade.

**View factors — how they are computed (Check 3 / task requirement)**: *not* OrbitWiz's sphere formula. COMSOL computes surface-to-surface view factors between all external surfaces by the hemicube method (resolution 128) and the external (Sun and planet) view factors by the same machinery, the planet being represented as 13 point sources on the visible spherical cap at the satellite's true position, Sun as an infinite-distance directional source; shadowing of the bus by the wings and radiator-to-wing exchange are therefore included. The 13- vs 51-point planet discretisation changes the integrated absorbed Earth-IR by the amount recorded in the solve log (§7).

**Studies**: OTL has no Stationary step, so the "stationary" check is a **frozen-environment transient** (global variable `tt = t·10⁻³` makes the orbit crawl 1000× slower — a strictly constant position is rejected because the velocity axis would be undefined) run for 60 000 s (≈ 8 thermal time constants); the orbital transient (`tt = t`) was *intended* to start from that state but — found in post-processing, see §7.6 — actually started from the uniform `ht` initial value (T_struct at t₀ = 50.4 °C): the study-step `initmethod/initstudy/solnum` settings did not propagate to the solver sequence (`useinitsol` was never switched on). Orbit 1 is discarded per the task, which absorbs most of the resulting warm-up; the frozen study A therefore serves as the stationary/energy-balance check only. The transient runs 3 orbits with **strict BDF-1 steps of 120 s** (60 s in the toy models; 120 s in production to keep the 17 k-triangle radiation problem at ~43 s per step) — the only stepping that survives the eclipse illumination switch (free stepping, events timelines, an Events interface and tighter tolerances all failed at the exact eclipse instant; see `smoke9–12.py`). Loads-only studies at the same times provide `otl.Gext1`/`otl.Gext2` for the explicit absorbed-power integrals (band-2 irradiation cannot be evaluated on a temperature dataset in this build — COMSOL NPE).

**Simplifications (complete list)**: rack frames omitted; blades extended to the spine (perfect contact, no bolted-joint resistance); booms not touching the panels; solar booms omitted (0.18 W/K); battery not modelled; platform heat uniform over the bus; heat-pipe network is an added design; pipe blocks are surface-mounted (white-painted) rather than embedded; equivalent-thick shells; 13-point planet disc; 120-s strict steps (eclipse edges resolved to ±120 s, OrbitWiz's own penumbra is ~10 s); solar irradiance 1331 W/m²; 2.7 K sink (OrbitWiz 0 K); COMSOL Earth radius 6378 km vs OrbitWiz 6371 km; sun vector interpolated from the OrbitWiz table (Vallado, ≤0.05° vs STK); the die temperature is not modelled in COMSOL — "die-equivalent" = COMSOL baseplate + P·R_th with OrbitWiz's R_th (flagged circular for that single quantity).

## 6. Sanity checks (Phase 4) — see §7 for the numbers

0. **Mass** — no mass attribute exists in USD (NOT FOUND). Replacement: the COMSOL geometry's mass from library aluminium and the OrbitWiz areal densities (446 kg incl. wings, 315 kg bus+payload+radiators) vs the preset's own derived estimate (477 kg, `design_presets.py:206-209`) — 6.5 % apart; derived vs derived, reported for completeness only. The COMSOL bus+payload capacity (~283 kJ/K) is 1.8× OrbitWiz's tuned 160 kJ/K — a genuine finding, not a unit error (unit path verified: usdz metersPerUnit 1.0 × 180 × 0.01).
1. **Energy balance** at the frozen steady state: sources + absorbed solar/albedo (∫α·Gext1) + absorbed Earth-IR (∫ε·Gext2) + mutual solar-band absorption vs gross emission ∫ε σ T⁴ over all exterior surfaces; residual = mutual ambient-band absorption + error.
2. **Magnitude** — radiator temperatures in §7.
3. **Radiating area** — COMSOL integrates the radiator faces: both faces of both panels = 6.273 m² (matches 4 × 1.98 × 0.792); one-face-vs-two is therefore not an issue; the 118.9 m² "all exterior" area is dominated by the wings (105 m²).
4. **Periodicity** — orbit 2 vs orbit 3 max |ΔT| in §7.

## 7. Results (Phase 5)

All COMSOL numbers below come from `out/comsol/<case>_probes.csv` (120-s output grid) and `out/compare/<case>_stats_o23.json`; the OrbitWiz reference is the 1-s trace interpolated onto the same grid. Time τ is measured from the hot instant (t₀ = 2051 s of the export); orbit 1 (τ < P = 5574 s) is discarded. Figures are indexed in `out/figures_final/FIGURES.md`.

### 7.1 Model size and cost

| Item | Value |
|---|---|
| Mesh | 22 460 tetrahedra + 520 prisms (wings, swept); **17 018 radiating boundary triangles** |
| Frozen steady state (study A, 60 000 s slow-motion transient, 31 outputs) | 533 s (A) / 542 s (B) wall, 5 cores each, both cases in parallel |
| Loads-only studies LA / LB (13-point planet, 128 hemicube) | 85 s / 1091 s |
| Orbital transient (study B, 3 orbits from uniform 50.4 °C, strict BDF-1, Δt = 120 s, 140 steps) | 6050 s (A) / 6035 s (B) ≈ 43 s per step |
| Extension B2 (2 more orbits, verified continuation of study B, same stepping) | 2485 s (A) / 2474 s (B); an earlier attempt that restarted from the uniform initial value took ≈ 4050 s and was discarded |
| Planet discretisation check (13 vs 51 point sources, frozen instant) | absorbed Earth-IR 7918 vs 8037 W (**−1.5 %**); solar-band ∫Gext1 41 330 vs 41 304 W (+0.06 %) |

### 7.2 Frozen hot-instant steady state (study A) and energy balance (Check 1)

| Quantity | Case A (V100) | Case B (A100) |
|---|---|---|
| Heat sources (12 packages + platform) | 2583 W | 3032 W |
| Radiator faces, area-weighted mean / max / min | 58.1 / 62.5 / 54.1 °C | 65.8 / 70.8 / 61.3 °C |
| GPU baseplate mean (12 TIM faces) / package max | 78.7 / 81.0 °C | 89.7 / 92.2 °C |
| Bus mean / blades mean | 85.5 / 78.4 °C | 96.2 / 89.3 °C |
| Wings mean | 16.2 °C | 16.3 °C |
| Absorbed: sources + ∫α·Gext1 + ∫ε·Gext2 + mutual solar | 2583 + 30 286 + 6512 + 284 = **39 665 W** | 3032 + 30 286 + 6512 + 284 = **40 114 W** |
| Emitted: ∫ε σ T⁴ over all exterior faces | **41 105 W** | **41 666 W** |
| Residual (= mutual ambient-band absorption Gm2 + error) | 1440 W = **3.63 %** of gross emission | 1552 W = **3.87 %** |
| of which: radiator faces emit / wings emit / bare-Al bus emits | 3641 / 35 580 / 386 W | 3989 / 35 598 / 430 W |

The residual is slightly above the 3 % target. It is *not* unexplained: COMSOL's OTL interface refuses to evaluate the mutual ambient-band irradiation `otl.Gm2` in this build (NPE), so the ambient-band exchange wings↔bus↔radiators — which physically is a few percent of the 35.6 kW the wings emit — is missing from the absorbed side. I report it as a residual rather than claiming closure. The radiating-area check (Check 3) is exact: the radiator faces integrate to 6.273 m² = 4 × 1.98 × 0.792 m², both faces of both panels, and both faces radiate (the OrbitWiz formula also uses 2 panels × 2 faces). Magnitude (Check 2): every radiator temperature in orbits 2–3 lies in 305–336 K, inside the 250–350 K band. One surprise that is physically consistent and worth knowing: the two **bare-aluminium radiator booms** (α/ε = 0.25/0.10, from the OrbitWiz coating table) reach ~118 °C in full sun — the white element in the frozen-state renders — because a low-ε surface in sunlight equilibrates hot; they are thermally insignificant (0.5 W/K) but they set the top of the colour bars.

### 7.3 Orbital transient, orbits 2–3 — per-probe statistics and maximum absolute deviation

Case A — V100, 12 cards, OrbitWiz never throttles (`out/compare/caseA_overlay_o23.png`):

| Probe | COMSOL min / max / cyclic mean (°C) | OrbitWiz single node min / max / mean (°C) | **max \|dev\|** (°C) | mean dev (°C) |
|---|---|---|---|---|
| Radiator, area-weighted mean | 31.9 / 45.1 / 38.6 | 43.8 / 52.3 / 47.7 | **12.0** | −9.1 |
| Radiator, max | 36.3 / 48.6 / 42.6 | 43.8 / 52.3 / 47.7 | **7.6** | −5.1 |
| GPU baseplate, mean of 12 TIM faces | 52.5 / 62.6 / 57.4 | 43.8 / 52.3 / 47.7 | **11.0** | +9.7 |
| Bus, volume mean | 59.0 / 68.0 / 63.1 | 43.8 / 52.3 / 47.7 | **17.5** | +15.5 |

Case B — A100, 12 cards, OrbitWiz throttled 95 % of the window (`out/compare/caseB_overlay_o23.png`):

| Probe | COMSOL min / max / cyclic mean (°C) | OrbitWiz min / max / mean (°C) | **max \|dev\|** (°C) | mean dev (°C) |
|---|---|---|---|---|
| Radiator, area-weighted mean | 47.2 / 57.9 / 52.8 | 60.4 / 66.9 / 64.9 | **16.1** | −12.1 |
| Radiator, max | 52.8 / 62.5 / 57.9 | 60.4 / 66.9 / 64.9 | **10.5** | −7.0 |
| GPU baseplate, mean | 71.3 / 80.3 / 77.0 | 60.4 / 66.9 / 64.9 | **13.8** | +12.1 |
| Bus, volume mean | 76.8 / 86.1 / 82.2 | 60.4 / 66.9 / 64.9 | **20.4** | +17.3 |

Radiated power through the radiator faces (COMSOL ∫εσT⁴ vs OrbitWiz `Q_out`), orbits 2–3 mean: 2858 vs 3204 W (A), 3414 vs 3948 W (B). COMSOL's radiators reject ~11–14 % less through the panels because part of the heat leaves through the ε 0.10 bus skin (386–430 W) and because the panels run colder.

**Reading these numbers.** The single OrbitWiz node sits *between* COMSOL's radiator and COMSOL's bus: it is ~9–12 °C hotter than the real radiator surface and ~10–17 °C colder than the electronics it is supposed to represent. That is the signature of a missing conduction path — the heat-pipe network, TIM and bus skin in COMSOL impose a bus→radiator temperature drop of ~25 °C (A) / ~30 °C (B) at 2.4–3.1 kW, which a one-node model cannot have. The second structural difference is dynamic: COMSOL's thin radiator (1.63 mm equivalent) swings ±6 °C with each eclipse, while the 160 kJ/K node barely notices the eclipse and follows only the 6-hour workload cycle; COMSOL's bus (283 kJ/K of aluminium) likewise smooths the eclipse but at a much higher mean.

### 7.4 Radiator in-plane gradient (max − area-weighted mean)

| | Case A | Case B |
|---|---|---|
| Orbits 2–3 mean / max | **3.99 / 4.60 °C** | **5.15 / 5.76 °C** |
| Per face (all four faces within 0.05 °C of each other), mean | 3.8–3.9 °C | 4.96–5.00 °C |
| max − min over the faces, mean / max | 7.2 / 8.2 °C | 9.3 / 10.5 °C |
| Frozen steady state | 4.4 °C (max 62.5, mean 58.1) | 5.0 °C |

The maps (`*_radiator_faces_*.png`) show the expected pattern: hottest along the header edge nearest the bus (where the transport bundle arrives), coldest at the far edge; the 8 spreaders at 0.1016 m pitch keep the transverse variation below ~1 °C. The gradient scales with the rejected power (A→B: +14 % power → +29 % gradient, i.e. the fin is running further into the T⁴ non-linearity).

### 7.5 Throttle-crossing comparison (85 °C / 83 °C)

Die-equivalent in COMSOL = max baseplate temperature + P·R_th with OrbitWiz's own R_th (0.12 K/W V100, 0.085 K/W A100) — the only circular ingredient, flagged in §5.

* **Case A (V100, 83 °C)** — OrbitWiz die never exceeds 73.5 °C (no crossing, by construction of the case). COMSOL's die-equivalent **crosses 83 °C at τ = 10 920 s (orbit 2) and 14 880 s (orbit 3)**, peaking at 85.7 °C at the end of each 6-h payload block. In other words, COMSOL predicts that the V100 configuration *would* throttle for the last ~35 min of each high-load block; OrbitWiz predicts it never does. The raw baseplate maximum stays well below 83 °C (54.0–64.5 °C over orbits 2–3), so the crossing is carried by the P·R_th term (up to ~21 °C at the 177 W peak per-card draw).
* **Case B (A100, 85 °C)** — OrbitWiz's die is regulated *at* 85 °C by its throttle loop for 96 % of the window and dips below it three times (τ = 3240, 12 120, 16 440 s: end of eclipse and the low-load block), re-crossing upward at τ = 5640 and 12 240 s. COMSOL's open-loop die-equivalent (driven with the same throttled power) is **97–101 °C for the entire window and never drops below 95 °C**; its first ≥ 85 °C sample is the first sample of every window, so the formal "first-crossing difference" is 0 s — a degenerate result: the two models disagree on *state* (COMSOL: throttled 100 % of the time, no un-throttle events; OrbitWiz: 96 %, two un-throttle/re-throttle events), not on *timing*. The meaningful number is the ~12–15 °C offset of the die-equivalent, which is the baseplate offset of §7.3 carried up to the die.

### 7.6 Periodicity (Check 4) — the criterion cannot apply as written; what was checked instead

Max |T(τ+P) − T(τ)| between orbits 2 and 3: radiator mean **5.9 °C**, baseplate **7.7 °C**, bus **6.3 °C** (A); 5.8 / 7.5 / 7.3 °C (B) — far above the 0.5 °C criterion. Two things had to be understood before calling this a failure:

1. **The forcing is not orbit-periodic.** OrbitWiz's `inference` workload profile has a 21 600-s cycle (3.875 orbits), so *the reference itself* changes by 4.7–7.6 °C from one orbit to the next (table in §7.7). No model can satisfy a 0.5 °C orbit-to-orbit criterion under this forcing; the criterion presupposes periodic loads.
2. **The initial condition was not the frozen state.** In post-processing the τ = 0 sample of study B turned out to be uniform 50.4 °C (radiator = baseplate = bus = wings) — the `ht` initial value, not the 85 °C frozen state; the study-step initial-value settings had not propagated to the solver sequence (`useinitsol` was off; the solver's Variables node shows `initmethod = init`). Orbit 1 (discarded) absorbs most of this warm-up: the bus rises from 50 to ~60 °C and the radiators fall from 50 to ~35 °C within the first orbit (heat-pipe coupling ≈ 100 W/K → bus time constant ≈ 45 min, not the 2 h estimated from radiation alone), but a residual of a few °C cannot be excluded from three orbits alone.

What was done about it: both cases were extended by two more orbits as a **true continuation** (`extend_orbits.py`: initial values taken from study B's *temperature* solution store — a two-step OTL study owns two stores, and "the solver of study B" resolves to the loads store whose T is frozen at the initial value, which is why a first attempt restarted at 50.44 °C and was discarded; the script now verifies the store with `withsol()` before solving and runs a 2-step continuity self-test before the full run), and Check 4 was replaced by a **same-workload-phase check**: T(τ + 21 600 s) − T(τ), which compares instants with identical payload one workload cycle apart (the eclipse phase differs by 697 s = 12 % of an orbit, which the radiator feels but the bus does not). Its results, together with the per-orbit means and the orbit-to-orbit variation of *both* models, are in §7.7. The orbits 2–3 statistics of §7.3–7.5 are reported as computed; the same-phase drift bounds the residual initial transient contained in them.

### 7.7 Orbits 4–5 (extended run, initialised from the orbit-3 state)

Same definitions as §7.3–7.6; window 3P ≤ τ ≤ 5P (`out/compare/*_stats_o45.json`, `SUMMARY_o45.md`, overlays `*_overlay_o45.png`, `*_die_o45.png`). The extension re-uses the saved models, adds loads study LB2 and temperature study B2 (strict BDF-1, Δt = 120 s, initial values = last step of study B) and the OrbitWiz traces regenerated over 7 orbits (identical to the original ones where they overlap).

**caseA — V100, never throttles in OrbitWiz**

| Probe | COMSOL min / max / cyclic mean (°C) | OrbitWiz min / max / mean (°C) | **max \|dev\|** (°C) | mean dev (°C) |
|---|---|---|---|---|
| Radiator, area-weighted mean | 34.0 / 45.9 / 40.2 | 42.8 / 51.5 / 46.8 | **10.6** | -6.6 |
| Radiator, max | 38.5 / 49.7 / 44.2 | 42.8 / 51.5 / 46.8 | **5.9** | -2.6 |
| GPU baseplate, mean of 12 TIM faces | 55.6 / 63.8 / 59.2 | 42.8 / 51.5 / 46.8 | **14.0** | +12.5 |
| Bus, volume mean | 63.2 / 68.7 / 66.2 | 42.8 / 51.5 / 46.8 | **22.5** | +19.4 |

Radiator in-plane gradient (max − area-weighted mean): mean **4.03 °C**, max **4.75 °C**; max − min over the faces mean 7.4 °C.
**Periodicity, orbit 4 vs orbit 5** (max |T(τ+P) − T(τ)|): radiator mean 3.77 °C, baseplate 5.79 °C, bus 3.60 °C → **FAIL** against the 0.5 °C criterion.
Radiated power through the radiator faces, mean: COMSOL 2916 W vs OrbitWiz Q_out 3169 W.
Throttle line 83 °C: OrbitWiz die max 72.7 °C (≥ threshold 0 % of the window; upward crossings at τ = — s, downward at — s); COMSOL die-equivalent 70.4–86.7 °C (≥ threshold 36 %; upward crossings at τ = [20803] s, downward at [24814] s).
- all: first ≥ threshold — OrbitWiz None s, COMSOL die-equiv 10919.999999999878 s, difference None s
- orbit4: first ≥ threshold — OrbitWiz None s, COMSOL die-equiv 20802.59999999811 s, difference None s
- orbit5: first ≥ threshold — OrbitWiz None s, COMSOL die-equiv 22362.599999999646 s, difference None s

Whole-run window, orbits 2–5 (`caseA_stats_o25.json`, `caseA_overlay_o25.png`): max \|dev\| Radiator, area-weighted mean **12.0 °C** (mean -7.8), Radiator, max **7.6 °C** (mean -3.8), GPU baseplate, mean of 12 TIM faces **14.0 °C** (mean +11.1), Bus, volume mean **22.5 °C** (mean +17.4); radiator gradient mean 4.01 / max 4.75 °C.

Periodicity diagnostics — per-orbit means, orbit-to-orbit variation of the *reference itself* and of COMSOL, and the same-workload-phase check:

| Orbit | mean payload (W) | OrbitWiz node mean (°C) | COMSOL radiator mean | COMSOL baseplate mean | COMSOL bus mean | bus − node | radiator − node |
|---|---|---|---|---|---|---|---|
| 1 | 1764 | 47.9 | 35.8 | 52.2 | 56.7 | +8.8 | -12.2 |
| 2 | 2111 | 46.2 | 36.8 | 55.3 | 60.7 | +14.6 | -9.3 |
| 3 | 1981 | 49.1 | 40.3 | 59.5 | 65.5 | +16.3 | -8.9 |
| 4 | 1866 | 46.3 | 39.7 | 58.7 | 65.5 | +19.2 | -6.6 |
| 5 | 1721 | 47.2 | 40.7 | 59.8 | 66.9 | +19.6 | -6.5 |

| Orbit pair | OrbitWiz node max \|ΔT\| (°C) | COMSOL radiator | COMSOL baseplate | COMSOL bus |
|---|---|---|---|---|
| 1 vs 2 | 7.58 | 12.65 | 8.47 | 8.58 |
| 2 vs 3 | 7.28 | 5.86 | 7.69 | 6.31 |
| 3 vs 4 | 4.73 | 1.47 | 2.38 | 2.85 |
| 4 vs 5 | 6.80 | 3.77 | 5.79 | 3.60 |

Same-workload-phase check, T(τ + 21 600 s) − T(τ) for τ ∈ [5574, 6120] s (7 samples at identical payload; the orbit phase is shifted by 21 600 − 3.875·5574 ≈ −697 s, i.e. eclipse timing differs by 12 % of an orbit, which the thin radiator feels and the bus does not): OrbitWiz node mean -0.36 / max \|Δ\| 0.61 °C; COMSOL radiator mean mean +2.97 / max \|Δ\| 5.12 °C; COMSOL baseplate mean mean +4.30 / max \|Δ\| 4.39 °C; COMSOL bus mean mean +5.55 / max \|Δ\| 5.80 °C.

**caseB — A100, throttled in OrbitWiz**

| Probe | COMSOL min / max / cyclic mean (°C) | OrbitWiz min / max / mean (°C) | **max \|dev\|** (°C) | mean dev (°C) |
|---|---|---|---|---|
| Radiator, area-weighted mean | 48.5 / 58.8 / 53.9 | 58.1 / 66.8 / 63.2 | **12.9** | -9.3 |
| Radiator, max | 54.1 / 63.6 / 59.1 | 58.1 / 66.8 / 63.2 | **7.1** | -4.2 |
| GPU baseplate, mean of 12 TIM faces | 74.1 / 81.6 / 78.3 | 58.1 / 66.8 / 63.2 | **16.4** | +15.1 |
| Bus, volume mean | 82.4 / 87.1 / 84.7 | 58.1 / 66.8 / 63.2 | **25.1** | +21.5 |

Radiator in-plane gradient (max − area-weighted mean): mean **5.16 °C**, max **5.82 °C**; max − min over the faces mean 9.4 °C.
**Periodicity, orbit 4 vs orbit 5** (max |T(τ+P) − T(τ)|): radiator mean 3.47 °C, baseplate 5.64 °C, bus 3.10 °C → **FAIL** against the 0.5 °C criterion.
Radiated power through the radiator faces, mean: COMSOL 3461 W vs OrbitWiz Q_out 3871 W.
Throttle line 85 °C: OrbitWiz die max 85.0 °C (≥ threshold 64 % of the window; upward crossings at τ = [18283, 27283] s, downward at [24814] s); COMSOL die-equivalent 90.5–103.7 °C (≥ threshold 100 %; upward crossings at τ = — s, downward at — s).
- all: first ≥ threshold — OrbitWiz 0.0 s, COMSOL die-equiv 0.0 s, difference 0.0 s
- orbit4: first ≥ threshold — OrbitWiz 18282.59999999949 s, COMSOL die-equiv 16842.599999999795 s, difference -1439.9999999996944 s
- orbit5: first ≥ threshold — OrbitWiz 22362.599999999646 s, COMSOL die-equiv 22362.599999999646 s, difference 0.0 s

Whole-run window, orbits 2–5 (`caseB_stats_o25.json`, `caseB_overlay_o25.png`): max \|dev\| Radiator, area-weighted mean **16.1 °C** (mean -10.7), Radiator, max **10.5 °C** (mean -5.6), GPU baseplate, mean of 12 TIM faces **16.4 °C** (mean +13.6), Bus, volume mean **25.1 °C** (mean +19.4); radiator gradient mean 5.15 / max 5.82 °C.

Periodicity diagnostics — per-orbit means, orbit-to-orbit variation of the *reference itself* and of COMSOL, and the same-workload-phase check:

| Orbit | mean payload (W) | OrbitWiz node mean (°C) | COMSOL radiator mean | COMSOL baseplate mean | COMSOL bus mean | bus − node | radiator − node |
|---|---|---|---|---|---|---|---|
| 1 | 2486 | 63.9 | 48.8 | 69.8 | 73.6 | +9.7 | -15.1 |
| 2 | 2921 | 64.3 | 51.4 | 75.3 | 79.9 | +15.6 | -12.9 |
| 3 | 2714 | 65.5 | 54.1 | 78.7 | 84.3 | +18.9 | -11.3 |
| 4 | 2673 | 63.5 | 53.8 | 78.3 | 84.4 | +20.9 | -9.7 |
| 5 | 2478 | 62.9 | 54.0 | 78.3 | 85.0 | +22.1 | -8.9 |

| Orbit pair | OrbitWiz node max \|ΔT\| (°C) | COMSOL radiator | COMSOL baseplate | COMSOL bus |
|---|---|---|---|---|
| 1 vs 2 | 6.82 | 15.44 | 8.64 | 10.14 |
| 2 vs 3 | 6.35 | 5.82 | 7.54 | 7.28 |
| 3 vs 4 | 6.23 | 1.98 | 3.62 | 2.07 |
| 4 vs 5 | 7.58 | 3.47 | 5.64 | 3.10 |

Same-workload-phase check, T(τ + 21 600 s) − T(τ) for τ ∈ [5574, 6120] s (7 samples at identical payload; the orbit phase is shifted by 21 600 − 3.875·5574 ≈ −697 s, i.e. eclipse timing differs by 12 % of an orbit, which the thin radiator feels and the bus does not): OrbitWiz node mean -0.37 / max \|Δ\| 0.73 °C; COMSOL radiator mean mean +3.10 / max \|Δ\| 5.22 °C; COMSOL baseplate mean mean +4.58 / max \|Δ\| 4.67 °C; COMSOL bus mean mean +5.97 / max \|Δ\| 6.25 °C.

### 7.8 Bottom line — which numbers to quote, and what they mean

**Which window.** The orbits 2–3 window (§7.3–7.5, as specified) still contains the tail of the warm-up from the uniform 50.4 / 66.6 °C start: the same-workload-phase check (§7.7) shows the COMSOL bus 5.6 °C (A) / 6.0 °C (B) hotter one workload cycle after the start of orbit 2, while the reference moves by −0.4 °C over the same interval; the per-orbit bus means converge from orbit 3 on (65.5 → 65.5 → 66.9 °C A; 84.3 → 84.4 → 85.0 °C B), and from orbit 3 onward COMSOL's orbit-to-orbit variation (1.5–5.8 °C) is at or below the reference's own (4.7–7.6 °C), i.e. what remains is the workload forcing, not a transient. **Orbits 4–5 are therefore the numbers to quote**; orbits 2–3 understate the bus and baseplate offsets by ≈ 4–6 °C and overstate the radiator offset by ≈ 2–3 °C.

| Quantity (orbits 4–5, cyclic mean; max \|dev\| in brackets) | Case A — V100 | Case B — A100 |
|---|---|---|
| Radiator mean: COMSOL vs OrbitWiz node | 40.2 vs 46.8 °C → **−6.6** (10.6) | 53.9 vs 63.2 °C → **−9.3** (12.9) |
| Radiator max vs node | 44.2 vs 46.8 → −2.6 (5.9) | 59.1 vs 63.2 → −4.2 (7.1) |
| GPU baseplate vs node | 59.2 vs 46.8 → **+12.5** (14.0) | 78.3 vs 63.2 → **+15.1** (16.4) |
| Bus vs node | 66.2 vs 46.8 → **+19.4** (22.5) | 84.7 vs 63.2 → **+21.5** (25.1) |
| Radiator in-plane gradient, mean / max | 4.0 / 4.8 °C | 5.2 / 5.8 °C |
| Radiated through radiator faces (COMSOL vs Q_out) | 2916 vs 3169 W | 3461 vs 3871 W |
| Throttle line | COMSOL die-equiv ≥ 83 °C for 36 % of the window (τ = 20 803–24 814 s, max 86.7 °C); OrbitWiz never (max 72.7 °C) | OrbitWiz at 85 °C 64 % of the window, un-throttled τ < 18 283 s and 24 814–27 283 s; COMSOL die-equiv 90.5–103.7 °C, never below the line |

**What it means for the lumped model.**

1. *Structure, not tuning.* The single OrbitWiz node sits between COMSOL's radiator and COMSOL's electronics: 7–9 °C above the radiator surface, 12–15 °C below the GPU baseplate, 19–22 °C below the bus. The model has no bus→radiator conduction path, so it cannot represent the ≈ 25–30 °C drop that the heat-pipe network, TIM, and bus skin impose at 2.4–3.1 kW; changing C or ε cannot fix this — a second node (electronics) with a conductance to the radiator node can.
2. *Throttle predictions differ in kind.* For the V100 case the lumped model predicts "never throttles"; the FE model predicts throttling for ~35 min of every high-load block. For the A100 case the lumped model predicts periodic un-throttling (eclipse exit / low-load block); the FE model says the die never leaves the throttled state. The difference is the same ≈ 12–15 °C baseplate offset propagated to the die; the crossing-time question ("how many seconds apart") has no answer because the two models disagree on the *state*, not the timing.
3. *Dynamics.* The 160 kJ/K node barely responds to eclipse; the FE radiator (1.63-mm equivalent skin) swings 6–12 °C per eclipse (max − min over the faces 7–9 °C), and the FE bus lags the payload by about half an orbit. The lumped radiator temperature is therefore too smooth by ~±5 °C even where its mean is right.
4. *Radiator gradient.* 4–6 °C max − mean (7–10 °C max − min) with 8 spreaders per face at 0.1016 m pitch — an isothermal-panel assumption is worth ≈ 5 °C at the radiator, small compared with the conduction-path error, but it grows with rejected power.
5. *Energy.* COMSOL rejects 8–11 % less power through the radiator panels than the lumped `Q_out` because 390–430 W leave through the ε = 0.10 bus skin (which OrbitWiz treats as non-radiating) and because the panels run colder.

**Honest limits of these numbers.** The whole heat-transport path (heat-pipe count, pitch, k_eff, TIM) is an external design (§5), so the *size* of the bus→radiator drop is a property of that design; a better-coupled design would shrink the offsets, a worse one enlarge them — but no realistic passive design brings the electronics down to the radiator temperature. Residual uncertainties of a few °C remain from the 120-s strict steps at eclipse edges, the 13-point planet disc (−1.5 % Earth IR), the 3.6–3.9 % energy-balance residual (un-evaluable mutual-IR term), the uniform-start warm-up (bounded above), and the algebraic die-equivalent (P·R_th with OrbitWiz's own R_th).

## 8. Things I am unsure about or had to judge

* The entire heat-transport design (heat pipes, pitch, count, k_eff, TIM) is external; the bus↔radiator ΔT and the radiator gradient depend on it. OrbitWiz's single node implicitly assumes infinite conductance.
* Radiator thickness: 1.63 mm solid-equivalent from OrbitWiz's 4.4 kg/m²; a real honeycomb facesheet is thinner but spreads heat through the core and pipes.
* COMSOL's bus surfaces radiate at ε 0.10 (OrbitWiz's bus does not radiate at all); the bus capacity is 1.8× OrbitWiz's.
* Solar irradiance 1331 W/m² (date-correct) instead of the task's literal 1361.
* 13-point planet discretisation and 120-s strict steps were forced by run time (measured: 75 s per step with 51 points on the lite mesh); their effect is quantified in §7.
* The frozen "stationary" state is a 1000×-slow-motion transient, not a true stationary solve (OTL limitation) — and it was *not* the initial condition of the orbital transient (uniform 50.4 °C was; §7.6). The residual warm-up after the discarded orbit 1 is bounded by the same-phase check in §7.7, not eliminated.
* The eclipse switch in COMSOL is binary and resolved to the 120-s grid; OrbitWiz has a ~10-s penumbra ramp.
* `otl.Gm2` (mutual ambient-band irradiation) cannot be evaluated in this COMSOL build; the balance residual carries it.
