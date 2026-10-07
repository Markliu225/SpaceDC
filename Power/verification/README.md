# Power model versus Simulink verification

This suite compares the repository's current Power equation implementation in
`Thermal/sdtwin_sim/power_stand_in.py` with an independently written MATLAB reference
executed by a saved Simulink model. The Python component remains explicitly a test
implementation, not a qualified production EPS or a measured battery.

The shared contract is the Power design report, equations P1–P11. Input fixtures and
device parameters are shared; neither implementation imports the other implementation's
outputs. MATLAB supplies independent cell equations, constrained current allocation and
protection transitions. Simulink owns the continuous integration through a Level 2
MATLAB S-function. Python uses SciPy DOP853. This is cross-implementation verification
under the same physics assumptions, not comparison against a factory Simscape battery
block and not experimental validation of a real cell.

The reference uses base Simulink because the installed MATLAB does not expose the
Simscape Battery or Electrical libraries. No model results are labeled as measurements.

## Execution

From the repository root:

```powershell
Thermal/.venv/Scripts/python.exe Power/verification/run_python.py
& 'C:/Program Files/MATLAB/R2026b/bin/matlab.exe' -batch "addpath('Power/verification/matlab'); run_suite"
Thermal/.venv/Scripts/python.exe Power/verification/compare.py
```

`prepare.py` defines all cases and freezes the tolerances before running either solver.
Shared input JSON, raw CSV, event logs and an input hash accompany every case. CSV
differences are evaluated only at identical timestamps and signal definitions. Scheduled
discontinuities are segment boundaries with separate left and right limits. No linear
interpolation is allowed across an event. Protection commands are processed at accepted
segment boundaries; continuous spontaneous depletion is listed separately if not covered.

Every case has a purpose, numerical inputs, expected behavior, comparison metrics,
fixed acceptance criteria and its own figure or table. Failed comparisons remain failed.
The report also records scope gaps, illustrative parameters and numerical convergence.

## Report format

Both reports use the retained Orbit test report as the formatting authority:
`Orbit/2. Test Report for Orbit Dynamics Module of SDCTwin  - 20260817.docx`.
`build_report.py` supplies evidence and figures; `orbit_format.py` clones the actual
reference document, case-record form and landscape summary. The seven chapters are
Overview, Test Content, Detailed Test Projects, Test Content Sufficiency Analysis,
Test Conditions and Requirements, Test Data, and Test Summary. Each of the 20 cases
has the standard 11-row record, a numerical input table, a comparison figure, an
error table, actual results and an anomaly verdict. The Word finalizer refreshes
the contents and page fields before PDF export. The format revision does not change
the frozen suite, results, tolerances, or the 17-pass / 3-fail acceptance count.
