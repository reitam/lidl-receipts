@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [HIBA] A fuggosegek nincsenek telepitve. Futtasd egyszer:
  echo   powershell -ExecutionPolicy Bypass -File setup.ps1
  exit /b 1
)

".venv\Scripts\python.exe" -m lidl %*
