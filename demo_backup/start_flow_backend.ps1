# Starts the production-flow backend (shiaanx-backend-flow) on http://localhost:8080 for the demo.
# Uses the local "flowtest" Postgres container (127.0.0.1:55432, db sx_flow). The DB password and
# JWT secret are read from that stack's backend container at start-up, so none are stored here.
# Prereq: Docker Desktop running. Run from any PowerShell:  .\start_flow_backend.ps1
#   -Data devcopy (default): sx_flow_devcopy, a local COPY of dev.shiaanx.com's DB + uploaded files
#                            (taken 2026-11-05; files in demo_backup\devcopy\flow). Nothing reaches dev.
#   -Data test:              sx_flow, the local test DB a Claude session created on 2026-10-23.
param([ValidateSet('devcopy','test')][string]$Data = 'devcopy')
$ErrorActionPreference = 'Stop'
docker start flowtest-db-1 | Out-Null
$envs = docker inspect flowtest-backend-1 --format '{{range .Config.Env}}{{println .}}{{end}}'
function Get-ContainerEnv($name) { ($envs | Where-Object { $_ -like "$name=*" } | Select-Object -First 1) -replace "^$name=", '' }
$env:DB_USER = 'postgres'; $env:DB_NAME = $(if ($Data -eq 'devcopy') { 'sx_flow_devcopy' } else { 'sx_flow' }); $env:DB_HOST = '127.0.0.1'; $env:DB_PORT = '55432'
$env:DB_DIALECT = 'postgres'; $env:NODE_ENV = 'development'; $env:PORT = '8080'
$env:DB_PASS = Get-ContainerEnv 'DB_PASS'; $env:JWT_SECRET = Get-ContainerEnv 'JWT_SECRET'
$env:AWS_S3_BUCKET = 'unused-local-disk'; $env:AWS_S3_REGION = 'ap-south-1'   # multer-s3 needs a name even for local disk
$env:CAPP_URL = 'http://localhost:8001'
$env:FLOW_STORAGE_DIR = $(if ($Data -eq 'devcopy') { 'C:\Users\Siddhant Gupta\Documents\ShiaanX\demo_backup\devcopy\flow' } else { 'C:\Users\Siddhant Gupta\Documents\ShiaanX\shiaanx-backend-flow\storage\flow' })
Write-Host "flow backend: data=$Data db=$env:DB_NAME files=$env:FLOW_STORAGE_DIR"
Set-Location 'C:\Users\Siddhant Gupta\Documents\ShiaanX\shiaanx-backend-flow'
node server.js
