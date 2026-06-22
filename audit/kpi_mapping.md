# KPI Data Mapping — FPR and FAR Cycle Time
Date: 2026-06-22

---

## Section A — FPR (First Pass Rate)

**Definition:** Percentage of parts that pass QC inspection on the first attempt with no rework.
**Formula:** FPR = (Parts passing QC on first attempt) / (Total parts inspected) × 100

### Field Mapping

```
Field: InfluxDB cnc_telemetry.production_count
Available: NO
Computes: Part count (how many cycles completed)
Gap: Field exists but is always 0. The CNC controller's part counter is not
     being captured correctly — either the OPC UA tag is unmapped or the
     counter resets between sessions. Cannot use for part counting.

Field: InfluxDB cnc_telemetry.cycle_time
Available: PARTIAL
Computes: Indirect indicator — a completed machining cycle can be inferred
          when cycle_time resets (drops from high to near-zero). This gives
          approximate part count per program run. However, it does not
          distinguish between a passed or rejected part.
Gap: No pass/fail flag. Cannot compute FPR from cycle detection alone.

Field: InfluxDB cnc_telemetry.program_name (v2 bucket: as tag)
Available: YES
Computes: Which part was being machined during each telemetry window.
          Links telemetry to a specific job.
Gap: program_name alone does not indicate outcome (pass/fail).

Field: InfluxDB cnc_telemetry.alarm_active
Available: YES
Computes: Whether a machine alarm occurred during a cycle. A cycle with
          alarm_active=1 may indicate a failed or interrupted part.
Gap: Not all alarms cause part rejection. Cannot use alarm as proxy for FPR.

Field: InfluxDB cnc_telemetry.spindle_load
Available: YES
Computes: Indirect quality signal — abnormal spindle load during a cycle
          may indicate tool breakage, chatter, or incorrect cutting. Could
          eventually feed into an ML model for quality prediction.
Gap: No ground-truth QC outcome to train against. Not directly usable for FPR.

Field: PostgreSQL enquiry_parts.auto_quote_data (JSONB)
Available: NO (schema exists, no live data locally)
Computes: Part specifications — material, quantity, process. Needed to
          denominator of FPR (total parts ordered).
Gap: No QC outcome stored here.

Field: PostgreSQL orders.quantity
Available: NO (schema exists, no live data locally)
Computes: How many parts were ordered per job.
Gap: No QC outcome stored here.
```

### FPR Gap Summary

**Status: BLOCKED — cannot compute FPR at all today.**

No data store anywhere in the system captures:
1. Whether a QC inspection was performed on a part
2. The outcome (pass / fail / conditional pass)
3. The failure mode (dimensional, surface finish, feature missed, etc.)
4. Whether the part was reworked and re-inspected
5. The rework cycle count (how many attempts before pass)

**Root cause:** QC is a manual, offline process. No inspection data is flowing into InfluxDB or PostgreSQL.

---

## Section B — FAR Cycle Time

**Definition:** Calendar days from job receipt to AS9102 First Article Report submission.

### Stage-by-Stage Mapping

```
Stage 1 — Job received (customer PO / enquiry date)
Field: enquiries.submitted_at
Available: PARTIAL (schema exists, no live data in local DB; live on AWS)
Computes: Timestamp when customer submitted the enquiry/RFQ
Gap: submitted_at can be null if enquiry was created without explicit submission.
     enquiries.created_at is always populated (auto-timestamp on INSERT).
     Need to confirm which timestamp the team uses as "job received."

Stage 2 — CAPP generated (program sheet produced)
Field: MISSING
Available: NO
Computes: Would mark when the AI pipeline completed the process plan + PDF.
Gap: No timestamp stored when capp_service generates a program sheet.
     The pipeline runs (capp_service/runner.py) but does not write back to
     any database with a completion timestamp. enquiry_parts.auto_quote_status
     has PENDING_PIPELINE / DRAFT / FINALIZED but no timestamp for transitions.

Stage 3 — Raw material procured
Field: MISSING
Available: NO
Computes: When raw material was purchased and received.
Gap: No procurement module exists. No table in PostgreSQL for material
     purchase orders or goods receipt.

Stage 4 — Machining complete
Field: PARTIAL (InfluxDB-derivable with effort)
Available: PARTIAL
Computes: End of machining for a job. Can be approximated from:
          - InfluxDB cnc_telemetry: machine_state returns to 0 (idle) after
            a long program_name session
          - cycle_time resetting at end of last cycle for a program
Gap: No explicit "machining_complete" event written anywhere. The InfluxDB
     data ends (program_name stops appearing) but there is no database record.
     Linking InfluxDB program_name back to a PostgreSQL enquiry/order
     requires ProgramToolMappings or a naming convention — not automated.

Stage 5 — QC inspection complete
Field: MISSING
Available: NO
Computes: When dimensional + visual inspection was signed off.
Gap: No QC module. No table. No field. Completely absent from the system.

Stage 6 — AS9102 FAR submitted
Field: MISSING
Available: NO
Computes: When the first article inspection report was sent to the customer.
Gap: No FAR tracking table. AS9102 is an external document and its submission
     is not tracked anywhere in the system.

Stage 7 — Customer acceptance
Field: PARTIAL
Available: PARTIAL (schema only, no live data)
Computes: Can approximate from orders.actual_delivery_date (when part shipped/delivered)
Gap: actual_delivery_date tracks physical delivery, not customer acceptance.
     Customer acceptance (sign-off on FAR) is a separate event not tracked.
```

### FAR Cycle Time Gap Summary

**Status: PARTIAL — only 2 of 7 stages have timestamps (job receipt, delivery).**

| Stage                  | Data Available | Source Field                     |
|------------------------|----------------|----------------------------------|
| Job received           | PARTIAL        | enquiries.submitted_at           |
| CAPP generated         | MISSING        | —                                |
| Material procured      | MISSING        | —                                |
| Machining complete     | PARTIAL        | Derivable from InfluxDB (manual) |
| QC complete            | MISSING        | —                                |
| FAR submitted          | MISSING        | —                                |
| Customer acceptance    | PARTIAL        | orders.actual_delivery_date      |

Cannot compute FAR cycle time today. Can compute an approximation of total
order-to-delivery time (enquiries.submitted_at to orders.actual_delivery_date)
once live PostgreSQL data is accessible.

---

## Section C — Other Potential Dashboard Metrics

### Computable from InfluxDB Today

```
Metric: Machine Utilization Rate
Formula: sum(cutting_time) / sum(production_time) per day
Status: COMPUTABLE (cutting_time and production_time are non-zero in cnc-data)
Notes: production_time = time machine was powered on; cutting_time = active cutting.
       Utilization = cutting_time / production_time. Available per program, per day.

Metric: Average Cycle Time per Program
Formula: mean(cycle_time) grouped by program_name per day
Status: COMPUTABLE from cnc-data-v2 (program_name is a tag for efficient grouping)
Notes: cycle_time is the elapsed program runtime. Shows machining efficiency per part.

Metric: Alarm Rate
Formula: count(alarm_active=1) / total_rows × 100 per program
Status: COMPUTABLE
Notes: alarm_active is binary (0/1). Count alarm events per session per program.
       High alarm rate for a program indicates setup or programming issues.

Metric: Feed/Spindle Override Usage
Formula: mean(feed_override), mean(spindle_override) — any value != 100 = manual override
Status: COMPUTABLE
Notes: Overrides != 100% indicate the operator manually adjusted the controller.
       Frequent large overrides may indicate incorrect cutting parameters in CAPP.

Metric: Spindle Load Profile per Program
Formula: mean/max/min(spindle_load) grouped by program_name and time window
Status: COMPUTABLE
Notes: Shows cutting intensity. Abnormally high spindle load = tool wear risk.

Metric: Programs Executed per Day
Formula: distinct count of program_name values per day
Status: COMPUTABLE from cnc-data-v2
Notes: Proxy for number of jobs started per day (not parts completed).

Metric: Machine State Distribution
Formula: time in state 0 (idle), 1 (running), 2 (MDI) per day
Status: COMPUTABLE
Notes: Time in state=1 vs 0 gives utilization. Time in state=2 = manual intervention.
```

### Computable from PostgreSQL (when live data accessible)

```
Metric: Quote-to-Order Conversion Rate
Formula: count(orders) / count(enquiries with status >= QUOTED)
Status: SCHEMA EXISTS, needs live data
Source: enquiries, orders tables

Metric: Average Enquiry Response Time (quote turnaround)
Formula: mean(time from enquiries.submitted_at to enquiry_status_history entry where to_status='QUOTED')
Status: SCHEMA EXISTS, needs live data

Metric: On-Time Delivery Rate
Formula: count(orders where actual_delivery_date <= expected_delivery_date) / count(orders)
Status: SCHEMA EXISTS, needs live data
Source: orders.expected_delivery_date, orders.actual_delivery_date

Metric: Revenue by Material / Technology
Formula: sum(orders.final_amount) grouped by material_id, processing_technology_id
Status: SCHEMA EXISTS, needs live data

Metric: Average Order Value
Formula: mean(orders.final_amount)
Status: SCHEMA EXISTS, needs live data

Metric: Customer Repeat Rate
Formula: count(customers with > 1 order) / count(distinct customers)
Status: SCHEMA EXISTS, needs live data
```

### Not Computable Today (require new capture)

```
Metric: First Pass Rate (FPR)          → requires QC module
Metric: FAR Cycle Time (full)          → requires 4 new stage timestamps
Metric: Rework Rate                    → requires QC module
Metric: Scrap Rate                     → requires QC + material tracking
Metric: Tool Life / Change Frequency   → production_count=0; needs fix
Metric: Setup Time vs. Cutting Time    → no explicit setup start/end events
```
