import requests
import json
import warnings
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

BASE = "https://8j1moabvym-aoe5tdinruw5gy.timestream-influxdb.ap-south-1.on.aws:8086"

def get_session():
    r = requests.post(f"{BASE}/api/v2/signin", auth=("admin", "admin123"), verify=False)
    r.raise_for_status()
    return r.cookies.get("influxdb-oss-session")

def flux_query(session, query):
    cookies = {"influxdb-oss-session": session}
    headers = {"Content-Type": "application/vnd.flux", "Accept": "application/csv"}
    r = requests.post(f"{BASE}/api/v2/query?org=cnc-org",
                      headers=headers, cookies=cookies, data=query, verify=False)
    if r.status_code == 401:
        session = get_session()
        cookies = {"influxdb-oss-session": session}
        r = requests.post(f"{BASE}/api/v2/query?org=cnc-org",
                          headers=headers, cookies=cookies, data=query, verify=False)
    return r.text, session

print("Authenticating to InfluxDB...")
session = get_session()
print(f"Session obtained: {session[:20]}...")

# 1. Row counts per field in cnc-data
print("\n=== ROW COUNTS (cnc-data) ===")
result, session = flux_query(session, """
from(bucket: "cnc-data") |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "cnc_telemetry")
  |> count() |> limit(n: 30)
""")
print(result)

# 2. Sample 5 rows of recent data
print("\n=== SAMPLE ROWS (last 7 days) ===")
result, session = flux_query(session, """
from(bucket: "cnc-data") |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "cnc_telemetry")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> limit(n: 5)
""")
print(result)

# 3. Unique program names
print("\n=== UNIQUE PROGRAMS ===")
result, session = flux_query(session, """
from(bucket: "cnc-data") |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "cnc_telemetry" and r._field == "program_name")
  |> distinct(column: "_value") |> limit(n: 50)
""")
print(result)

# 4. Oldest record
print("\n=== OLDEST RECORD ===")
result, session = flux_query(session, """
from(bucket: "cnc-data") |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "cnc_telemetry" and r._field == "cycle_time")
  |> first()
""")
print(result)

# 5. Newest record
print("\n=== NEWEST RECORD ===")
result, session = flux_query(session, """
from(bucket: "cnc-data") |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "cnc_telemetry" and r._field == "cycle_time")
  |> last()
""")
print(result)

# 6. Unique tool names
print("\n=== UNIQUE TOOL NAMES ===")
result, session = flux_query(session, """
from(bucket: "cnc-data") |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "cnc_telemetry" and r._field == "tool_name")
  |> distinct(column: "_value") |> limit(n: 50)
""")
print(result)

# 7. Unique machine_state values
print("\n=== UNIQUE MACHINE STATES ===")
result, session = flux_query(session, """
from(bucket: "cnc-data") |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "cnc_telemetry" and r._field == "machine_state")
  |> distinct(column: "_value") |> limit(n: 20)
""")
print(result)

# 8. Unique alarm_active values
print("\n=== UNIQUE ALARM VALUES ===")
result, session = flux_query(session, """
from(bucket: "cnc-data") |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "cnc_telemetry" and r._field == "alarm_active")
  |> distinct(column: "_value") |> limit(n: 10)
""")
print(result)

# 9. Machine mode values
print("\n=== UNIQUE MACHINE MODES ===")
result, session = flux_query(session, """
from(bucket: "cnc-data") |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "cnc_telemetry" and r._field == "machine_mode")
  |> distinct(column: "_value") |> limit(n: 10)
""")
print(result)

# 10. Production count range
print("\n=== PRODUCTION COUNT (min/max) ===")
result, session = flux_query(session, """
from(bucket: "cnc-data") |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "cnc_telemetry" and r._field == "production_count")
  |> min()
""")
print("MIN:", result)
result, session = flux_query(session, """
from(bucket: "cnc-data") |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "cnc_telemetry" and r._field == "production_count")
  |> max()
""")
print("MAX:", result)

# 11. cnc-data-v2 bucket
print("\n=== ROW COUNTS (cnc-data-v2) ===")
result, session = flux_query(session, """
from(bucket: "cnc-data-v2") |> range(start: 0)
  |> filter(fn: (r) => r._measurement == "cnc_telemetry")
  |> count() |> limit(n: 5)
""")
print(result)

# 12. List all buckets
print("\n=== ALL BUCKETS ===")
cookies = {"influxdb-oss-session": session}
r = requests.get(f"{BASE}/api/v2/buckets?org=cnc-org", cookies=cookies, verify=False)
print(json.dumps(r.json(), indent=2))
