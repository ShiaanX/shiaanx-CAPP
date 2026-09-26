@echo off
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  echo Missing .venv. Run setup.bat first.
  exit /b 1
)

if "%PORT%"=="" set PORT=8780
echo Starting CAD Feature Recognition at http://127.0.0.1:%PORT%
.venv\Scripts\python.exe -m uvicorn local_app.main:app --host 127.0.0.1 --port %PORT%
