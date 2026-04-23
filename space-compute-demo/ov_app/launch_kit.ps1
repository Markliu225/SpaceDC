<#
.SYNOPSIS
    Launch space.demo.viewer_streaming with SPACE_DEMO_USD_ROOT pointing at the
    repo's canonical usd/ directory, so space.demo.core can open root.usda.
#>
param(
    [switch]$Base,         # launch the non-streaming viewer instead
    [string]$Focus = "",   # "overview" (default) | "satellite" close-up
    [switch]$Headless      # pass --no-window (no local Kit UI, stream-only)
)

$ErrorActionPreference = 'Stop'
$OvApp     = $PSScriptRoot
$Repo      = Split-Path $OvApp -Parent
$KitBuild  = 'C:\Workspace\kit-usd-viewer-template\_build\windows-x86_64\release'

$env:SPACE_DEMO_USD_ROOT = Join-Path $Repo 'usd'
if ($Focus) { $env:SPACE_DEMO_FOCUS = $Focus } else { $env:SPACE_DEMO_FOCUS = $null }
Write-Host "SPACE_DEMO_USD_ROOT = $env:SPACE_DEMO_USD_ROOT"
Write-Host "SPACE_DEMO_FOCUS    = $env:SPACE_DEMO_FOCUS"

$target = if ($Base) { 'space.demo.viewer.kit.bat' } else { 'space.demo.viewer_streaming.kit.bat' }
$bat = Join-Path $KitBuild $target

if (-not (Test-Path $bat)) {
    Write-Host "[ERROR] Launcher not found: $bat" -ForegroundColor Red
    exit 1
}

$extraArgs = @()
if ($Headless -and -not $Base) {
    $extraArgs += '--no-window'
}

Write-Host "Launching: $bat $extraArgs"
& $bat @extraArgs
