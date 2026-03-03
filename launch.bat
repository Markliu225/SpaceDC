@echo off
chcp 65001 >nul 2>&1
title SpaceDC Digital Twin — Launcher
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║   SpaceDC Digital Twin — NVIDIA Omniverse Launcher  ║
echo  ║   ORBITAL DC-1 · 1MW-class Space Data Center       ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

:: ── 路径配置 ──────────────────────────────────────────────
set "SPACEDC_ROOT=%~dp0"
set "KIT_ROOT=C:\Workspace\kit-app-template"
set "EXT_SRC=%SPACEDC_ROOT%exts\spacedc.digital_twin"
set "EXT_DST=%KIT_ROOT%\source\extensions\spacedc.digital_twin"
set "EXT_BUILD=%KIT_ROOT%\_build\windows-x86_64\release\exts\spacedc.digital_twin"
set "KIT_BAT=%KIT_ROOT%\_build\windows-x86_64\release\spacedc.editor.bat"

:: ── 检查 kit-app-template 是否存在 ─────────────────────────
if not exist "%KIT_ROOT%" (
    echo [ERROR] kit-app-template not found at: %KIT_ROOT%
    echo         Please clone it first:
    echo         git clone https://github.com/NVIDIA-Omniverse/kit-app-template.git "%KIT_ROOT%"
    pause
    exit /b 1
)

:: ── 检查构建产物是否存在 ───────────────────────────────────
if not exist "%KIT_BAT%" (
    echo [ERROR] Build not found. Running first-time build...
    echo         This may take several minutes.
    echo.
    pushd "%KIT_ROOT%"
    call build.bat
    popd
    if not exist "%KIT_BAT%" (
        echo [ERROR] Build failed. Please check errors above.
        pause
        exit /b 1
    )
)

:: ── 终止旧的 Kit 进程 ─────────────────────────────────────
echo [1/3] Stopping previous Kit instances...
taskkill /F /IM kit.exe >nul 2>&1
timeout /t 1 /nobreak >nul

:: ── 同步源文件到 kit-app-template ─────────────────────────
echo [2/3] Syncing extension files...
if not exist "%EXT_DST%" mkdir "%EXT_DST%"
xcopy "%EXT_SRC%\*" "%EXT_DST%\" /E /Y /Q >nul
if errorlevel 1 (
    echo [ERROR] File sync failed!
    pause
    exit /b 1
)
:: Also sync data/textures to build dir (not covered by junction)
if exist "%EXT_SRC%\data" (
    if not exist "%EXT_BUILD%\data" mkdir "%EXT_BUILD%\data"
    xcopy "%EXT_SRC%\data\*" "%EXT_BUILD%\data\" /E /Y /Q >nul
    echo       Textures synced to build dir.
)
echo       Extension synced OK.

:: ── 启动 SpaceDC Editor ───────────────────────────────────
echo [3/3] Launching SpaceDC Digital Twin...
echo.
echo  → Kit executable: %KIT_BAT%
echo  → Extension: spacedc.digital_twin
echo.
echo  Waiting for RTX viewport... (this may take 10-20 seconds)
echo  ─────────────────────────────────────────────────────────
echo.

pushd "%KIT_ROOT%"
start "" "%KIT_BAT%" --enable spacedc.digital_twin
popd

echo  SpaceDC launched! You can close this window.
echo.
timeout /t 5 /nobreak >nul
