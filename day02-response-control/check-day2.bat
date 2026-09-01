@echo off
echo ============================================
echo  Day 2 Response Control - environment check
echo ============================================
echo.

set FAIL=0

echo [1/6] python...
where python >nul 2>&1
if errorlevel 1 goto :py_fail
for /f "delims=" %%v in ('python --version 2^>^&1') do echo   OK: %%v
goto :py_done
:py_fail
echo   FAIL: python not found in PATH
set FAIL=1
:py_done
echo.

echo [2/6] ffmpeg...
where ffmpeg >nul 2>&1
if errorlevel 1 goto :ff_fail
echo   OK: ffmpeg found
goto :ff_done
:ff_fail
echo   FAIL: ffmpeg not found in PATH (set FFMPEG_PATH or add to PATH)
set FAIL=1
:ff_done
echo.

echo [3/6] GEMINI_API_KEY...
if "%GEMINI_API_KEY%"=="" goto :key_fail
echo   OK: GEMINI_API_KEY is set, value not shown
goto :key_done
:key_fail
echo   FAIL: GEMINI_API_KEY is not set for this session
echo   See tools\API_KEYS.md - set it as a User environment variable and restart the terminal
set FAIL=1
:key_done
echo.

echo [4/6] Pillow (needed only for record-video-headless.py)...
python -c "import PIL" >nul 2>&1
if errorlevel 1 goto :pil_warn
echo   OK: Pillow installed
goto :pil_done
:pil_warn
echo   WARN: Pillow not installed - run: pip install pillow
:pil_done
echo.

echo [5/6] py_compile day2_response_control.py...
python -m py_compile "%~dp0day2_response_control.py"
if errorlevel 1 goto :compile_fail
echo   OK: compiles cleanly
goto :compile_done
:compile_fail
echo   FAIL: syntax error in day2_response_control.py
set FAIL=1
:compile_done
echo.

echo [6/6] check-secrets.ps1 (no leaked keys in this folder)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\tools\check-secrets.ps1" -Path "%~dp0."
if errorlevel 1 goto :secrets_fail
goto :secrets_done
:secrets_fail
echo   FAIL: check-secrets.ps1 found something
set FAIL=1
:secrets_done
echo.

echo ============================================
if "%FAIL%"=="1" goto :result_fail
echo  RESULT: OK - environment is ready
echo.
echo  Next steps:
echo    python day2_response_control.py            ^(manual demo run^)
echo    python record-video-headless.py             ^(record video^)
goto :result_done
:result_fail
echo  RESULT: FAIL - fix the items above before recording
:result_done
echo ============================================

pause
