# Dashboard Data Model — Findings
Date: 2026-06-22
Author: Automated inventory session

---

## What Exists Today

### InfluxDB (CNC Controller Telemetry)

| Bucket | Rows | Date Range | Machine | Structure |
|--------|------|------------|---------|-----------|
| cnc-data | 356,383 | 2026-05-06 to 2026-05-13 | jyotiVMC | program_name as FIELD |
| cnc-data-v2 | ~132,535 | 2026-05-08 to 2026-06-06 | jyotiVMC | program_name as TAG (better) |

**20 confirmed fields:** alarm_active, axis_x/y/z, block_number, cutting_time, cycle_time, feed_override, feed_rate, machine_mode, machine_state, production_count, production_time, program_name, program_runtime, spindle_load, spindle_override, spindle_speed, tool_name, tool_number

**Data quality issues found:**
1. `production_count` is always 0 across all 356,383 rows — part counter not working
2. `tool_name` stores G-code program text, not tool names (field name is misleading)
3. cnc-data has no data since 2026-05-13 (~40 days stale); cnc-data-v2 is more recent (last data: 2026-06-06, ~16 days ago)
4. No data in last 7 days from either bucket as of query date

**80+ unique programs in cnc-data-v2** covering parts: 200873, 200874, 200879, 200880, 204995, 204997, 226718, GI023/024, GL034/106-109, GP034, IR366, MOTOR_MOUNT, UBR01036/08642/12937, and more.

### PostgreSQL (Business Data)

**27 tables** — schema fully defined via 26 migrations. Local Docker instance is empty (dev only); live data on AWS at 13.233.172.143:3003.

Key tables for the dashboard:

| Table | Purpose | Key Timestamp Fields |
|-------|---------|---------------------|
| enquiries | Job receipt, RFQ | submitted_at, created_at |
| enquiry_parts | Per-part specs, auto-quote | auto_quote_status (no timestamp) |
| orders | Confirmed orders | generated_at, expected_delivery_date, actual_delivery_date |
| enquiry_status_history | Status transitions | created_at per transition |
| order_status_history | Order status transitions | created_at per transition |
| ProgramToolMappings | Links InfluxDB program_name to tool | — |

### Object Storage

**AWS S3** (not MinIO as originally listed in task). Stores CAD files, drawings, PDFs. Not relevant to KPI computation.

---

## FPR Status

**FPR cannot be computed today. Status: BLOCKED.**

The entire QC layer is absent from the system. There is no table, field, or data capture for:
- Whether a part was inspected
- Whether it passed or failed on first attempt
- What the failure mode was (dimensional, surface finish, feature, etc.)
- Whether it was reworked and reinspected

The `production_count` InfluxDB field that could approximate part count is always 0 — a separate P0 issue that must be fixed regardless.

**What is needed to unblock FPR:**
A single new PostgreSQL table (`qc_inspection_results`) with: order_id, part_id, inspected_at, outcome (PASS/FAIL/CONDITIONAL), failure_mode, rework_cycle_number. Even a basic web form to populate this table is sufficient to start computing FPR.

---

## FAR Cycle Time Status

**FAR cycle time is partially blocked. 2 of 7 stages have timestamps. Status: PARTIAL.**

| Stage | Timestamp Available | Source |
|-------|---------------------|--------|
| Job received | YES | enquiries.submitted_at |
| CAPP generated | NO | Not captured anywhere |
| Material procured | NO | No procurement module |
| Machining complete | PARTIAL | Derivable from InfluxDB (program_name session end) but not stored in DB |
| QC complete | NO | No QC module |
| FAR submitted | NO | Not tracked anywhere |
| Customer acceptance | PARTIAL | orders.actual_delivery_date (delivery, not acceptance) |

**What can be computed today** (approximation only):
- Total order-to-delivery days = `orders.actual_delivery_date - enquiries.submitted_at`
- This is NOT the same as FAR cycle time but is a starting proxy.

---

## P0 Capture Gaps (must fix to compute MVP KPIs)

1. **[G01] QC inspection outcome** — required for FPR — capture via new PostgreSQL table `qc_inspection_results` + admin form. Effort: Medium.

2. **[G02] production_count always 0** — required for part counting — fix OPC UA/Focas tag mapping on jyotiVMC controller. Effort: Low (operational fix, not code).

3. **[G03] CAPP generated timestamp** — required for FAR stage 2 — add `capp_generated_at` to `enquiry_parts`, write from `capp_service/runner.py`. Effort: Low (1 migration + 3 lines of code).

4. **[G04] InfluxDB-to-PostgreSQL job linkage** — required for machining complete (FAR stage 4) — create `program_job_mappings` table; populate from CAPP pipeline when program sheet is generated. Effort: Low.

5. **[G07] Telemetry collection is stale** — required for all InfluxDB KPIs — restart data collection agent; switch dashboard to cnc-data-v2 as primary bucket. Effort: Low (operational).

---

## P1 Capture Gaps (fix within 2 weeks)

1. **[G05] FAR report tracking** — required for FAR stage 6 — new table `far_reports` + admin form + S3 upload. Effort: Medium.

2. **[G06] Material procurement dates** — required for FAR stage 3 — add `material_ordered_date`, `material_received_date` to orders. Effort: Low.

---

## Recommended MVP Dashboard (what to build first given available data)

Given the data available today, these 4 metrics can be shown on a live dashboard without any new data capture:

### 1. Machine Utilization Rate (Daily)
- **Source:** InfluxDB cnc-data-v2
- **Query:** `sum(cutting_time) / sum(production_time)` per day
- **Visualization:** Line chart over time + single number (today's %)
- **Business value:** Shows factory productivity without needing QC data

### 2. Cycle Time per Program
- **Source:** InfluxDB cnc-data-v2 (program_name as tag)
- **Query:** `mean(cycle_time)` grouped by program_name
- **Visualization:** Bar chart sorted by cycle time
- **Business value:** Identifies which programs are slowest; validates CAPP parameter estimates

### 3. Alarm Events Timeline
- **Source:** InfluxDB cnc-data (alarm_active field)
- **Query:** `count(alarm_active=1)` per day per program
- **Visualization:** Heatmap (program × day) or bar chart
- **Business value:** Early warning for setup problems or tool issues

### 4. Jobs in Progress (Pipeline View)
- **Source:** PostgreSQL (requires live AWS data) + InfluxDB program_name
- **Query:** Join enquiries (status != DELIVERED) with most recent program_name in InfluxDB
- **Visualization:** Kanban-style status table: enquiry_number | material | status | last_seen_on_machine
- **Business value:** Real-time visibility into where each job is in the pipeline

---

## Surprise Findings (not anticipated in task brief)

1. **`tool_name` is not a tool name** — it contains multi-line G-code program text (the currently executing CNC block). The backend already handles this correctly via `parseGCode()` in analytics.controller.js, but anyone looking at raw InfluxDB data would be confused. Rename the field or add documentation.

2. **cnc-data-v2 is better than cnc-data** — in v2, `program_name` is stored as an InfluxDB TAG rather than a measurement field. Tags are indexed and enable efficient `filter(fn: (r) => r.program_name == "X")` queries. The cnc-data bucket would require a full scan to filter by program. All new dashboards should query cnc-data-v2.

3. **80+ unique programs in cnc-data-v2 vs. 7 in cnc-data** — the v2 bucket has significantly broader job coverage (includes MOTOR_MOUNT, GP034, UBR08642, etc.). cnc-data was only collecting from May 6-13; v2 captures data through June 6.

4. **Production_count is universally 0** — the part counter OPC UA tag has never worked. Every metric that requires "parts made" (utilization %, FPR denominator, tool change intervals) is blocked by this single misconfiguration.

5. **No MinIO — it's AWS S3** — the task brief mentioned MinIO but the system uses AWS S3. This is a minor naming difference but confirms that all document storage is cloud-hosted (no local object storage running).

---

## Questions for Human Decision

1. **Which timestamp is "job received"?** — `enquiries.submitted_at` (when customer submitted the enquiry form) vs `orders.generated_at` (when the admin confirmed the PO). The FAR clock typically starts at PO receipt, not RFQ.

2. **Should machining complete be automatically detected from InfluxDB** (when program_name session ends and machine returns to idle), or should it be a manual field the operator marks? Automatic is more accurate but requires the program_job_mappings linkage to be in place.

3. **What qualifies as a "part" for FPR?** — Is it per `enquiry_parts` row, per `order` quantity (e.g., if an order is for 10 pieces, are all 10 tracked individually?), or per program execution? This determines the granularity of the qc_inspection_results table.

4. **Who does QC inspection?** — Internal QA team, the operator, or the customer? This affects whether the `inspector_id` field in qc_inspection_results should reference `users` table or a separate inspector table.

5. **Does the dashboard need to show data from the AWS production Postgres instance**, or is a separate dashboard-specific read replica or analytics database preferred? Direct queries to the production DB from a public dashboard are a security concern.

---

## Migrations Created (2026-06-23)

Four Sequelize migration files added to `shiaanx-backend/migrations/`.
All four tested against local Docker Postgres — all ran successfully with 0 errors.

| Migration | File | What it creates | KPI unblocked |
|-----------|------|-----------------|---------------|
| 27 | 27-create-qc-inspection-results.js | `qc_inspection_results` table | FPR |
| 28 | 28-create-program-job-mappings.js | `program_job_mappings` table | FAR stage 4, utilisation per job |
| 29 | 29-add-capp-generated-at-to-enquiry-parts.js | `capp_generated_at` column on `enquiry_parts` | FAR stage 2 |
| 30 | 30-add-manufacturing-timestamps-to-orders.js | 4 timestamp columns on `orders` | FAR stages 3, 4, 5, 6 |

**Run command:**
```bash
cd shiaanx-backend
DB_USER=postgres DB_PASS=7009 DB_NAME=sx_dev DB_HOST=localhost npx sequelize-cli db:migrate
```

See `shiaanx-backend/migrations/DASHBOARD_MIGRATIONS.md` for full column specs, FPR formula SQL, FAR query SQL, and how each field should be populated.

**KPI coverage after migrations applied:**

| KPI | Before | After migrations |
|-----|--------|-----------------|
| FPR | BLOCKED | COMPUTABLE (needs QC form to write rows) |
| FAR stage 2 (CAPP) | MISSING | COMPUTABLE (needs runner.py write-back) |
| FAR stage 3 (material) | MISSING | COMPUTABLE (needs admin form) |
| FAR stage 4 (machining) | PARTIAL | COMPUTABLE (InfluxDB auto-detect or admin entry) |
| FAR stage 5 (QC) | MISSING | COMPUTABLE (set from qc_inspection_results) |
| FAR stage 6 (FAR) | MISSING | COMPUTABLE (needs admin form) |
| Machine util. per job | MISSING | COMPUTABLE (program_job_mappings + InfluxDB) |

---

## Output Files

| File | Contents |
|------|----------|
| `audit/influx_inventory.txt` | InfluxDB full inventory — fields, row counts, date ranges, program lists |
| `audit/db_inventory.txt` | PostgreSQL schema from migrations, table list, row counts |
| `audit/minio_inventory.txt` | MinIO not deployed — AWS S3 used instead |
| `audit/kpi_mapping.md` | Field-by-field FPR and FAR mapping, bonus metrics |
| `dashboard_data_model.json` | Structured dashboard spec with gaps and proposed schema |
| `shiaanx-backend/migrations/27-create-qc-inspection-results.js` | QC table migration |
| `shiaanx-backend/migrations/28-create-program-job-mappings.js` | InfluxDB↔PG link migration |
| `shiaanx-backend/migrations/29-add-capp-generated-at-to-enquiry-parts.js` | CAPP timestamp migration |
| `shiaanx-backend/migrations/30-add-manufacturing-timestamps-to-orders.js` | FAR stages 3-6 migration |
| `shiaanx-backend/migrations/DASHBOARD_MIGRATIONS.md` | Migration guide with SQL examples |
| `FINDINGS_dashboard_data_model.md` | This file |
