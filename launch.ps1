<#
.SYNOPSIS
    SpaceDC Digital Twin — One-click Omniverse Launcher
.DESCRIPTION
    Syncs extension source files and launches the Kit-based SpaceDC editor.
    Run: .\launch.ps1
          .\launch.ps1 -NoBuild        # skip build check
          .\launch.ps1 -SkipSync       # don't copy files
          .\launch.ps1 -Verbose        # show xcopy details
#>
param(
    [switch]$NoBuild,
    [switch]$SkipSync
)

$ErrorActionPreference = "Stop"

# ── Paths ──────────────────────────────────────────────────
$SpaceDCRoot  = $PSScriptRoot
$KitRoot      = "C:\Workspace\kit-app-template"
$ExtSrc       = Join-Path $SpaceDCRoot "exts\spacedc.digital_twin"
$ExtDstSource = Join-Path $KitRoot     "source\extensions\spacedc.digital_twin"
$ExtDstBuild  = Join-Path $KitRoot     "_build\windows-x86_64\release\exts\spacedc.digital_twin"
$KitBat       = Join-Path $KitRoot     "_build\windows-x86_64\release\spacedc.editor.bat"

# ── Banner ─────────────────────────────────────────────────
Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║   SpaceDC Digital Twin — NVIDIA Omniverse Launcher  ║" -ForegroundColor Cyan
Write-Host "  ║   ORBITAL DC-1 · 1MW-class Space Data Center       ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Pre-flight checks ─────────────────────────────────────
if (-not (Test-Path $KitRoot)) {
    Write-Host "  [ERROR] kit-app-template not found at: $KitRoot" -ForegroundColor Red
    Write-Host "          Clone it first:" -ForegroundColor Yellow
    Write-Host "          git clone https://github.com/NVIDIA-Omniverse/kit-app-template.git `"$KitRoot`"" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $KitBat)) {
    if ($NoBuild) {
        Write-Host "  [ERROR] Build not found and -NoBuild specified." -ForegroundColor Red
        exit 1
    }
    Write-Host "  [BUILD] First-time build required. This may take several minutes..." -ForegroundColor Yellow
    Push-Location $KitRoot
    & .\build.bat
    Pop-Location
    if (-not (Test-Path $KitBat)) {
        Write-Host "  [ERROR] Build failed." -ForegroundColor Red
        exit 1
    }
}

if (-not (Test-Path $ExtSrc)) {
    Write-Host "  [ERROR] Extension source not found: $ExtSrc" -ForegroundColor Red
    exit 1
}

# ── Step 1: Kill old Kit ───────────────────────────────────
Write-Host "  [1/3] " -ForegroundColor Green -NoNewline
Write-Host "Stopping previous Kit instances..."
$killed = Get-Process -Name "kit" -ErrorAction SilentlyContinue
if ($killed) {
    Stop-Process -Name "kit" -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    Write-Host "        Killed $($killed.Count) process(es)." -ForegroundColor DarkGray
} else {
    Write-Host "        No running Kit found." -ForegroundColor DarkGray
}

# ── Step 2: Sync files ────────────────────────────────────
Write-Host "  [2/3] " -ForegroundColor Green -NoNewline
Write-Host "Syncing extension files..."

if ($SkipSync) {
    Write-Host "        Skipped (-SkipSync)." -ForegroundColor DarkGray
} else {
    if (-not (Test-Path $ExtDstSource)) {
        New-Item -ItemType Directory -Path $ExtDstSource -Force | Out-Null
    }
    # Copy entire extension (Python code, config, data/textures) to source dir
    Copy-Item -Path "$ExtSrc\*" -Destination $ExtDstSource -Recurse -Force

    # Also copy data/textures to build dir (not covered by junction)
    $dataSrc = Join-Path $ExtSrc "data"
    $dataDst = Join-Path $ExtDstBuild "data"
    if (Test-Path $dataSrc) {
        if (-not (Test-Path $dataDst)) {
            New-Item -ItemType Directory -Path $dataDst -Force | Out-Null
        }
        Copy-Item -Path "$dataSrc\*" -Destination $dataDst -Recurse -Force
        Write-Host "        Textures synced to build dir." -ForegroundColor DarkGray
    }

    # Count synced files
    $count = (Get-ChildItem -Path $ExtSrc -Recurse -File).Count
    Write-Host "        $count files synced OK." -ForegroundColor DarkGray
}

# ── Step 3: Launch ─────────────────────────────────────────
Write-Host "  [3/3] " -ForegroundColor Green -NoNewline
Write-Host "Launching SpaceDC Digital Twin..."
Write-Host ""
Write-Host "        Kit:       $KitBat" -ForegroundColor DarkGray
Write-Host "        Extension: spacedc.digital_twin" -ForegroundColor DarkGray
Write-Host ""

Push-Location $KitRoot
Start-Process -FilePath $KitBat -ArgumentList "--enable", "spacedc.digital_twin"
Pop-Location

Write-Host "  ✅ SpaceDC launched! Viewport will appear in ~15 seconds." -ForegroundColor Green
Write-Host ""
