@echo off
REM ============================================================
REM   SpaceDC launcher — WINDOWED Kit variant.
REM   Same as start_all.bat but Kit opens its local viewport
REM   window (useful for debugging in the Omniverse UI).
REM   NOTE: keep that window RESTORED (not minimized) while using
REM   the webpage — a minimized Kit window throttles rendering
REM   and the web stream turns choppy. The .kit config sets
REM   renderer.skipWhileMinimized=false as a safety net, but the
REM   headless start_all.bat is the smoothest web experience.
REM ============================================================
taskkill /F /IM hub.exe >nul 2>&1
setlocal
pushd "%~dp0"

echo.
echo  [1/6] Killing any existing Kit process...
taskkill /F /IM kit.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo  [2/6] Freeing ports 8001 and 5173 (stale backend / dev-server instances)...
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8001" ^| findstr "LISTENING"') do taskkill /F /PID %%p >nul 2>&1
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":5173" ^| findstr "LISTENING"') do taskkill /F /PID %%p >nul 2>&1
timeout /t 1 /nobreak >nul

echo  [3/6] Starting BACKEND on http://localhost:8001 ...
start "SpaceDC Backend :8001" cmd /k "cd /d "%~dp0backend" && .venv\Scripts\python.exe -m uvicorn app:app --port 8001 --log-level info"

echo  [4/6] Starting WEB dev server on http://localhost:5173 ...
start "SpaceDC Web :5173" cmd /k "cd /d "%~dp0web" && npm run dev -- --port 5173 --strictPort"

echo  [5/6] Starting Omniverse KIT streaming on 127.0.0.1:49100 (windowed) ...
start "SpaceDC Kit :49100" powershell -NoExit -ExecutionPolicy Bypass -File "%~dp0ov_app\launch_kit.ps1"

echo  [6/6] Waiting 20 seconds for Kit to finish initializing, then opening browser...
timeout /t 20 /nobreak >nul

echo  Opening http://localhost:5173 in default browser...
start "" http://localhost:5173

echo.
echo  All services launched. Three windows are now running:
echo    - SpaceDC Backend :8001
echo    - SpaceDC Web :5173
echo    - SpaceDC Kit :49100 (windowed - do not minimize)
echo.
echo  To stop everything, close those three windows
echo  (or double-click stop_all.bat).
echo.

popd
endlocal
pause
