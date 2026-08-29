# COMSOL vs OrbitWiz — comparison summary (orbits 2-5)

## caseA (V100)

| Probe | COMSOL min / max / mean (°C) | OrbitWiz min / max / mean (°C) | max |dev| (°C) | mean dev (°C) |
|---|---|---|---|---|
| radiator_mean_C | 31.9 / 45.9 / 39.4 | 42.8 / 52.3 / 47.2 | 12.0 | -7.8 |
| radiator_max_C | 36.3 / 49.7 / 43.4 | 42.8 / 52.3 / 47.2 | 7.6 | -3.8 |
| baseplate_mean_C | 52.5 / 63.8 / 58.3 | 42.8 / 52.3 / 47.2 | 14.0 | +11.1 |
| bus_mean_C | 59.0 / 68.7 / 64.6 | 42.8 / 52.3 / 47.2 | 22.5 | +17.4 |

Radiator in-plane gradient (max − area-weighted mean): mean 4.01 °C, max 4.75 °C.
Periodicity (orbit 2 vs 5, max |ΔT|): rad_mean_K 5.86 °C, baseplate_mean_K 7.69 °C, bus_mean_K 6.31 °C

Throttle threshold 83 °C: OrbitWiz die max 73.5 °C (throttled 0 % of orbits 2-3); COMSOL die-equivalent max 86.7 °C.
- orbit2: OrbitWiz first ≥ thr at None s; COMSOL die-equiv (max baseplate) at 10919.999999999878 s; raw baseplate max ≥ thr at None s; difference None s
- orbit5: OrbitWiz first ≥ thr at None s; COMSOL die-equiv (max baseplate) at 14879.999999999518 s; raw baseplate max ≥ thr at None s; difference None s
- all: OrbitWiz first ≥ thr at None s; COMSOL die-equiv (max baseplate) at 10919.999999999878 s; raw baseplate max ≥ thr at None s; difference None s

Radiated power (radiator faces, orbits 2-5): COMSOL mean 2887 W vs OrbitWiz Q_out mean 3186 W.

## caseB (A100)

| Probe | COMSOL min / max / mean (°C) | OrbitWiz min / max / mean (°C) | max |dev| (°C) | mean dev (°C) |
|---|---|---|---|---|
| radiator_mean_C | 47.2 / 58.8 / 53.3 | 58.1 / 66.9 / 64.1 | 16.1 | -10.7 |
| radiator_max_C | 52.8 / 63.6 / 58.5 | 58.1 / 66.9 / 64.1 | 10.5 | -5.6 |
| baseplate_mean_C | 71.3 / 81.6 / 77.6 | 58.1 / 66.9 / 64.1 | 16.4 | +13.6 |
| bus_mean_C | 76.8 / 87.1 / 83.4 | 58.1 / 66.9 / 64.1 | 25.1 | +19.4 |

Radiator in-plane gradient (max − area-weighted mean): mean 5.15 °C, max 5.82 °C.
Periodicity (orbit 2 vs 5, max |ΔT|): rad_mean_K 5.82 °C, baseplate_mean_K 7.54 °C, bus_mean_K 7.28 °C

Throttle threshold 85 °C: OrbitWiz die max 85.0 °C (throttled 80 % of orbits 2-3); COMSOL die-equivalent max 103.7 °C.
- orbit2: OrbitWiz first ≥ thr at 5639.999999999749 s; COMSOL die-equiv (max baseplate) at 5639.999999999749 s; raw baseplate max ≥ thr at None s; difference 0.0 s
- orbit5: OrbitWiz first ≥ thr at 11159.999999999722 s; COMSOL die-equiv (max baseplate) at 11159.999999999722 s; raw baseplate max ≥ thr at None s; difference 0.0 s
- all: OrbitWiz first ≥ thr at 0.0 s; COMSOL die-equiv (max baseplate) at 0.0 s; raw baseplate max ≥ thr at None s; difference 0.0 s

Radiated power (radiator faces, orbits 2-5): COMSOL mean 3438 W vs OrbitWiz Q_out mean 3910 W.
