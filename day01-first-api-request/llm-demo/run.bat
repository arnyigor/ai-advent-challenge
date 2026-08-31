@echo off
chcp 65001 >nul
REM Launch llm-demo (Web + API). Requires Node.js 18+.
cd /d "%~dp0"
echo.

REM Check if port 3000 is already in use
netstat -ano | findstr "LISTENING" | findstr ":3000 " >nul
if not errorlevel 1 (
  echo  [X] Port 3000 already in use: llm-demo seems to be running.
  echo      Just open http://localhost:3000 - or stop the old server.
  pause
  exit /b 1
)

echo  [OK] llm-demo: http://localhost:3000
echo  (Ctrl+C to stop)
REM Open browser with a delay so the server has time to start
start /b cmd /c "timeout /t 1 /nobreak >nul && start http://localhost:3000"
node server.mjs
echo.
echo  [OK] Server stopped.
pause
