@echo off
REM ============================================================
REM   Same as start_all.bat but with Kit focused on satellite
REM   close-up (shows component assembly instead of Earth view).
REM ============================================================

setlocal
pushd "%~dp0"

echo  Killing existing Kit...
taskkill /F /IM kit.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo  Backend :8001 ...
start "SpaceDC Backend :8001" cmd /k "cd /d "%~dp0backend" && .venv\Scripts\python.exe -m uvicorn app:app --port 8001 --log-level info"

echo  Web :5173 ...
start "SpaceDC Web :5173" cmd /k "cd /d "%~dp0web" && npm run dev -- --port 5173 --strictPort"

echo  Kit :49100 (satellite close-up)...
start "SpaceDC Kit :49100 [satellite]" powershell -NoExit -ExecutionPolicy Bypass -File "%~dp0ov_app\launch_kit.ps1" -Focus satellite

echo  Waiting 20s...
timeout /t 20 /nobreak >nul
start "" http://localhost:5173

popd
endlocal
pause
