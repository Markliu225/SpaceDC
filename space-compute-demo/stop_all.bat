@echo off
REM ============================================================
REM   Stop all space-compute-demo services.
REM ============================================================

echo  Stopping Kit (kit.exe)...
taskkill /F /IM kit.exe >nul 2>&1

echo  Stopping any Python processes using ports 8001 ...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8001.*LISTENING"') do (
    echo   killing PID %%p
    taskkill /F /PID %%p >nul 2>&1
)

echo  Stopping any Node processes using port 5173 ...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5173.*LISTENING"') do (
    echo   killing PID %%p
    taskkill /F /PID %%p >nul 2>&1
)

echo  Done. All services stopped.
pause
