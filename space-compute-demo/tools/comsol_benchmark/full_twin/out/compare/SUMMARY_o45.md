# COMSOL vs OrbitWiz — comparison summary (orbits 4-5)

## caseA (V100)

| Probe | COMSOL min / max / mean (°C) | OrbitWiz min / max / mean (°C) | max |dev| (°C) | mean dev (°C) |
|---|---|---|---|---|
| radiator_mean_C | 27.8 / 45.3 / 35.9 | 42.8 / 51.5 / 46.8 | 15.0 | -10.9 |
| radiator_max_C | 32.0 / 46.9 / 39.7 | 42.8 / 51.5 / 46.8 | 10.8 | -7.1 |
| baseplate_mean_C | 47.2 / 58.5 / 53.3 | 42.8 / 51.5 / 46.8 | 11.2 | +6.5 |
| bus_mean_C | 51.2 / 62.9 / 58.7 | 42.8 / 51.5 / 46.8 | 18.4 | +11.9 |

Radiator in-plane gradient (max − area-weighted mean): mean 3.76 °C, max 4.59 °C.
Periodicity (orbit 4 vs 5, max |ΔT|): rad_mean_K 6.89 °C, baseplate_mean_K 9.93 °C, bus_mean_K 10.34 °C

Throttle threshold 83 °C: OrbitWiz die max 72.7 °C (throttled 0 % of orbits 2-3); COMSOL die-equivalent max 81.2 °C.
- orbit4: OrbitWiz first ≥ thr at None s; COMSOL die-equiv (max baseplate) at None s; raw baseplate max ≥ thr at None s; difference None s
- orbit5: OrbitWiz first ≥ thr at None s; COMSOL die-equiv (max baseplate) at None s; raw baseplate max ≥ thr at None s; difference None s
- all: OrbitWiz first ≥ thr at None s; COMSOL die-equiv (max baseplate) at 10920.000000000195 s; raw baseplate max ≥ thr at None s; difference None s

Radiated power (radiator faces, orbits 4-5): COMSOL mean 2761 W vs OrbitWiz Q_out mean 3169 W.
