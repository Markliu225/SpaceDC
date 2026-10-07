# SDTwin Thermal module: implementation and test contract

This file is the single contract for the code under `Thermal/`. The normative source is the design report
`Thermal/SDTwin_Thermal_Design_Report_EN.docx` (Chinese twin `..._CN.docx`, same content). Where this contract
and the design report differ, the design report wins and this file must be corrected.

Plain-text dumps of the reports, with equations, for reading:
- Thermal design EN: `C:\Users\markl\AppData\Local\Temp\claude\c--Workspace-SpaceDC\b11ed6c3-4f31-4d80-b2e1-bcf1cceefcc7\scratchpad\en_math.txt`
- Thermal design CN: `...\scratchpad\cn_math.txt`
- Power design CN: `...\scratchpad\power_cn.txt` (source: `Power/SDTwin_Power_Design_Report_CN.docx`)
- Test cases (Chinese, normative for the tests): the `CASES` dict in `Thermal/test_report/build_test_report_cn.py`

## Layout

```
Thermal/
  thermal/            module under test, exactly the package of design section 3.2
    __init__.py       exports the 4 data types and 5 functions of design appendix A, plus the error classes
    types.py          ThermalParameters, ThermalState, ThermalInputs, ThermalEvaluation, SurfaceRecord, constants, errors
    parameters.py     assemble_thermal_parameters
    environment.py    prepare_surface_environment, calculate_surface_heat
    model.py          calculate_heat_flows, thermal_derivative
  sdtwin_sim/         support code that the design places outside the thermal package
    earth_flux.py     earth_flux provider (design 5.3: albedo and infrared are new environment data)
    power_stand_in.py stand-in of the Power module written from the Power design report interfaces and P1 to P11
    coupled.py        coupled procedure of thermal design chapters 7 and 8 (trial and accepted states, events, archive)
    scene.py          SimReady asset and scene assembly of thermal design 9.3 and 9.4 (USD geometry via pxr)
  tests/              one pytest module per test case, test data under tests/data, evidence under tests/results
  test_report/        report generator (do not edit during implementation or testing)
```

Interpreter: `Thermal/.venv/Scripts/python.exe` (Python 3.11; numpy, scipy, astropy, pytest, usd-core, and the Orbit
package `ntu_space_dynamics` installed in editable mode). Run tests from `Thermal/`:
`.venv/Scripts/python.exe -m pytest tests -q`. `tests/conftest.py` puts `Thermal/` on `sys.path`, so tests import
`thermal` and `sdtwin_sim` directly. Do not install anything else without recording it here.

## Conventions (design 1.4, 5.1, 6.1)

- Units: K, s, W, m, J/K, K/W. Temperatures inside the module are kelvin.
- Node order `NODE_ORDER = ("S", "J", "C", "B", "D", "R")`; path order `PATH_ORDER = ("SR", "JC", "CR", "BR", "DR")`;
  path end nodes `PATH_NODES = {"SR": ("S","R"), "JC": ("J","C"), "CR": ("C","R"), "BR": ("B","R"), "DR": ("D","R")}`;
  exposed nodes `EXPOSED_NODES = ("S", "R")` give the order of `Q_env_W` and `Q_emit_W`.
- A positive heat flow on path `ij` goes from the first node to the second (T2: `q_ij = (T_i - T_j) / R_ij`).
- `time_s` is seconds from one timezone-aware UTC epoch; every record carries `run_id` and `time_s`.
- Power ports: `P_pv_W` from SolarArray01 (node S), `P_load_W` from Compute01 (node J), `Q_B_W` from Battery01 (node B),
  `Q_D_W` from PDU01 (node D). Controller01 and PDU01 share node D.
- Stefan-Boltzmann constant 5.670374419e-8 W m^-2 K^-4 (design table 5). No deep-space background term (design 4.4).
- No default device values anywhere in `thermal/`. Missing or invalid data raises an error that names the record and field.
- Functions return new objects and never modify their inputs.

## thermal/types.py

Errors: `ThermalError(ValueError)`; `ThermalConfigurationError(ThermalError)` for assembly or parameter problems;
`ThermalInputError(ThermalError)` for runtime inputs; `ThermalRangeWarning(UserWarning)` for temperatures outside a
declared material range (design 5.4: reported, not silently assumed).

`SurfaceRecord` (frozen): `surface_id: str`, `node_id: "S" | "R"`, `area_m2 > 0`, `normal_body` unit vector shape (3,)
(read-only array, |norm - 1| <= 1e-9), `absorptivity` in [0, 1], `emissivity` in [0, 1].

`ThermalParameters` (frozen; arrays read-only; mappings wrapped in `types.MappingProxyType`):
- `C_J_K` shape (6,) in NODE_ORDER, finite and > 0.
- `R_K_W` shape (5,) in PATH_ORDER, finite and > 0.
- `surfaces: tuple[SurfaceRecord, ...]` in asset surface order; only nodes S and R; unique `surface_id`.
- `instance_map`: `{"nodes": {node_id: tuple[instance_id, ...]} for all six nodes, "ports": {"P_pv_W": "SolarArray01",
  "P_load_W": "Compute01", "Q_B_W": "Battery01", "Q_D_W": "PDU01"}}` with each port instance inside the right node.
- `provenance`: mapping with at least
  `node_order` (must equal NODE_ORDER), `path_order` (must equal PATH_ORDER),
  `units` (must equal `{"C_J_K": "J/K", "R_K_W": "K/W", "area_m2": "m^2", "temperature": "K"}`),
  `capacitance` (per node: value and the material portions with instance, material id, mass, specific heat, source),
  `resistance` (per path: value, method `"conduction_plus_contact"` or `"equivalent_total"`, inputs, source),
  `assets` (per instance: asset_id, asset_version), `overrides_applied` (list of target, field, old, new, source),
  `temperature_range_K` (per node: (min, max), the declared applicability range of its constants).
- Construction checks dimensions, finiteness, positivity, orders, units, surface rules and the port map; a wrong order
  or unit raises `ThermalConfigurationError`.

`ThermalState` (frozen): `run_id: str` (non-empty), `time_s: float` (finite), `temperature_K` shape (6,) in NODE_ORDER,
finite and > 0, read-only.

`ThermalInputs` (frozen): `run_id`, `time_s`, `environment` (the mapping returned by `prepare_surface_environment`,
whose `run_id` and `time_s` must equal the inputs'), `P_pv_W`, `P_load_W`, `Q_B_W`, `Q_D_W` (finite floats; `Q_B_W` keeps
its sign). Sign limits of the other three are checked in `thermal_derivative` (design 5.6).

`ThermalEvaluation` (frozen, arrays read-only): `run_id`, `time_s`, `dT_dt_K_s` (6,), `q_W` (5,), `Q_env_W` (2,),
`Q_emit_W` (2,), `T_B_K = temperature_K[3]`, `T_J_K = temperature_K[1]` (copies of the input state, not new states).

## thermal/parameters.py

`assemble_thermal_parameters(components, connections, overrides) -> ThermalParameters` (design 4.5 T5, 5.2):
- `components`: sequence of mappings
  `{"instance_id", "node_id", "asset_id", "asset_version", "materials": [{"material_id", "mass_kg", "cp_J_kgK", "source"}],
    "surfaces": [{"surface_id", "area_m2", "normal_body", "absorptivity", "emissivity", "source"}],
    "temperature_range_K": [min, max], "ports": [port names this instance supplies]}`.
  Only D is a shared temperature extent (design table 1 and 3.2): Controller01 and PDU01 both map to D, every other
  node holds exactly one instance. A node must have at least one material portion.
- `connections`: one mapping per path, either
  `{"path", "length_m", "conductivity_W_mK", "area_m2", "contact_resistance_K_W", "source"}` (R = l/(k A) + R_contact) or
  `{"path", "equivalent_total_resistance_K_W", "includes_contact": bool, "contact_resistance_K_W" (required if and only
  if `includes_contact` is false), "source"}` (R = the total when `includes_contact` is true; R = the total +
  `contact_resistance_K_W` when it is false, and a missing contact resistance is an error, never assumed zero; giving
  `contact_resistance_K_W` with `includes_contact` true is the double-counting error of design 4.5).
- `overrides`: `{"components": {instance_id: {"materials": {material_id: {field: value}}, "surfaces": {surface_id:
  {field: value}}, "temperature_range_K": [..]}}, "connections": {path: {field: value}}, "source": str}`; explicit
  overrides take precedence over asset values and are listed in `provenance["overrides_applied"]`.
- Checks: mass, specific heat, length, conductivity, area finite and > 0; contact resistance finite and >= 0; one
  material portion belongs to one component (duplicate `material_id` anywhere is an error); duplicate `surface_id`;
  surfaces only on S and R; every one of the five paths defined exactly once; unknown paths; optical properties in [0, 1];
  normals unit length. Every error names the offending record. The function creates no operating temperature.

## thermal/environment.py

`prepare_surface_environment(orbit_input, earth_flux, parameters) -> dict` (design 5.3, 6.1):
- `orbit_input`: mapping with `run_id`, `time_s`, `epoch` (aware UTC datetime), `position_m` (3,), `sun_position_m` (3,,
  Earth to Sun), `frame` (only `"GCRS"` is accepted; `"TEME"` and others are rejected because relabelling is not a frame
  transformation), `quaternion_xyzw` (4,, active body-to-GCRS rotation, SciPy xyzw convention, unit within 1e-9),
  `G_W_m2 >= 0` (already includes eclipse; it is passed through and never multiplied by an eclipse factor again).
- `earth_flux`: mapping with `run_id`, `time_s`, `surface_ids`, `albedo_W_m2`, `infrared_W_m2` for exactly the surfaces of
  `parameters.surfaces` in the same order; mismatch, missing record or field, negative values, or a different run or
  time is rejected.
- Sun direction = normalize(sun_position_m - position_m); each `normal_body` is rotated by the quaternion; `cos_incidence`
  is the dot product (negative for surfaces facing away; clipping happens in T4).
- Returns `{"run_id", "time_s", "surface_ids": tuple, "G_W_m2": float, "cos_incidence", "albedo_W_m2", "infrared_W_m2"}`
  with read-only arrays in asset surface order.

`calculate_surface_heat(state, environment, parameters) -> dict` (design 4.4 T4, 5.4):
- per surface `g_sun = G * max(0, cos)`; `Q_env,i = sum A [alpha (g_sun + g_alb) + eps g_IR]`;
  `Q_emit,i = sum eps sigma A T_i^4` with `T_i` the owning node temperature; summed for S and R.
- Returns `{"run_id", "time_s", "Q_env_W" (2,), "Q_emit_W" (2,), "absorbed_solar_S_W", "range_warnings": tuple[str]}`
  where `absorbed_solar_S_W = sum over S surfaces of A alpha g_sun` (direct sunlight only).
- Run and time must agree; temperatures finite and > 0; irradiances >= 0. A temperature of S or R outside
  `provenance["temperature_range_K"]` is listed in `range_warnings` and emitted as `ThermalRangeWarning`.

## thermal/model.py

`calculate_heat_flows(state, parameters) -> dict` (design 4.2 T2, 5.5): returns `{"run_id", "time_s", "q_W"}` in
PATH_ORDER; each path evaluated once; errors for missing nodes, wrong array shape or order, non-positive resistance,
non-finite inputs. No state update.

`thermal_derivative(state, inputs, parameters) -> ThermalEvaluation` (design 4.1 T1, 4.3 T3, 5.6):
- check run and time of state, inputs and environment; `P_pv_W`, `P_load_W`, `Q_D_W` >= 0; `P_pv_W <=
  absorbed_solar_S_W` (relative tolerance 1e-12); call `calculate_surface_heat` and `calculate_heat_flows`;
- T3: `C_S dT_S = Q_env,S - P_pv - q_SR - Q_emit,S`; `C_J dT_J = P_load - q_JC`; `C_C dT_C = q_JC - q_CR`;
  `C_B dT_B = Q_B - q_BR`; `C_D dT_D = Q_D - q_DR`; `C_R dT_R = q_SR + q_CR + q_BR + q_DR + Q_env,R - Q_emit,R`;
- does not repair powers, does not decide load restart, adds no throttling rule; temperatures of any node outside its
  declared range raise `ThermalRangeWarning`.

## sdtwin_sim/earth_flux.py

`earth_flux_record(run_id, time_s, position_m, sun_position_m, quaternion_xyzw, surfaces, *, albedo, olr_W_m2,
solar_constant_W_m2, earth_radius_m=6378137.0, resolution=(240, 360)) -> dict` returning the `earth_flux` mapping above.
Helpers `earth_view_factor(position_m, normal_gcrs)` and `albedo_factor(position_m, normal_gcrs, sun_dir)`: numerical
integration over the visible spherical cap of a Lambertian Earth; infrared irradiance = `olr * F`, albedo irradiance =
`albedo * solar_constant * F_alb` where `F_alb` weights each Earth element by max(0, cos of its solar zenith angle).
Nadir plate check: F = (R / r)^2.

## sdtwin_sim/power_stand_in.py

A stand-in for the Power module, written from `Power/SDTwin_Power_Design_Report_CN.docx` (public names of its table 4,
appendix A; equations P1 to P11; valid and event_required semantics of its 5.1 and 5.5; apply_power_event of 5.6). Its
battery parameters are illustrative test values recorded in its provenance as such. Public names: `PowerParameters`,
`PowerEnvironment`, `PowerInputs`, `PowerState`, `SolarPowerResult`, `BatteryResponse`, `PowerResult`, `PowerEvent`,
`load_power_parameters`, `battery_response`, `solar_power`, `solve_power_allocation`, `apply_power_event`, plus
`example_power_parameters()` and a `CALL_STATS` counter (solve calls, battery evaluations) for test diagnostics.

## sdtwin_sim/coupled.py

`run_coupled(...)` integrates the six temperatures (and, with Power, the two lithium fractions) as one state vector using
SciPy `OdeSolver` classes (`RK45` by default, `Radau` allowed), splitting at eclipse boundaries, load commands and located
Power events; it never averages across a boundary, stores only accepted states, samples outputs on the accepted solution
at a fixed output step independent of the internal step, handles `valid=False` (report and stop) and `event_required`
(locate the boundary within `event_time_tol_s`, accept it, apply the event, recompute at the same instant; only a
confirmed `supply_shortfall` has a protection rule, any other boundary decision such as `device_boundary` stops the
run at the last accepted state inside the bound with a `device_boundary` record), and returns an
archive with run_id, UTC epoch, time_s, node and path order, temperatures, the four Power ports, heat flows, Q_env and
Q_emit, lithium fractions, events, solver settings, parameter provenance and step statistics (accepted steps, rejected
steps, function evaluations, Power calls). Thermal-only runs take `prescribed_ports(time_s) -> dict` instead of Power.
The coupled procedure never calls Orbit's `power_considering_thermal` and never writes a temperature from anywhere but
the thermal state.

## sdtwin_sim/scene.py

Reads SimReady asset definitions (`asset_id`, `asset_version`, `geometry_uri` to a USD file, physical capabilities
`domain`, `model_id`, `parameter_set`, parameter evidence `ports`, `provenance`) and a scene record (`instances` with
`instance_id`, `asset_ref`; configuration `parameter_overrides`, `initial_state`, `connections`), places instances under
`/World/Sat01/<instance_id>`, resolves physical sizes from USD extents times `metersPerUnit` (display transforms such as a
scale op never change physical sizes), maps `model_id` through a fixed registry (unregistered ids are rejected; nothing
from USD is executed), and returns the `components`, `connections` and `overrides` for `assemble_thermal_parameters`
plus the initial `ThermalState` inputs. A scene that puts a second instance on S, J, C, B or R, or two instances of
one asset on any node, is rejected (one temperature per node, design table 1); two satellites built from the same
assets are separate scenes with separate run ids, states and archives.

## Test evidence

Each test module records its checks through the `case_record` fixture of `tests/conftest.py`, which writes
`tests/results/<CASE_ID>.json`:

```
{"case_id": "PA-001", "status": "pass" | "fail" | "partial" | "not_run",
 "checks": [{"name": str, "expected": str, "actual": str, "passed": bool}],
 "metrics": {...}, "summary_cn": str, "anomalies_cn": str,
 "environment": {"python": ..., "numpy": ..., "scipy": ..., "astropy": ...}}
```

`summary_cn` and `anomalies_cn` are Chinese sentences that follow the report rules: no brackets of any kind, no dashes,
no question forms, no invented words, negative numbers written with U+2212.

## Verification and report reproduction, 2026-10-06

The 16 report cases contain 117 pytest functions. The evidence fixture records collection and completion counts,
UTC timestamps and source SHA-256 values. It writes a case after its last function so dependent cases read the
current result. Setup errors, incomplete execution and missing summaries cannot silently become a pass.

From `Thermal`, run the scientific tests with the project environment:

```powershell
$env:PYTHONUTF8 = '1'
.venv/Scripts/python.exe -m pytest tests -q *> tests/results/pytest_verified_run.txt
.venv/Scripts/python.exe -m pytest tests/test_en_003_earth_flux.py -q *> tests/results/pytest_en003_final.txt
```

The second command refreshes EN-003 after COMSOL load refinement. The expensive reference experiments are
`tests/data/en_003/fe_refine_ladder.py`, using the repository backend Python environment with MPh and COMSOL 6.3.
The solved ISS models provide the original 2 x 6 loads. At the same 16 instants, from 10920 s to 16320 s in 360 s
steps, the script recomputes loads at 4 x 12 and 8 x 24; hot75 also repeats 2 x 6. The requested COMSOL range has
an upper bound of 16560 s, which is not a multiple of the interval from the start and is not an output instant.
COMSOL also saves paired pre/post-eclipse event samples in beta-zero cases. The raw exports preserve these
extra points. `ladder_compare.py` selects the 16 requested instants by exact-time matching within 1e-6 s, with
no interpolation or relative-time tolerance; extra event points do not enter the arithmetic sample means.
The result records retain each level's raw sample count and excluded event times.
These comparisons use arithmetic sample means rather than an exact-orbit time average. The experiment does not establish
convergence of the complete temperature solution. `ladder_compare.py` reports the three sample means and peaks;
Richardson estimates are conditional on decreasing changes of the same sign, not proof of asymptotic convergence.

EN-003 additionally uses an independent adaptive geocentric reference in `earth_reference.py`. It splits the
azimuth integral at visibility and illumination boundaries before radial quadrature. This is test reference code;
the production earth_flux resolution remains 240 x 360. A uniform relative criterion remains 1% even for weak
positive flux. Numerical zero alone receives an absolute tolerance of 1e-12 W/m2.

To build the reports, use a Python environment containing python-docx and matplotlib, then Microsoft Word for
TOC update and PDF export. The local bundled document runtime supplies these packages.

```powershell
python test_report/reviewed_results.py
python test_report/figures_results.py
python test_report/build_test_report.py cn
python test_report/build_test_report.py en
powershell -NoProfile -ExecutionPolicy Bypass -File test_report/finalize.ps1 -Name SDTwin_Thermal_Test_Report_CN
powershell -NoProfile -ExecutionPolicy Bypass -File test_report/finalize.ps1 -Name SDTwin_Thermal_Test_Report_EN
python test_report/qa/render_review.py SDTwin_Thermal_Test_Report_CN.pdf SDTwin_Thermal_Test_Report_EN.pdf
python test_report/qa/audit_fe001_plot.py
python test_report/qa/audit_reports.py
.venv/Scripts/python.exe test_report/evidence_manifest.py
```

Both languages use the same measured values and case verdicts. `reviewed_results.py` binds concise report text to
each raw result by SHA-256; the builder refuses stale prose. Raw checks and detailed time series stay in
`tests/results`. `verification_manifest.json` distinguishes completed execution from passing acceptance and
binds the final source, inputs, evidence and four report files. It rejects missing refinement cases, incomplete
functions, infrastructure errors or results from a different core implementation. Final page images are inspected
after Word export. The existing draft and pre-handoff sources are preserved under `test_report/qa`.

Report revision 2.1 adds a scene and input explanation for every test project, 11 measured-input/reference/result
tables for the non-FE projects and a whole-satellite input table. The five benchmark projects retain their detailed
comparison tables. `case_evidence.py` supplies the bilingual explanations and reads measured values from case records;
`audit_reports.py` checks scenario and result-table coverage and numerical agreement in both languages.

The same revision now defines the physical meaning before listing input values for all 16 projects. Chapter 2
tabulates the ISS cold/mean/hot radiation inputs, defines beta angle, and explains why the beta-zero cases have
about 36.1 min eclipse while beta 75 remains sunlit. These are prescribed environments, not air temperatures or
rankings of every component's computed temperature. Per-project context explains the test object, heat path,
boundary conditions and terminology; the independent FE-004 and NI environments are kept distinct. Figure titles
show beta and eclipse status, and captions explain the physical scenario as well as the axes and acceptance window.
The content audit checks environment values and eclipse duration against the retained configuration and FE summaries.
Three solved ISS FE views are included: the nom0 whole-station field near orbital noon, the cold0 field near
mid-eclipse, and the hot75 radiator field near noon. The original COMSOL image fields are retained and the
original Plasma range (-80 to 80 degrees C) is reproduced with bilingual colour bars. Captions identify the
parts, environment, requested output phase, nearest-saved-solution convention and limits of colour-map reading.
The manifest binds the original three image files and rendering scripts as well as the report-ready figures.

FE-001 figure rows show the common-scale whole-orbit temperatures, local views around the largest difference,
and the signed module-minus-FE difference. All rows now use the exact FE output instants in the acceptance record,
with the same piecewise-linear sample connections. The earlier figure re-interpolated the 10 s module export at
two eclipse-event instants, differing from the test by up to 0.4832 K, although the reported maxima were unchanged.
`out/fe001_plot_data.json` retains the paired data. `qa/audit_fe001_plot.py` compares every FE point with its original
CSV and every residual with the test record, including the subtraction identity between plotted samples. This is
a report-figure correction; it does not change the experiment records, acceptance thresholds, or case verdicts.

The measured limitations must remain explicit: FE-001 meets the statistic criterion but fails simultaneous
temperature-curve comparison; EN-003 has weak-albedo relative-accuracy and original FE-load exceedances; FE-004
fails the whole-satellite temperature criterion. Passing formula and interface checks does not remove these
failures. FE-004's unallocated energy remainder includes several surfaces and cannot be wholly assigned to J or
used as a validated temperature correction. Power battery values remain illustrative test parameters.

The scene examples were corrected before execution to conserve the test battery lithium inventory. Runtime code
uses the supplied fractions unchanged. Power's validation temperature is set to the actual thermal initial value,
including hot-start probes; all runtime battery temperatures come from Thermal. Effective density and derived mass
after a scene override are retained in parameter provenance.
