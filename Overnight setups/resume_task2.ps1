# Resume TASK 2 after rate limit reset
Set-Location "C:\Users\Siddhant Gupta\Documents\ShiaanX"

$prompt = @"
The rate limit has reset. You were running TASK 2 (dashboard data model and controller log schema inventory) on branch feature/dashboard-data-model.

To resume:
1. Run: git checkout feature/dashboard-data-model
2. Read audit/influx_inventory.txt and audit/db_inventory.txt if they exist — these show what was inventoried
3. Read audit/kpi_mapping.md if it exists — check which KPI sections are done
4. Continue from the next incomplete step in TASK_2_controller_logs_dashboard.md
5. When complete, write FINDINGS_dashboard_data_model.md

InfluxDB credentials if needed:
- URL: https://8j1moabvym-aoe5tdinruw5gy.timestream-influxdb.ap-south-1.on.aws:8086
- Auth: POST /api/v2/signin with username=admin password=admin123
- Org: cnc-org, Bucket: cnc-data

Read CLAUDE.md first for project context. Then resume.
"@

$prompt | claude --dangerously-skip-permissions
