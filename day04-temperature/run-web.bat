@echo off
chcp 65001 >nul
rem ============================================================
rem Day 04 — Температура: запуск веб-интерфейса
rem Порт: 8766 (отдельный от Day 3 — 8765 и Day 1 — 3000)
rem ============================================================
setlocal
cd /d "%~dp0"

set PORT=8766
echo ============================================
echo Day 4 Temperature — Web UI
echo ============================================
echo.
rem Проверка, что порт свободен
netstat -ano | findstr "LISTENING" | findstr ":%PORT% " >nul
if not errorlevel 1 (
    echo [X] Port %PORT% already in use.
    echo Just open http://127.0.0.1:%PORT% - or stop the old server.
    pause
    exit /b 1
)
echo [OK] Starting web server on port %PORT%...
echo [OK] Open http://127.0.0.1:%PORT% in browser
echo [OK] Press Ctrl+C to stop
echo.
rem Открываем браузер с задержкой, чтобы сервер успел стартовать
start /b cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:%PORT%"
python web_server.py --host 127.0.0.1 --port %PORT%
echo.
echo [OK] Server stopped.
endlocal
pause