@echo off
rem claude-office: stop the hub and the collector and remove their scheduled tasks. Settings and images stay in data\.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\setup.ps1" -Uninstall
echo.
pause
