# Power comparison test contract

The design reports remain the normative model description. The present executable
under test is `../Thermal/sdtwin_sim/power_stand_in.py`, explicitly a test implementation
with illustrative device parameters. This test project does not silently relabel it
as a production or experimentally calibrated Power module.

## Comparison framework

`verification/prepare.py` generates a versioned, hash-bound shared input suite. The
Python runner calls the existing Power API and integrates with SciPy DOP853. The
reference in `verification/matlab/power_reference.m` independently evaluates P1–P11;
`power_sfun.m` supplies continuous derivatives and outputs to the Simulink engine.
The saved `sdtwin_power_reference.slx` uses Simulink ode45. Neither side calls the
other side's equations or consumes the other side's outputs during simulation.

The reference is a custom Simulink implementation of the design equations. It is not
a built-in Simscape Battery model and does not provide empirical cell validation.
The scalar thermal feedback cases use one battery heat-capacity/resistance model,
not the complete six-node Thermal simulation.

## Cases

| Group | Cases | Purpose |
| --- | --- | --- |
| Solar | PV-001 | Eclipse, front and rear illumination, attitude and irradiance |
| Battery | BT-001 to BT-004 | OCV, temperature/current, signed heat, pack scaling |
| Allocation | PD-001 and PD-002 | Power allocation, efficiency and distribution loss |
| Limits | CT-001 to CT-003 | Charge curtailment, discharge shortfall, full SOC |
| Protection | PR-001 | Stop/start, loss latch, duplicate and trial commands |
| Invalid inputs | IV-001 | Temperature, identity, time, frame, Sun direction, state boundary |
| Dynamics | DY-001 to DY-007 | Sunlight, eclipse, demand, charge limits, restart, thermal feedback, three cycles |
| Numerics | NU-001 | Independent solver refinement |

All 20 cases have both simulation outputs, numerical metrics and physical acceptance
checks. Scheduled discontinuities preserve separate left and right limits at an
identical time. The residual figures use direct CSV subtraction without interpolation
across a boundary. Every plotted point is asserted against the saved difference CSV.

## Current results

All 20 cases were executed. All 20 pass the cross-implementation numerical criteria;
17 pass overall acceptance and 3 fail:

* CT-003: charging continues at the configured SOC = 1 endpoint, about −0.545 A/cell.
* DY-002: peak SOC is 1.0061529226631865 over one controlled orbit cycle.
* DY-007: peak SOC is 1.0420700453112586 over three controlled cycles.

Both implementations reproduce the issue. Existing allocation constraints enforce
current, voltage, and material fraction limits, but omit the usable SOC endpoint
`x_n_100 = 0.90`. Material validity permits `x_n` up to 0.95. This difference explains
why equal simulation results can still violate the full-charge design requirement.
No production/source-under-test fix or display clipping was performed in this run.

Input contract 1.0 was frozen before the first execution. Coverage review added
CT-003 and explicit SOC physical acceptance in 1.1 after overcharge was observed.
Original numerical tolerances were not relaxed; prior fixtures remain in
`verification/results/history/`.

## Reproduction and delivery

Run `powershell -NoProfile -ExecutionPolicy Bypass -File Power/verification/run_all.ps1`
from the repository root. Read `verification/results/summary.json`: an execution
success is not an acceptance pass. Raw CSVs, event logs and per-case JSON are retained.

Open `verification/matlab/sdtwin_power_reference.slx` in MATLAB to run the default
900-second sunlight case. Its load callback adds the reference code directory and
loads the shared fixture. Run `run_suite` for the complete test set.

The bilingual report generator is `verification/build_report.py`, executed with the
document runtime containing python-docx and matplotlib. Word exports are performed
with `verification/finalize.ps1`; PDF page images and document audits are retained in
`verification/qa/`. Final files are `SDTwin_Power_Test_Report_CN.docx/.pdf` and their
English counterparts.

Report revision 1.1 follows the retained Orbit test report: its cover, revision
history, contents, seven chapters, standard case-record fields, grouped test-project
numbering, and landscape summary. `verification/orbit_format.py` applies the format
to both languages. All 20 comparison figures and numerical evidence are retained;
the format revision does not change the frozen input suite or acceptance results.

The current scope excludes measured battery accuracy, switching waveforms, detailed
electrolyte transients, autonomous boundary localization during continuous depletion,
full six-node Thermal integration, and exhaustive SimReady asset-validation errors.
These are explicit scope limits, not reported as passed tests.
