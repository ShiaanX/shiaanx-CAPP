# Starts everything needed to rehearse the demo on http://localhost:3000/admin/#/proto
# Safe to run any time: a service that is already listening is left alone.
#   Right-click > Run with PowerShell, or from PowerShell:  .\start_local_demo.ps1
# Needs Docker Desktop to be running (the local database lives in a container).
$root = 'C:\Users\Siddhant Gupta\Documents\ShiaanX'
$py   = 'C:\Users\Siddhant Gupta\miniconda3\envs\occ\python.exe'
$qcdir = "$root\Claude output for program sheet\labeling_app"
$logs = Join-Path $env:TEMP 'shiaanx-demo-logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null

function Test-Port($port) { [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) }
function Start-Service($name, $port, $file, $argList, $dir) {
    if (Test-Port $port) { Write-Host ("  {0,-26} already running on {1}" -f $name, $port); return }
    Start-Process -FilePath $file -ArgumentList $argList -WorkingDirectory $dir -WindowStyle Hidden `
        -RedirectStandardOutput "$logs\$name.log" -RedirectStandardError "$logs\$name.err"
    Write-Host ("  {0,-26} starting on {1}" -f $name, $port)
}

Write-Host 'ShiaanX local demo services'
docker info *> $null
if ($LASTEXITCODE -ne 0) { Write-Host '  Docker Desktop is not running: open it first (the local database needs it).'; exit 1 }
docker start flowtest-db-1 *> $null
Write-Host '  database (Docker)          ready'

Start-Service 'flow backend'       8080 'powershell.exe' "-NoProfile -ExecutionPolicy Bypass -File `"$root\demo_backup\start_flow_backend.ps1`"" $root
Start-Service 'part-analysis (capp)' 8001 $py '-m uvicorn main:app --port 8001' "$root\capp_service"
Start-Service 'QC 3D service'      8780 "$qcdir\.venv\Scripts\python.exe" '-m uvicorn local_app.main:app --host 127.0.0.1 --port 8780' $qcdir
$env:BROWSER = 'none'
Start-Service 'frontend'           3000 'cmd.exe' '/c npm start' "$root\shiaanx-frontend-admin"

Write-Host ''
Write-Host 'Give the frontend about a minute to compile, then open:'
Write-Host '  http://localhost:3000/admin/#/proto'
Write-Host "Logs: $logs"
Write-Host 'The planner console (8765) starts from the Program card; PowerMill must be open for the PowerMill buttons.'
