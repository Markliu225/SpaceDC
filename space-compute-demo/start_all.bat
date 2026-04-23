@echo off
REM ============================================================
REM   SpaceDC - space-compute-demo / one-click launcher
REM   Double-click to start backend, web, and Kit streaming.
REM   Each service opens in its own window. Close that window
REM   to stop the corresponding service.
REM ============================================================

setlocal
pushd "%~dp0"

echo.
echo  [1/5] Killing any existing Kit process...
taskkill /F /IM kit.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo  [2/5] Starting BACKEND on http://localhost:8001 ...
start "SpaceDC Backend :8001" cmd /k "cd /d "%~dp0backend" && .venv\Scripts\python.exe -m uvicorn app:app --port 8001 --log-level info"

echo  [3/5] Starting WEB dev server on http://localhost:5173 ...
start "SpaceDC Web :5173" cmd /k "cd /d "%~dp0web" && npm run dev -- --port 5173 --strictPort"

echo  [4/5] Starting Omniverse KIT streaming on 127.0.0.1:49100 ...
start "SpaceDC Kit :49100" powershell -NoExit -ExecutionPolicy Bypass -File "%~dp0ov_app\launch_kit.ps1"

echo  [5/5] Waiting 20 seconds for Kit to finish initializing, then opening browser...
timeout /t 20 /nobreak >nul

echo  Opening http://localhost:5173 in default browser...
start "" http://localhost:5173

echo.
echo  All services launched. Three windows are now running:
echo    - SpaceDC Backend :8001
echo    - SpaceDC Web :5173
echo    - SpaceDC Kit :49100
echo.
echo  To stop everything, close those three windows
echo  (or double-click stop_all.bat).
echo.

popd
endlocal
pause
