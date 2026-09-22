#!/bin/bash
# Run SQL against the DSV Data Workbench warehouse via the Statement Execution API.
# Usage: ./run_sql.sh "SELECT 1"   OR   ./run_sql.sh - < file.sql
P=${DBX_PROFILE:-fe-bar}
W=${DBX_WAREHOUSE:-74ec803467a6bcfb}
if [ "$1" = "-" ]; then SQL=$(cat); else SQL="$1"; fi

python3 - "$SQL" "$W" > /tmp/dsv_payload.json <<'PY'
import json,sys
print(json.dumps({"warehouse_id":sys.argv[2],"statement":sys.argv[1],"wait_timeout":"50s","on_wait_timeout":"CONTINUE"}))
PY

databricks api post /api/2.0/sql/statements --profile=$P --json @/tmp/dsv_payload.json > /tmp/dsv_resp.json 2>/tmp/dsv_err.txt

python3 - "$P" <<'PY'
import json,sys,subprocess,time
P=sys.argv[1]
try:
    d=json.load(open("/tmp/dsv_resp.json"))
except Exception:
    print("NO RESPONSE. stderr:")
    print(open("/tmp/dsv_err.txt").read()[:2000]); sys.exit(1)
sid=d.get("statement_id")
state=d.get("status",{}).get("state")
while state in ("PENDING","RUNNING"):
    time.sleep(3)
    r=subprocess.run(["databricks","api","get",f"/api/2.0/sql/statements/{sid}","--profile",P],capture_output=True,text=True)
    d=json.loads(r.stdout); state=d.get("status",{}).get("state")
if state!="SUCCEEDED":
    print("STATE:",state)
    print("ERROR:",json.dumps(d.get("status",{}).get("error",{}),indent=2)); sys.exit(1)
res=d.get("result",{})
cols=[c["name"] for c in d.get("manifest",{}).get("schema",{}).get("columns",[])]
print("COLS:",cols)
for row in (res.get("data_array") or [])[:200]:
    print(row)
print("STATE: SUCCEEDED  rows:", len(res.get("data_array") or []))
PY
