<#
.SYNOPSIS
    Syncs ov_app/{apps,exts/space.demo.*} into the kit-usd-viewer-template source tree,
    so `repo.bat build` can pick them up.

.DESCRIPTION
    Canonical source lives in space-compute-demo/ov_app/. The Kit build requires files
    to be in kit-usd-viewer-template/source/apps and /source/extensions. This script
    copies (not symlinks — Windows junctions are flaky) our authored exts into the
    Kit source tree. Setup + messaging exts that were rendered by `repo template new`
    into Kit source/ are copied back here by a one-time bootstrap.

    Run: .\sync_to_kit.ps1
         .\sync_to_kit.ps1 -Verbose
#>
param(
    [switch]$NoBuild,
    [switch]$Launch
)

$ErrorActionPreference = 'Stop'
$OvAppRoot = $PSScriptRoot
$SpaceDCRoot = Split-Path $OvAppRoot -Parent
$KitRoot   = 'C:\Workspace\kit-usd-viewer-template'
$KitSrcApps = Join-Path $KitRoot 'source\apps'
$KitSrcExts = Join-Path $KitRoot 'source\extensions'

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

Write-Host ''
Write-Host '  [sync_to_kit]' -ForegroundColor Cyan
Write-Host "  ov_app: $OvAppRoot"
Write-Host "  kit  : $KitRoot"
Write-Host ''

if (-not (Test-Path $KitRoot)) {
    Write-Host "  [ERROR] Kit template missing at $KitRoot" -ForegroundColor Red
    exit 1
}

# 1) Sync app .kit file (if present)
$appsSrc = Join-Path $OvAppRoot 'apps'
if (Test-Path $appsSrc) {
    $kitFiles = Get-ChildItem -Path $appsSrc -Filter '*.kit' -ErrorAction SilentlyContinue
    foreach ($f in $kitFiles) {
        $dst = Join-Path $KitSrcApps $f.Name
        Copy-Item $f.FullName $dst -Force
        Write-Host "  [app]  $($f.Name)" -ForegroundColor Green
    }
}

# 2) Sync authored extensions (one-way: ov_app -> kit source)
foreach ($ext in $authoredExts) {
    $src = Join-Path $OvAppRoot "exts\$ext"
    $dst = Join-Path $KitSrcExts $ext
    if (-not (Test-Path $src)) { continue }
    if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
    Copy-Item $src $dst -Recurse -Force
    Write-Host "  [ext]  $ext" -ForegroundColor Green
}

# 3) Set stage env vars so space.demo.core knows where usd/ lives
$env:SPACE_DEMO_USD_ROOT = Join-Path $SpaceDCRoot 'usd'

# 4) Build
if (-not $NoBuild) {
    Write-Host ''
    Write-Host '  [build] repo.bat build' -ForegroundColor Cyan
    Push-Location $KitRoot
    try {
        & .\repo.bat build
        if ($LASTEXITCODE -ne 0) { throw "Kit build failed ($LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
}

# 5) Launch
if ($Launch) {
    $bat = Join-Path $KitRoot '_build\windows-x86_64\release\space.demo.viewer_streaming.kit.bat'
    if (-not (Test-Path $bat)) {
        $bat = Join-Path $KitRoot '_build\windows-x86_64\release\space.demo.viewer.kit.bat'
    }
    if (Test-Path $bat) {
        Write-Host "  [launch] $bat" -ForegroundColor Cyan
        Start-Process -FilePath $bat -WorkingDirectory $KitRoot
    } else {
        Write-Host "  [ERROR] No launcher bat found - has repo template new run? Did build succeed?" -ForegroundColor Red
        exit 1
    }
}

Write-Host ''
Write-Host '  sync complete.' -ForegroundColor Green
