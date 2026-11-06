@echo off
rem Starts the local 3D QC service on http://127.0.0.1:8780 for rehearsal (see demo_backup\qc\README.md).
rem Needs the labeling_app environment (OCP) set up with labeling_app\setup.bat.
cd /d "C:\Users\Siddhant Gupta\Documents\ShiaanX\Claude output for program sheet\labeling_app"
echo Starting the QC service on http://127.0.0.1:8780 ...
echo The frontend then needs REACT_APP_QC_URL=http://127.0.0.1:8780 (set it and restart npm start).
".venv\Scripts\python.exe" -m uvicorn local_app.main:app --host 127.0.0.1 --port 8780
echo.
echo The QC service has stopped.
pause
