# COMSOL vs OrbitWiz — comparison summary (orbits 2-3)

## caseA (V100)

| Probe | COMSOL min / max / mean (°C) | OrbitWiz min / max / mean (°C) | max |dev| (°C) | mean dev (°C) |
|---|---|---|---|---|
| radiator_mean_C | 31.9 / 45.1 / 38.6 | 43.8 / 52.3 / 47.7 | 12.0 | -9.1 |
| radiator_max_C | 36.3 / 48.6 / 42.6 | 43.8 / 52.3 / 47.7 | 7.6 | -5.1 |
| baseplate_mean_C | 52.5 / 62.6 / 57.4 | 43.8 / 52.3 / 47.7 | 11.0 | +9.7 |
| bus_mean_C | 59.0 / 68.0 / 63.1 | 43.8 / 52.3 / 47.7 | 17.5 | +15.5 |

Radiator in-plane gradient (max − area-weighted mean): mean 3.99 °C, max 4.60 °C.
Periodicity (orbit 2 vs 3, max |ΔT|): rad_mean_K 5.86 °C, baseplate_mean_K 7.69 °C, bus_mean_K 6.31 °C

Throttle threshold 83 °C: OrbitWiz die max 73.5 °C (throttled 0 % of orbits 2-3); COMSOL die-equivalent max 85.7 °C.
- orbit2: OrbitWiz first ≥ thr at None s; COMSOL die-equiv (max baseplate) at 10920.000000000195 s; raw baseplate max ≥ thr at None s; difference None s
- orbit3: OrbitWiz first ≥ thr at None s; COMSOL die-equiv (max baseplate) at 14879.999999999522 s; raw baseplate max ≥ thr at None s; difference None s
- all: OrbitWiz first ≥ thr at None s; COMSOL die-equiv (max baseplate) at 10920.000000000195 s; raw baseplate max ≥ thr at None s; difference None s

Radiated power (radiator faces, orbits 2-3): COMSOL mean 2858 W vs OrbitWiz Q_out mean 3204 W.
