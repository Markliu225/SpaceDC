<#
.SYNOPSIS
    Launch space.demo.viewer_streaming with SPACE_DEMO_USD_ROOT pointing at the
    repo's canonical usd/ directory, so space.demo.core can open root.usda.

.DESCRIPTION
    Before launching, copies every authored extension's `space/` package from
    ov_app/exts/<ext>/ over to kit-usd-viewer-template/source/extensions/<ext>/.
    The release build's `space/` is a junction back to source, so writing to
    source is enough — Kit picks up the latest Python at startup. No `repo.bat
    build` needed because Python is interpreted at runtime.

    Without this sync, edits to ov_app/exts/*/space/.../*.py never reach the
    Kit instance and the user runs whatever was last manually synced — which
    is how a freshly-edited Earth-rotation driver can silently fail to load.
#>
param(
    [switch]$Base,         # launch the non-streaming viewer instead
    [string]$Focus = "",   # "overview" (default) | "satellite" close-up
    [switch]$Headless,     # pass --no-window (no local Kit UI, stream-only)
    [switch]$SkipSync      # opt out of the pre-launch ext sync (debug only)
)

$ErrorActionPreference = 'Stop'
$OvApp     = $PSScriptRoot
$Repo      = Split-Path $OvApp -Parent
$KitRoot   = 'C:\Workspace\kit-usd-viewer-template'
$KitBuild  = Join-Path $KitRoot '_build\windows-x86_64\release'
$KitSrcExt = Join-Path $KitRoot 'source\extensions'
$KitSrcApp = Join-Path $KitRoot 'source\apps'

$env:SPACE_DEMO_USD_ROOT = Join-Path $Repo 'usd'
if ($Focus) { $env:SPACE_DEMO_FOCUS = $Focus } else { $env:SPACE_DEMO_FOCUS = $null }
Write-Host "SPACE_DEMO_USD_ROOT = $env:SPACE_DEMO_USD_ROOT"
Write-Host "SPACE_DEMO_FOCUS    = $env:SPACE_DEMO_FOCUS"

# --- Sync authored extensions + apps into the Kit source tree ----------------
if (-not $SkipSync) {
    $authoredExts = @(
        'space.demo.core',
        'space.demo.scene',
        'space.demo.timeline',
        'space.demo.selection',
        'space.demo.task_maritime',
        'space.demo.camera',
        'space.demo.messaging',
        'space.demo.setup'
    )
    Write-Host "[sync] $(Get-Date -Format HH:mm:ss) syncing extensions to $KitSrcExt"
    foreach ($ext in $authoredExts) {
        $src = Join-Path $OvApp "exts\$ext\space"
        $dst = Join-Path $KitSrcExt "$ext\space"
        if (-not (Test-Path $src)) { continue }
        if (-not (Test-Path (Split-Path $dst -Parent))) { continue }
        # robocopy is faster + safer than cp for "mirror this tree"; /XD __pycache__
        # avoids dragging stale .pyc files (which can mask new code).
        $null = robocopy $src $dst /MIR /XD __pycache__ /NFL /NDL /NJH /NJS /NC /NS /NP
        Write-Host "  [ext] $ext"
    }
    # .kit app files
    $appsSrc = Join-Path $OvApp 'apps'
    if (Test-Path $appsSrc) {
        Get-ChildItem -Path $appsSrc -Filter '*.kit' | ForEach-Object {
            $dst = Join-Path $KitSrcApp $_.Name
            Copy-Item $_.FullName $dst -Force
            Write-Host "  [app] $($_.Name)"
        }
    }
}

# --- Launch -------------------------------------------------------------------
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
