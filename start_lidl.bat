@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PORT=%~1"
if not defined PORT set "PORT=8765"
set "NOOPEN="
if /I "%~2"=="--no-open" set "NOOPEN=--no-open"

if not exist ".venv\Scripts\python.exe" (
  echo [HIBA] A fuggosegek nincsenek telepitve.
  echo Futtasd egyszer: powershell -ExecutionPolicy Bypass -File setup.ps1
  pause
  exit /b 1
)

netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul
if not errorlevel 1 (
  echo A dashboard mar fut a %PORT% porton. Megnyitas...
  start "" "http://127.0.0.1:%PORT%/"
  exit /b 0
)

echo Lidl dashboard inditasa a %PORT% porton...
".venv\Scripts\python.exe" -m lidl dashboard --port %PORT% %NOOPEN%
if errorlevel 1 (
  echo.
  echo A dashboard hiba miatt leallt.
  pause
)
