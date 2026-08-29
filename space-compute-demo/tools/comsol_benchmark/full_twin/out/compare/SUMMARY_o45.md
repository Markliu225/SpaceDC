# COMSOL vs OrbitWiz — comparison summary (orbits 4-5)

## caseA (V100)

| Probe | COMSOL min / max / mean (°C) | OrbitWiz min / max / mean (°C) | max |dev| (°C) | mean dev (°C) |
|---|---|---|---|---|
| radiator_mean_C | 34.0 / 45.9 / 40.2 | 42.8 / 51.5 / 46.8 | 10.6 | -6.6 |
| radiator_max_C | 38.5 / 49.7 / 44.2 | 42.8 / 51.5 / 46.8 | 5.9 | -2.6 |
| baseplate_mean_C | 55.6 / 63.8 / 59.2 | 42.8 / 51.5 / 46.8 | 14.0 | +12.5 |
| bus_mean_C | 63.2 / 68.7 / 66.2 | 42.8 / 51.5 / 46.8 | 22.5 | +19.4 |

Radiator in-plane gradient (max − area-weighted mean): mean 4.03 °C, max 4.75 °C.
Periodicity (orbit 4 vs 5, max |ΔT|): rad_mean_K 3.77 °C, baseplate_mean_K 5.79 °C, bus_mean_K 3.60 °C

Throttle threshold 83 °C: OrbitWiz die max 72.7 °C (throttled 0 % of orbits 2-3); COMSOL die-equivalent max 86.7 °C.
- orbit4: OrbitWiz first ≥ thr at None s; COMSOL die-equiv (max baseplate) at 20802.59999999811 s; raw baseplate max ≥ thr at None s; difference None s
- orbit5: OrbitWiz first ≥ thr at None s; COMSOL die-equiv (max baseplate) at 22362.599999999646 s; raw baseplate max ≥ thr at None s; difference None s
- all: OrbitWiz first ≥ thr at None s; COMSOL die-equiv (max baseplate) at 10919.999999999878 s; raw baseplate max ≥ thr at None s; difference None s

Radiated power (radiator faces, orbits 4-5): COMSOL mean 2916 W vs OrbitWiz Q_out mean 3169 W.

## caseB (A100)

| Probe | COMSOL min / max / mean (°C) | OrbitWiz min / max / mean (°C) | max |dev| (°C) | mean dev (°C) |
|---|---|---|---|---|
| radiator_mean_C | 48.5 / 58.8 / 53.9 | 58.1 / 66.8 / 63.2 | 12.9 | -9.3 |
| radiator_max_C | 54.1 / 63.6 / 59.1 | 58.1 / 66.8 / 63.2 | 7.1 | -4.2 |
| baseplate_mean_C | 74.1 / 81.6 / 78.3 | 58.1 / 66.8 / 63.2 | 16.4 | +15.1 |
| bus_mean_C | 82.4 / 87.1 / 84.7 | 58.1 / 66.8 / 63.2 | 25.1 | +21.5 |

Radiator in-plane gradient (max − area-weighted mean): mean 5.16 °C, max 5.82 °C.
Periodicity (orbit 4 vs 5, max |ΔT|): rad_mean_K 3.47 °C, baseplate_mean_K 5.64 °C, bus_mean_K 3.10 °C

Throttle threshold 85 °C: OrbitWiz die max 85.0 °C (throttled 64 % of orbits 2-3); COMSOL die-equivalent max 103.7 °C.
- orbit4: OrbitWiz first ≥ thr at 18282.59999999949 s; COMSOL die-equiv (max baseplate) at 16842.599999999795 s; raw baseplate max ≥ thr at None s; difference -1439.9999999996944 s
- orbit5: OrbitWiz first ≥ thr at 22362.599999999646 s; COMSOL die-equiv (max baseplate) at 22362.599999999646 s; raw baseplate max ≥ thr at None s; difference 0.0 s
- all: OrbitWiz first ≥ thr at 0.0 s; COMSOL die-equiv (max baseplate) at 0.0 s; raw baseplate max ≥ thr at None s; difference 0.0 s

Radiated power (radiator faces, orbits 4-5): COMSOL mean 3461 W vs OrbitWiz Q_out mean 3871 W.
