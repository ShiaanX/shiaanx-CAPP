import requests, time, json, sys
B = "http://127.0.0.1:8790"
step = r"C:\Users\Siddhant Gupta\Documents\ShiaanX\Claude output for program sheet\Manufactured parts\Motor Mount\MOTOR MOUNT.step"
sheet = sys.argv[1]
j = requests.post(B + "/api/labeling-jobs", files={"file": ("MOTOR MOUNT.step", open(step, "rb"))}).json()
for _ in range(400):
    if j["status"] in ("completed", "failed"):
        break
    time.sleep(1.5)
    j = requests.get(f"{B}/api/labeling-jobs/{j['job_id']}").json()
print(j["status"], j.get("error"), (j.get("result") or {}).get("face_count"))
jid = j["job_id"]
s = requests.post(f"{B}/api/labeling-jobs/{jid}/dimensions/seed", files={"file": ("Motor Mount QC sheet.xlsx", open(sheet, "rb"))})
print("seed", s.status_code)
sj = s.json()
print("face_links", sj.get("face_links"))
r = requests.put(f"{B}/api/labeling-jobs/{jid}/dimensions", json={"dimensions": sj["dimensions"]})
print("PUT", r.status_code)
q = requests.post(f"{B}/api/labeling-jobs/{jid}/qc-results", files={"file": ("Motor Mount QC sheet.xlsx", open(sheet, "rb"))})
print("qc", q.status_code)
d = requests.get(f"{B}/api/labeling-jobs/{jid}/dimensions").json()
print("tagged", d["tagged_count"], "of", d["dimension_count"])
v = requests.get(f"{B}/api/labeling-jobs/{jid}/qc-results").json()
print(v["summary"])
for x in v["results"]:
    print(x["balloon"], x["dim_type"], x["nominal"], x["faces_a"], x["faces_b"], len(x["readings"]), x["verdict"], x.get("worst_reading"), "remark_disagrees" if x["remark_disagrees"] else "")
for p in ("inspection", "dimensions"):
    print(p, requests.get(f"{B}/{p}?job={jid}&embed=1").status_code)
