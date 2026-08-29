# Phase 1 addendum — externally sourced parameters (user decision B, 2026-08-29: "你去找")

OrbitWiz contains **no** material properties, masses, contact conductances or heat-transport design. The user authorised me to source them. Every value below is **NOT an OrbitWiz value**; it is marked EXTERNAL with its source, and the thermal comparison inherits its uncertainty. Nothing in this table comes from the lumped thermal model.

| Parameter | Value | Unit | Source | Class | Notes / confidence |
|---|---|---|---|---|---|
| Aluminium k / ρ / cp (bus, blades, packages, booms, radiator & array sheets, heat-pipe walls) | 238 / 2700 / 900 | W/mK, kg/m³, J/kgK | COMSOL 6.3 built-in material library "Aluminum" (Basic property group), read from the shipped model `applications/Heat_Transfer_Module/Orbital_Thermal_Loads/spacecraft_thermal_analysis.mph` | EXTERNAL (library) | high; GSFC PD-ED-1209 names 6061/6063 as the flight alloys — same generic values |
| Radiator sheet equivalent thickness | 1.63 (= 4.4 / 2700) | mm | OrbitWiz areal density 4.4 kg/m² (state_engine.py:180, WhitePaint entry) ÷ library ρ | derived from an OrbitWiz semi-primitive | medium — a real honeycomb panel has 2×0.2–1.0 mm facesheets (US 9878808 B2) + core; the solid-equivalent sheet carries the same mass and a comparable in-plane conductance |
| Solar-array equivalent thickness | 0.93 (= 2.5 / 2700) | mm | OrbitWiz areal density 2.5 kg/m² (state_engine.py:126, Si) ÷ library ρ | derived | low — layup unknown; only affects the array's own capacity/gradient, which is thermally decoupled from the bus in both models |
| Equivalent-thick-shell trick | model thickness 20 mm; k, ρ scaled by t_real/t_model (in-plane k·t and areal ρ·cp·t preserved) | — | standard thin-shell equivalence (through-thickness conductance 970 W/m²K ≫ radiative h) | modelling choice | high |
| GPU package → baseplate TIM | 0.06 °C·cm²/W (upper bound of 0.04–0.06 @ no shim, ASTM D5470 mod.); k 6.0–8.5 W/mK | m²K/W = 6e-6 | Honeywell TIM portfolio brochure `pmt-am-brochure-tims-2608-english-final-9-6-2022.pdf`, p.6 (PTM7000 series) | EXTERNAL (vendor) | high for the number; negligible in the result (R = 6e-6 / 0.039 m² = 1.5e-4 K/W per package) |
| Heat-pipe transport resistance | R = 0.015 K/W per pipe at 275 W (HHF2); HHF1 > 320 W at < 0.012 K/W; test pipes ~12 in long; evaporator 5.08 × 1.27 cm | K/W | Advanced Cooling Technologies, "High-Heat-Flux (>50 W/cm²) Hybrid Constant Conductance Heat Pipes" (1-act.com PDF) | EXTERNAL (vendor paper) | medium; used as **k_eff = L_ref/(R·A) = 1.6e5 W/mK** for Thin-Rod edges (length-proportional reading = conservative) |
| Heat-pipe capacity for pipe count | Q_max = 275 W per pipe | W | same paper | EXTERNAL | transport bundles: n = ceil(3 blades × peak heat / 275) = 5 (A100 case sizing, same hardware for both cases) |
| Heat-pipe outer diameter | 12.7 (= evaporator contact width 1.27 cm) | mm | same paper | EXTERNAL (inferred from contact width) | low-medium |
| Container / fluid | Al 6061/6063, anhydrous ammonia, 200–350 K | — | NASA GSFC Preferred Reliability Practice PD-ED-1209 (klabs.org) | EXTERNAL | qualitative |
| Radiator spreader-pipe pitch | 0.1016 (condenser branch spacing, Fig. 20) | m | NASA NTRS 19890011820 (Hughes, "High capacity demonstration of honeycomb panel heat pipes"), Fig. 20 common data; same report: 5.08 cm sideflow sections, optimised max spacing ≈ 15 cm | EXTERNAL | medium — a design-family number, not this radiator's design; sensitivity noted in the report |
| Radiator efficiency expectation (for interpretation only) | > 95 %, ΔT "a few °C" for CCHP-embedded panels | — | ACT blog "Thermally Enhanced Honeycomb Panels for Spacecraft" | EXTERNAL (qualitative) | used only to judge whether the computed gradient is plausible |
| Solar irradiance in COMSOL | 1331 (= 1361/d_AU² on 2024-08-22; window mean of the OrbitWiz trace column `solar_flux_w_m2`) | W/m² | S₀ geodyn.py:32 × analytic Earth–Sun distance (geodyn.sun_teme) | primitive + astronomy | **deviates from the task's literal "1361"**: 1361 is the 1-AU constant; using it would put a 2.2 % environment mismatch between the two models |
| Deep-space sink | 2.7 | K | task specification | — | OrbitWiz uses 0 K; difference < 0.01 K |
| Earth radius / mass for view factors | 6378 km / 5.972e24 kg (COMSOL "Earth" preset) | — | COMSOL Planet Properties default | EXTERNAL (COMSOL) | OrbitWiz uses 6371 km — deliberately not copied; VF difference ≈ 0.2 % |
| Albedo / Earth IR | 0.30 / 237 | –, W/m² | geodyn.py:34, 33 (same constants as the task) | primitive | — |
| Bus / blade external surfaces optics | α 0.25 / ε 0.10 (bare aluminium) | — | state_engine.py:179 "Aluminum" coating entry | primitive (OrbitWiz coating table) | OrbitWiz's thermal model never radiates from the bus; COMSOL does, at this low ε |
| Radiator optics (both faces) | α 0.25 / ε 0.85 | — | state_engine.py:180 WhitePaint (user decision A) | primitive | — |
| Array optics | +X cell face α 0.60 (0.80 − 0.20 electrical), −X back α 0.80; ε 0.85 both | — | state_engine.py:150-152 | primitive constants, per-face split is my reading | the sun is on the −X (back) face for this window (β ≈ −31°) |

## Geometry simplifications (all reported in the final summary)
1. Rack frames omitted (open frames); each blade chassis extended 37 mm inward to the spine face (perfect contact).
2. Radiator panel drawn 95 mm thick (visual scan) → equivalent 20-mm shell with the 1.63-mm-sheet properties.
3. Radiator booms shortened by 5 mm so they do not touch the panel (conductance 0.5 W/K, negligible vs. the heat pipes); the heat-pipe rods are the only bus↔radiator coupling.
4. Solar-array booms omitted (0.18 W/K); wings are separate, non-touching domains — matches OrbitWiz's "array thermally decoupled from the bus" (state_engine.py:137-146).
5. Battery not modelled (no geometry, no thermal role in OrbitWiz).
6. Platform 600 W × 0.95 dissipated uniformly in the spine (location NOT FOUND in OrbitWiz).
7. GPU heat = 0.95 × electrical draw per card (OrbitWiz's RF factor), applied as a heat rate in the package block on top of each blade (footprint = OrbitWiz's "Heatsink" box, gen_twin_satellite.py:652).
8. Heat-pipe network is an added thermal-control design (OrbitWiz has none): 4 transport bundles (5 pipes) blades→radiator faces, 1 header + 8 spreaders (pitch 0.1016 m) per radiator face. Modelled as Thin Rod edges with k_eff 1.6e5 W/mK, solid-aluminium capacity.
