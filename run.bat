@echo off
REM Orchestra launcher for Windows. Idempotent: safe to run every time.
setlocal
cd /d "%~dp0"

REM Load .env if present. Keys supplied this way are never written to
REM %USERPROFILE%\.orchestra\config.json - the app reads the environment on
REM every load. Names are echoed, values never are.
if exist .env (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    echo %%A| findstr /r "^[ ]*#" >nul || if not "%%B"=="" (
      set "%%A=%%B"
      echo Loaded from .env: %%A
    )
  )
)

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.10+ is required but was not found on PATH.
  echo Install it from https://python.org, then run this script again.
  exit /b 1
)

if not exist .venv (
  echo First run: creating virtual environment...
  python -m venv .venv
)

call .venv\Scripts\activate.bat

fc /b requirements.txt .venv\.requirements-stamp >nul 2>nul
if errorlevel 1 (
  echo Installing dependencies...
  python -m pip install --quiet --upgrade pip
  python -m pip install --quiet -r requirements.txt
  copy /y requirements.txt .venv\.requirements-stamp >nul
)

python -m orchestra %*
