# -*- coding: utf-8 -*-
"""Collect the result + modelling figures into out/figures_final/ with numbered
names and write FIGURES.md (caption index). Re-runnable; skips missing files.
    backend/.venv/Scripts/python organize_figures.py
A = thermal model (geometry / mesh / optics / loads), B = frozen steady state,
C = orbital transient fields, D = COMSOL-vs-OrbitWiz comparison curves.
"""
import os, shutil
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "out")
FIG, CMP, FIN = os.path.join(OUT, "figures"), os.path.join(OUT, "compare"), os.path.join(OUT, "figures_final")
os.makedirs(FIN, exist_ok=True)
# (source dir, source file, target file, caption)
ITEMS = [
 # --- A. thermal model: geometry_spec drawings (plot_geometry.py) + COMSOL-native renders (render_comsol.py)
 (FIG, "model_geometry_3d.png",  "A01_model_geometry_3d.png",  "Model geometry (geometry_spec.py), isometric: spine/tanks/thrusters bus, 12 blade chassis + GPU packages, radiator panels at +/-Z (faces +/-Y) with booms, two solar wings at +/-X. Body frame +X orbit normal / +Y ram / +Z nadir."),
 (FIG, "model_geometry_bus.png", "A02_model_geometry_bus.png", "Bus zoom of the geometry: packages on the blade baseplates (TIM = thin resistive layer 0.06 C.cm2/W), heat-pipe transport bundles (5 pipes/rack, +X side of the blades), header + 8 spreaders per radiator face at 0.1016 m pitch."),
 (FIG, "model_geometry_ortho.png","A03_model_geometry_ortho.png","Orthographic XY / XZ / YZ views with dimensions (stage metres = usdz metres x 1.8)."),
 (FIG, "caseA_cm_mesh_full.png",  "A04_mesh_full.png",  "COMSOL mesh, full satellite: 22 460 tets + 520 swept prisms (wings); 17 018 radiating boundary triangles."),
 (FIG, "caseA_cm_mesh_bus.png",   "A05_mesh_bus.png",   "COMSOL mesh, bus zoom: refined on packages / baseplates (h ~ 6-7 cm), radiator shells h ~ 8 cm, heat-pipe blocks h ~ 10 cm."),
 (FIG, "caseA_cm_eps_map.png",    "A06_emissivity_map.png", "Ambient-band emissivity actually assigned in the solver (otl.epsilon_rad): 0.85 white paint on radiators + pipe blocks, 0.85 on solar cells (both faces), 0.10 bare aluminium on bus, blades, booms. Verifies the two-band optics assignment (the bug that once zeroed all emissivities)."),
 (FIG, "caseA_cm_Gext1_t0.png",   "A07_solar_irradiation_t0.png", "Solar-band external irradiation otl.Gext1 (W/m2) at the hot instant t0: direct Sun (1331 W/m2) + albedo, hemicube-128 view factors incl. shadowing. beta ~ -31 deg: Sun on the -X back face of the wings."),
 (FIG, "caseA_cm_Gext1_t0_bus.png","A08_solar_irradiation_t0_bus.png", "Same, bus zoom: radiator faces and blade edges lit, package tops shadowed by neighbouring blades."),
 (FIG, "caseA_cm_Gext2_t0.png",   "A09_earthIR_irradiation_t0.png", "Ambient-band external irradiation otl.Gext2 (W/m2) at t0: Earth IR 237 W/m2 x planet view factor (13-point disc); nadir-facing (+Z) faces receive ~200 W/m2."),
 # --- B. frozen hot-instant steady state (study A)
 (FIG, "caseA_cm_T_frozen_full.png", "B01_caseA_T_frozen_full.png", "Case A (V100): surface temperature at the frozen hot-instant steady state, full satellite (colour 10-100 C; wings ~16 C, bus ~85 C, bare-Al booms saturate at ~118 C)."),
 (FIG, "caseA_cm_T_frozen_bus.png",  "B02_caseA_T_frozen_bus.png",  "Case A: bus zoom - packages 81 C, baseplates 79 C, bus 85 C, transport bundles, radiators 54-63 C: the ~25 C bus-to-radiator drop that a single-node model cannot represent."),
 (FIG, "caseA_cm_T_frozen_rad.png",  "B03_caseA_T_frozen_radiators.png", "Case A: -Y (wake) radiator faces with the header/spreader pattern, frozen steady state."),
 (FIG, "caseA_radiator_faces_frozen.png","B04_caseA_radiator_face_maps_frozen.png","Case A: node-wise maps of the four radiator faces (+Y/-Y of both panels) with mean / max / min and max-mean (in-plane gradient) per face."),
 (FIG, "caseB_cm_T_frozen_full.png", "B05_caseB_T_frozen_full.png", "Case B (A100): frozen steady state, full satellite."),
 (FIG, "caseB_cm_T_frozen_bus.png",  "B06_caseB_T_frozen_bus.png",  "Case B: bus zoom - packages 92 C, bus 96 C, radiators 61-71 C."),
 (FIG, "caseB_radiator_faces_frozen.png","B07_caseB_radiator_face_maps_frozen.png","Case B: radiator face maps at the frozen steady state."),
 # --- C. orbital transient fields (study B, orbit 2)
 (FIG, "caseA_cm_T_orbit2_hot_full.png",  "C01_caseA_T_orbit2_hot_full.png",  "Case A: surface temperature at the hottest radiator instant of orbit 2 (tau = 11 040 s, end of the high-load block), full satellite."),
 (FIG, "caseA_cm_T_orbit2_hot_bus.png",   "C02_caseA_T_orbit2_hot_bus.png",   "Case A: bus zoom at the hottest instant."),
 (FIG, "caseA_cm_T_orbit2_cold_full.png", "C03_caseA_T_orbit2_cold_full.png", "Case A: coldest radiator instant of orbit 2 (tau = 8089 s, end of eclipse) - wings at -45 C, radiators 32 C."),
 (FIG, "caseA_cm_T_orbit2_cold_bus.png",  "C04_caseA_T_orbit2_cold_bus.png",  "Case A: bus zoom at the coldest instant - bus still 59 C while the radiators are at 32 C."),
 (FIG, "caseA_radiator_faces_orbit2_hot.png",  "C05_caseA_radiator_face_maps_orbit2_hot.png",  "Case A: radiator face maps at the hottest instant of orbit 2 (max-mean 3.0 C per face)."),
 (FIG, "caseA_radiator_faces_orbit2_cold.png", "C06_caseA_radiator_face_maps_orbit2_cold.png", "Case A: radiator face maps at the coldest instant of orbit 2."),
 (FIG, "caseB_cm_T_orbit2_hot_full.png",  "C07_caseB_T_orbit2_hot_full.png",  "Case B: hottest radiator instant of orbit 2, full satellite."),
 (FIG, "caseB_cm_T_orbit2_hot_bus.png",   "C08_caseB_T_orbit2_hot_bus.png",   "Case B: bus zoom at the hottest instant - packages ~82 C, bus ~86 C."),
 (FIG, "caseB_cm_T_orbit2_cold_full.png", "C09_caseB_T_orbit2_cold_full.png", "Case B: coldest radiator instant of orbit 2, full satellite."),
 (FIG, "caseB_cm_T_orbit2_cold_bus.png",  "C10_caseB_T_orbit2_cold_bus.png",  "Case B: bus zoom at the coldest instant."),
 (FIG, "caseB_radiator_faces_orbit2_hot.png",  "C11_caseB_radiator_face_maps_orbit2_hot.png",  "Case B: radiator face maps at the hottest instant of orbit 2."),
 (FIG, "caseB_radiator_faces_orbit2_cold.png", "C12_caseB_radiator_face_maps_orbit2_cold.png", "Case B: radiator face maps at the coldest instant of orbit 2."),
 # --- D. comparison (results)
 (CMP, "caseA_overlay_o23.png", "D01_caseA_overlay_orbits2-3.png", "Case A (V100, never throttles in OrbitWiz): COMSOL vs OrbitWiz single node - radiator mean, radiator max, GPU baseplate mean, bus mean over orbits 2-3 (grey = eclipse). Max |dev| 12.0 / 7.6 / 11.0 / 17.5 C."),
 (CMP, "caseA_die_o23.png",     "D02_caseA_die_orbits2-3.png",     "Case A: GPU die - OrbitWiz die (T_struct + P.R_th) vs COMSOL die-equivalent (baseplate max + P.R_th) against the 83 C V100 throttle line: COMSOL crosses at tau = 10 920 s and 14 880 s, OrbitWiz never."),
 (CMP, "caseB_overlay_o23.png", "D03_caseB_overlay_orbits2-3.png", "Case B (A100, throttled in OrbitWiz): overlay over orbits 2-3. Max |dev| 16.1 / 10.5 / 13.8 / 20.4 C."),
 (CMP, "caseB_die_o23.png",     "D04_caseB_die_orbits2-3.png",     "Case B: die vs the 85 C line - OrbitWiz regulated at 85 C (dips at eclipse exit / low-load block), COMSOL die-equivalent 97-101 C throughout (no un-throttle events)."),
 (CMP, "caseA_overlay_o45.png", "D05_caseA_overlay_orbits4-5.png", "Case A, extended run (orbits 4-5, initialised from the orbit-3 state): the periodic-steady-state comparison once the frozen-start transient has decayed."),
 (CMP, "caseA_die_o45.png",     "D06_caseA_die_orbits4-5.png",     "Case A, orbits 4-5: die-equivalent vs OrbitWiz die."),
 (CMP, "caseB_overlay_o45.png", "D07_caseB_overlay_orbits4-5.png", "Case B, extended run (orbits 4-5) overlay."),
 (CMP, "caseB_die_o45.png",     "D08_caseB_die_orbits4-5.png",     "Case B, orbits 4-5: die temperature and 85 C crossings."),
 (CMP, "caseA_overlay_o25.png", "D09_caseA_overlay_orbits2-5.png", "Case A, whole run (orbits 2-5 = one full 21 600-s workload cycle): shows that the orbit-to-orbit variation is workload-driven in both models, not a residual initial transient."),
 (CMP, "caseB_overlay_o25.png", "D10_caseB_overlay_orbits2-5.png", "Case B, whole run (orbits 2-5)."),
 (CMP, "caseA_die_o25.png",     "D11_caseA_die_orbits2-5.png",     "Case A, orbits 2-5: die-equivalent vs OrbitWiz die, 83 C line."),
 (CMP, "caseB_die_o25.png",     "D12_caseB_die_orbits2-5.png",     "Case B, orbits 2-5: die temperature vs the 85 C line."),
]
lines = ["# Figure index (`out/figures_final/`)\n",
         "A = thermal model (geometry / mesh / optics / loads), B = frozen hot-instant steady state, C = orbital transient fields (orbit 2), D = COMSOL-vs-OrbitWiz comparison curves.\n",
         "COMSOL-native renders (`*_cm_*`, via render_comsol.py: PlotGroup3D + Image export on the mph server); face maps and comparison curves are matplotlib (render_fields.py / compare_report.py).\n"]
n = 0
for src_dir, src, dst, cap in ITEMS:
    s = os.path.join(src_dir, src)
    if not os.path.exists(s):
        lines.append(f"- *(missing)* `{dst}` - {cap}"); continue
    shutil.copyfile(s, os.path.join(FIN, dst)); n += 1
    lines.append(f"- ![{dst}]({dst})\n  **{dst}** - {cap}\n")
open(os.path.join(FIN, "FIGURES.md"), "w", encoding="utf-8").write("\n".join(lines))
print(f"{n}/{len(ITEMS)} figures -> {FIN}")
