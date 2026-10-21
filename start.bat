@echo off
rem claude-office: install / update / start everything on this Windows PC (hub + collector), then open the browser.
rem Double-click this file. No admin rights needed. Messages come from windows\setup.ps1.
setlocal
cd /d "%~dp0"
echo [claude-office] Setting up and starting (hub + collector)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\setup.ps1"
if errorlevel 1 (
  echo.
  echo [claude-office] FAILED - see the messages above.
  pause
  exit /b 1
)
echo.
echo [claude-office] Done. This window closes in 10 seconds.
timeout /t 10 >nul
