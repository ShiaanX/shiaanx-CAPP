# TASK 2 — Controller Log Schema Inventory & Dashboard Data Model

**Session type:** Inventory → Map → Design → Report  
**Time estimate:** 3–4 hours  
**Git branch:** `feature/dashboard-data-model`  
**Output:** `FINDINGS_dashboard_data_model.md` + `dashboard_data_model.json`

---

## Context

ShiaanX captures CNC controller telemetry into **InfluxDB** (time-series) and business
data (enquiries, orders, quotes) into **PostgreSQL**. The two systems together cover
most of what the dashboard needs. The objective of the dashboard is to track:

1. **FPR — First Pass Rate** (parts that pass QC on the first attempt, no rework)
2. **FAR cycle time** — time from job receipt to AS9102 submission / customer delivery

**Important correction from original task:** Controller logs are NOT in PostgreSQL.
They are in InfluxDB (AWS Timestream for InfluxDB, ap-south-1). PostgreSQL holds
business/order data only. Tonight's task is to inventory both stores, map data to
what the KPIs need, identify gaps, and produce a structured data model spec.

**What is already known (pre-verified):**
- InfluxDB bucket `cnc-data` has **356,383 rows** of real telemetry
- Machine in data: `factory_id=ts`, `machine_id=jyotiVMC`
- Measurement name: `cnc_telemetry`
- All 19 fields confirmed live (see Step 2 for full list)

---

## Objective

Inventory what is stored in PostgreSQL and MinIO today. Map available data to FPR and
FAR cycle time. Identify what is missing. Produce a dashboard data model specification
and a gap list.

---

## Inputs — pre-verified, all confirmed live

```
InfluxDB (CNC controller telemetry):
  URL:      https://8j1moabvym-aoe5tdinruw5gy.timestream-influxdb.ap-south-1.on.aws:8086
  Username: admin
  Password: admin123
  Org:      cnc-org
  Buckets:  cnc-data (primary, 356k rows), cnc-data-v2 (secondary)
  Auth:     POST /api/v2/signin with basic auth → use returned session cookie
            NOTE: session expires in ~1 hour. Re-POST /api/v2/signin to refresh.

PostgreSQL (business data — enquiries, orders, quotes):
  Start Docker first: cd C:\Users\Siddhant Gupta\Documents\ShiaanX\shiaanx-backend && docker compose up -d
  Connection: postgresql://postgres:7009@localhost:5432/sx_dev
  Schema lives in: shiaanx-backend/migrations/

Other relevant files:
  CLAUDE.md                              # Project context
  shiaanx-backend/src/utils/influxClient.js  # InfluxDB query patterns used by backend
  shiaanx-backend/migrations/            # Full PostgreSQL schema (all tables)
```

---

## Step-by-step instructions

### Step 1 — Set up the branch
```bash
git checkout main
git pull
git checkout -b feature/dashboard-data-model
```

### Step 2 — Inventory InfluxDB (CNC controller telemetry)
Write a Python script `audit/inventory_influx.py` and run it. Save all output to
`audit/influx_inventory.txt`.

```python
import requests, json

BASE = "https://8j1moabvym-aoe5tdinruw5gy.timestream-influxdb.ap-south-1.on.aws:8086"

def get_session():
    r = requests.post(f"{BASE}/api/v2/signin", auth=("admin", "admin123"), verify=False)
    r.raise_for_status()
    return r.cookies.get("influxdb-oss-session")

def flux_query(session, bucket, query):
    cookies = {"influxdb-oss-session": session}
    headers = {"Content-Type": "application/vnd.flux", "Accept": "application/csv"}
    r = requests.post(f"{BASE}/api/v2/query?org=cnc-org",
                      headers=headers, cookies=cookies, data=query, verify=False)
    if r.status_code == 401:  # session expired — re-auth
        session = get_session()
        cookies = {"influxdb-oss-session": session}
        r = requests.post(f"{BASE}/api/v2/query?org=cnc-org",
                          headers=headers, cookies=cookies, data=query, verify=False)
    return r.text, session

session = get_session()

# Known confirmed fields in cnc_telemetry (bucket: cnc-data, 356k rows):
# alarm_active, axis_x, axis_y, axis_z, block_number, cutting_time, cycle_time,
# feed_override, feed_rate, machine_mode, machine_state, production_count,
# production_time, program_name, program_runtime, spindle_load, spindle_override,
# spindle_speed, tool_name, tool_number
# Tags: factory_id (= "ts"), machine_id (= "jyotiVMC")

# 1. Row counts per field
result, session = flux_query(session, "cnc-data", """
from(bucket: "cnc-data") |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "cnc_telemetry")
  |> count() |> limit(n: 30)
""")
print("=== ROW COUNTS (cnc-data) ==="); print(result)

# 2. Sample 5 rows of recent data
result, session = flux_query(session, "cnc-data", """
from(bucket: "cnc-data") |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "cnc_telemetry")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> limit(n: 5)
""")
print("=== SAMPLE ROWS (last 7 days) ==="); print(result)

# 3. Unique program names
result, session = flux_query(session, "cnc-data", """
from(bucket: "cnc-data") |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "cnc_telemetry" and r._field == "program_name")
  |> distinct(column: "_value") |> limit(n: 50)
""")
print("=== UNIQUE PROGRAMS ==="); print(result)

# 4. Date range of data
result, session = flux_query(session, "cnc-data", """
from(bucket: "cnc-data") |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "cnc_telemetry" and r._field == "cycle_time")
  |> first()
""")
print("=== OLDEST RECORD ==="); print(result)

result, session = flux_query(session, "cnc-data", """
from(bucket: "cnc-data") |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "cnc_telemetry" and r._field == "cycle_time")
  |> last()
""")
print("=== NEWEST RECORD ==="); print(result)

# 5. Also check cnc-data-v2
result, session = flux_query(session, "cnc-data-v2", """
from(bucket: "cnc-data-v2") |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "cnc_telemetry")
  |> count() |> limit(n: 5)
""")
print("=== ROW COUNTS (cnc-data-v2) ==="); print(result)
```

### Step 3 — Inventory PostgreSQL (business data)
Start Docker first: `cd C:\Users\Siddhant Gupta\Documents\ShiaanX\shiaanx-backend && docker compose up -d`

Connect to `postgresql://postgres:7009@localhost:5432/sx_dev` and run:
```sql
-- Row counts for all tables
SELECT schemaname, tablename, n_live_tup AS row_count
FROM pg_stat_user_tables ORDER BY n_live_tup DESC;

-- Sample enquiry with status history
SELECT e.id, e.enquiry_number, e.status, e.submitted_at, e.created_at
FROM enquiries e LIMIT 5;

SELECT * FROM enquiry_status_history LIMIT 10;
SELECT * FROM order_status_history LIMIT 10;

-- ProgramToolMappings (links InfluxDB program names to tool names)
SELECT * FROM "ProgramToolMappings" LIMIT 20;
```
Save all output to `audit/db_inventory.txt`.

**If Docker Postgres is empty:** Note it and use the schema from `shiaanx-backend/migrations/`
to document the intended schema — the live data is on the AWS backend at `http://13.233.172.143`.
```

### Step 4 — Map available data to FPR and FAR KPIs
Write `audit/kpi_mapping.md` with two sections.

**Section A — FPR (First Pass Rate)**

FPR requires knowing, for each part:
- Was a QC inspection performed?
- Did it pass on the first attempt?
- If not, what was the failure mode (dimensional, surface finish, feature missed)?

For each data field you found in Step 2/3, note whether it contributes to computing FPR:
```
Field: [table.column]
Available: YES / NO / PARTIAL
Computes: [what aspect of FPR this helps with]
Gap: [what is missing to fully compute FPR]
```

**Section B — FAR Cycle Time**

FAR cycle time requires timestamps for each stage:
1. Job received (customer PO / enquiry date)
2. CAPP generated (program sheet produced)
3. Raw material procured
4. Machining complete
5. QC inspection complete
6. AS9102 first article report submitted
7. Customer acceptance

Same format — for each stage, note what timestamp field exists vs. what is missing.

**Section C — Other potential dashboard metrics**

Beyond FPR and FAR, what else could be computed from available data?
(e.g., machine utilisation, on-time delivery rate, rework cost, average quote-to-PO time)
List these as "bonus metrics" — not required for MVP dashboard.

### Step 5 — Design the dashboard data model
Write `dashboard_data_model.json` — a structured specification of what the dashboard
needs. Format:

```json
{
  "dashboard_version": "0.1",
  "primary_kpis": [
    {
      "kpi_name": "First Pass Rate (FPR)",
      "definition": "Percentage of parts that pass QC inspection on first attempt",
      "numerator": "Parts passing QC on first attempt in period",
      "denominator": "Total parts inspected in period",
      "granularity": ["overall", "by_customer", "by_material", "by_part_complexity"],
      "refresh_cadence": "daily",
      "source_tables": ["[table names from DB]"],
      "missing_data": ["[list of fields that don't exist yet]"],
      "status": "computable_now | partial | blocked"
    },
    {
      "kpi_name": "FAR Cycle Time",
      "definition": "Calendar days from job receipt to AS9102 submission",
      "stages": [
        {"stage": "job_receipt", "source_field": "[table.column or MISSING]"},
        {"stage": "capp_generated", "source_field": "[table.column or MISSING]"},
        {"stage": "material_procured", "source_field": "[table.column or MISSING]"},
        {"stage": "machining_complete", "source_field": "[table.column or MISSING]"},
        {"stage": "qc_complete", "source_field": "[table.column or MISSING]"},
        {"stage": "far_submitted", "source_field": "[table.column or MISSING]"}
      ],
      "status": "computable_now | partial | blocked"
    }
  ],
  "capture_gaps": [
    {
      "gap_description": "[What needs to be captured that currently isn't]",
      "required_for_kpi": "FPR | FAR | both",
      "capture_method": "[How to capture it — OPC UA tag, form field, webhook, etc.]",
      "priority": "P0 | P1 | P2"
    }
  ]
}
```

### Step 6 — Write FINDINGS_dashboard_data_model.md

---

## Output files required (all committed to branch)

| File | Description |
|------|-------------|
| `audit/db_inventory.txt` | Raw PostgreSQL schema + sample rows |
| `audit/minio_inventory.txt` | MinIO bucket and object listing |
| `audit/kpi_mapping.md` | Field-by-field mapping to FPR and FAR |
| `dashboard_data_model.json` | Structured dashboard spec |
| `FINDINGS_dashboard_data_model.md` | Summary findings report |

---

## FINDINGS_dashboard_data_model.md template

```markdown
# Dashboard Data Model — Findings
Date: [date]

## What exists today
- PostgreSQL tables: [list]
- MinIO buckets: [list]
- Data coverage: [brief summary — sparse, moderate, rich?]

## FPR Status
[Can it be computed today? What is missing?]

## FAR Cycle Time Status
[Which stages have timestamps? Which are missing?]

## P0 Capture Gaps (must fix to compute MVP KPIs)
1. [Gap description] — required for [FPR/FAR] — capture via [method]
2. ...

## P1 Capture Gaps (fix within 2 weeks)
1. ...

## Recommended MVP Dashboard (what to build first given available data)
[Given what exists, what 3–4 metrics can actually be shown on a dashboard today?]

## Questions for human decision
1. [Any ambiguity about data ownership, schema design, or business logic]
```

---

## What NOT to do tonight

- Do NOT build any dashboard UI
- Do NOT write any React, HTML, or frontend code
- Do NOT create new PostgreSQL tables or alter existing schema
- Do NOT write data to any database
- Do NOT design the visual layout of the dashboard — that requires human input
- Do NOT assume what the dashboard should look like — only what data it needs

---

## Hard stop conditions

Stop immediately and write FINDINGS.md if:
- Cannot authenticate to InfluxDB after 3 retries (check URL and credentials in Inputs section)
- InfluxDB connects but `cnc-data` bucket returns 0 rows — this would be unexpected; note and stop
- Cannot start local Docker Postgres (note it and proceed using migration files for schema reference only)
