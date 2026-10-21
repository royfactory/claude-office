@echo off
rem claude-office: show whether the hub and the collector are running, with their recent logs.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\setup.ps1" -Status
echo.
pause
