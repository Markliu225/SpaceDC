$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location $root
try {
    $python = Join-Path $root 'Thermal/.venv/Scripts/python.exe'
    $matlab = 'C:/Program Files/MATLAB/R2026b/bin/matlab.exe'
    & $python Power/verification/prepare.py
    if ($LASTEXITCODE) { throw 'Input preparation failed' }
    & $python Power/verification/run_python.py
    if ($LASTEXITCODE) { throw 'Python execution failed' }
    & $matlab -batch "addpath('Power/verification/matlab'); run_suite"
    if ($LASTEXITCODE) { throw 'MATLAB execution failed' }
    & $python Power/verification/compare.py
    if ($LASTEXITCODE) { throw 'Comparison infrastructure failed' }
    Write-Output 'Read results/summary.json for acceptance verdicts, including retained failures.'
} finally { Pop-Location }
