$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "Virtuális környezet létrehozása..."
    python -m venv .venv
}

Write-Host "Függőségek telepítése..."
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -r requirements.txt

Write-Host ""
Write-Host "Kész. Következő lépés:"
Write-Host "  .\lidl.cmd login"
Write-Host ""
Write-Host "Részletes útmutató: HASZNALAT.md"
