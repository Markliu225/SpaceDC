# COMSOL vs OrbitWiz — comparison summary (orbits 2-5)

## caseA (V100)

| Probe | COMSOL min / max / mean (°C) | OrbitWiz min / max / mean (°C) | max |dev| (°C) | mean dev (°C) |
|---|---|---|---|---|
| radiator_mean_C | 27.8 / 45.3 / 37.3 | 42.8 / 52.3 / 47.2 | 15.0 | -10.0 |
| radiator_max_C | 32.0 / 48.6 / 41.1 | 42.8 / 52.3 / 47.2 | 10.8 | -6.1 |
| baseplate_mean_C | 47.2 / 62.6 / 55.4 | 42.8 / 52.3 / 47.2 | 11.2 | +8.1 |
| bus_mean_C | 51.2 / 68.0 / 60.9 | 42.8 / 52.3 / 47.2 | 18.4 | +13.7 |

Radiator in-plane gradient (max − area-weighted mean): mean 3.87 °C, max 4.60 °C.
Periodicity (orbit 2 vs 5, max |ΔT|): rad_mean_K 5.86 °C, baseplate_mean_K 7.69 °C, bus_mean_K 6.31 °C

Throttle threshold 83 °C: OrbitWiz die max 73.5 °C (throttled 0 % of orbits 2-3); COMSOL die-equivalent max 85.7 °C.
- orbit2: OrbitWiz first ≥ thr at None s; COMSOL die-equiv (max baseplate) at 10920.000000000195 s; raw baseplate max ≥ thr at None s; difference None s
- orbit5: OrbitWiz first ≥ thr at None s; COMSOL die-equiv (max baseplate) at 14879.999999999522 s; raw baseplate max ≥ thr at None s; difference None s
- all: OrbitWiz first ≥ thr at None s; COMSOL die-equiv (max baseplate) at 10920.000000000195 s; raw baseplate max ≥ thr at None s; difference None s

Radiated power (radiator faces, orbits 2-5): COMSOL mean 2810 W vs OrbitWiz Q_out mean 3186 W.
