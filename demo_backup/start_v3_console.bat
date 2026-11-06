@echo off
rem Starts the ShiaanX planner console (Rohit's PowerMill console) on http://localhost:8765
set "PATH=C:\Users\Siddhant Gupta\miniconda3\condabin;C:\Users\Siddhant Gupta\miniconda3\Scripts;%PATH%"
cd /d "C:\Users\Siddhant Gupta\Documents\shiaanx_v3_standalone"
echo Starting the planner console on http://localhost:8765 ...
"C:\Users\Siddhant Gupta\miniconda3\envs\occ_env\python.exe" ui\server.py
echo.
echo The console has stopped.
pause
