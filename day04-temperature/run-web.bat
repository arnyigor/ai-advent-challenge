@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set PORT=8766
set URL=http://127.0.0.1:%PORT%/

echo ============================================
echo Day 04 Temperature - Web UI manual check
echo ============================================
echo.
echo URL: %URL%
echo.
echo Manual check:
echo   1. Click Start, or choose a Replay from the dropdown.
echo   2. On Live, each temperature column should fill progressively.
echo   3. Progress text should move from dash to N/3 done during the run.
echo   4. Open Analogies and Metrics; both tabs should render readable content.
echo   5. Press Ctrl+C in this window to stop the server.
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [FAIL] python was not found in PATH.
    echo.
    pause
    exit /b 1
)

netstat -ano | findstr "LISTENING" | findstr ":%PORT% " >nul
if not errorlevel 1 (
    echo [WARN] Port %PORT% is already in use.
    echo Opening the existing server.
    start "" "%URL%"
    echo.
    pause
    exit /b 0
)

echo [OK] Starting web server on port %PORT%...
echo [OK] Browser will open in a moment.
echo [OK] Press Ctrl+C to stop
echo.
start /b cmd /c "timeout /t 2 /nobreak >nul && start %URL%"
python web_server.py --host 127.0.0.1 --port %PORT%

echo.
echo [OK] Server stopped.
endlocal
pause
