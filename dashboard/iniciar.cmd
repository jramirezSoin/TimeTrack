@echo off
rem Doble clic: inicia el dashboard de TimeTrack en segundo plano (ver iniciar.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0iniciar.ps1"
timeout /t 3 >nul
