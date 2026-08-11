@echo off
REM Orchestra launcher for Windows. Idempotent: safe to run every time.
setlocal
cd /d "%~dp0"

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
