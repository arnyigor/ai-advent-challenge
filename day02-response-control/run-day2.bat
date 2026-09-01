@echo off
rem ============================================================
rem  Day 02 - Response Control: quick run for demo
rem  Requires: Python 3.10+, requests, GEMINI_API_KEY in env
rem ============================================================
setlocal
cd /d "%~dp0"

if not defined GEMINI_API_KEY (
    echo [ERROR] GEMINI_API_KEY is not set in environment variables.
    echo Set it first, e.g.:  setx GEMINI_API_KEY "AIza..."
    pause
    exit /b 1
)

python -c "import requests" 2>nul
if errorlevel 1 (
    echo [INFO] Installing requests...
    python -m pip install -r requirements.txt || exit /b 1
)

echo ============================================================
echo  1/2  TEXT mode (demo, no Enter pauses)
echo ============================================================
python day2_response_control.py --mode text --no-interactive
echo.
pause

echo ============================================================
echo  2/2  JSON mode (deterministic document)
echo ============================================================
python day2_response_control.py --mode json
echo.
pause
endlocal
