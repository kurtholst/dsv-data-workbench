"""
DSV Parcel Express — Data Workbench app (FastAPI).

Surfaces the governed Gold marts to business users and analysts:
  * KPI header (FTR, automation share, no-show rate, avg lead time)
  * Quality-by-channel, monthly trend, lane concentration, completeness
  * GenAI defect categories
  * Live ML scoring (First-Time-Right risk) for a what-if booking
  * Link into the Genie space for natural-language exploration

Runs both locally (profile auth) and as a Databricks App (WorkspaceClient auto-auth).
Reads via the SQL warehouse Statement Execution API (Gold marts / synced serving tables).
"""
from __future__ import annotations

import json
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from config import (CATALOG, GENIE_SPACE_ID, GOLD, ML_ENDPOINT, SILVER,
                    WAREHOUSE_ID, get_workspace_client)

app = FastAPI(title="DSV Parcel Express — Data Workbench")
_w = None


def w():
    global _w
    if _w is None:
        _w = get_workspace_client()
    return _w


def q(sql: str) -> list[dict[str, Any]]:
    """Run SQL on the warehouse and return list-of-dicts."""
    resp = w().statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=sql, wait_timeout="50s")
    # poll if needed
    import time
    from databricks.sdk.service.sql import StatementState
    while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(1)
        resp = w().statement_execution.get_statement(resp.statement_id)
    if resp.status.state != StatementState.SUCCEEDED:
        raise HTTPException(500, f"SQL failed: {resp.status.error}")
    cols = [c.name for c in resp.manifest.schema.columns]
    rows = resp.result.data_array or []
    return [dict(zip(cols, r)) for r in rows]


@app.get("/healthz")
def healthz():
    return {"status": "ok", "catalog": CATALOG}


@app.get("/api/summary")
def summary():
    rows = q(f"""
        SELECT
          count(*)                              AS bookings,
          round(avg(first_time_right::int), 4)  AS ftr_rate,
          round(avg(is_electronic::int), 4)     AS automation_share,
          round(avg(no_show::int), 4)           AS no_show_rate,
          round(avg((amendment_count>0)::int),4) AS amendment_rate,
          round(avg(lead_time_days), 2)         AS avg_lead_time_days
        FROM {SILVER}.bookings_clean
    """)
    return rows[0] if rows else {}


@app.get("/api/quality_by_channel")
def quality_by_channel():
    return q(f"SELECT * FROM {GOLD}.quality_by_channel ORDER BY ftr_rate DESC")


@app.get("/api/monthly_trend")
def monthly_trend():
    return q(f"SELECT * FROM {GOLD}.quality_monthly_trend ORDER BY booking_month")


@app.get("/api/top_lanes")
def top_lanes():
    return q(f"SELECT lane, mode, bookings, total_weight_kg, ftr_rate, avg_lead_time_days "
             f"FROM {GOLD}.lane_concentration ORDER BY bookings DESC LIMIT 15")


@app.get("/api/completeness")
def completeness():
    return q(f"SELECT * FROM {GOLD}.completeness_breakdown ORDER BY channel")


@app.get("/api/defect_categories")
def defect_categories():
    try:
        return q(f"SELECT defect_category, count(*) AS n FROM {GOLD}.defect_classification_flat "
                 f"GROUP BY defect_category ORDER BY n DESC")
    except Exception:
        return []


@app.get("/api/score")
def score(channel: str = "FAX_OCR", mode: str = "AIR", customer_type: str = "HEALTHCARE",
          origin_hub: str = "FRA", destination_hub: str = "JFK", service_code: str = "EXP-12",
          lead_time_days: float = 1.0, weight_kg: float = 12.0, volume_m3: float = 0.08,
          capacity_utilization: float = 0.5, is_international: int = 1):
    """Live First-Time-Right risk score for a what-if booking via the ML serving endpoint."""
    payload = {"dataframe_records": [{
        "mode": mode, "channel": channel, "customer_type": customer_type,
        "origin_hub": origin_hub, "destination_hub": destination_hub,
        "service_code": service_code, "lead_time_days": lead_time_days,
        "weight_kg": weight_kg, "volume_m3": volume_m3,
        "capacity_utilization": capacity_utilization, "is_international": is_international,
    }]}
    try:
        resp = w().serving_endpoints.query(name=ML_ENDPOINT, dataframe_records=payload["dataframe_records"])
        preds = resp.predictions
        return {"needs_correction_risk": preds, "input": payload["dataframe_records"][0]}
    except Exception as e:
        raise HTTPException(500, f"scoring failed: {e}")


@app.get("/api/genie")
def genie_link():
    host = os.environ.get("DATABRICKS_HOST", "")
    return {"space_id": GENIE_SPACE_ID,
            "url": f"{host}/genie/rooms/{GENIE_SPACE_ID}" if GENIE_SPACE_ID else ""}


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_PAGE


# Minimal self-contained dashboard (no build step needed for the App).
HTML_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>DSV Parcel Express — Data Workbench</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--navy:#0a1f44;--orange:#e8590c;--ink:#0f172a;--muted:#64748b;--bg:#f6f8fb;--card:#fff;--line:#e2e8f0}
*{box-sizing:border-box}body{margin:0;font-family:'DM Sans',system-ui,sans-serif;background:var(--bg);color:var(--ink)}
header{background:var(--navy);color:#fff;padding:18px 28px;display:flex;align-items:center;gap:14px}
header h1{font-size:18px;margin:0;font-weight:600}header .tag{background:var(--orange);padding:2px 10px;border-radius:12px;font-size:12px}
.wrap{max-width:1180px;margin:0 auto;padding:22px}
.kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:20px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.kpi .v{font-size:24px;font-weight:700;color:var(--navy)}.kpi .l{font-size:12px;color:var(--muted);margin-top:4px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
.card h3{margin:0 0 10px;font-size:14px;color:var(--navy)}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600}.bar{height:8px;background:var(--orange);border-radius:4px}
.score{display:flex;gap:8px;align-items:center;flex-wrap:wrap}select,input{padding:6px;border:1px solid var(--line);border-radius:8px}
button{background:var(--orange);color:#fff;border:0;padding:8px 16px;border-radius:8px;cursor:pointer;font-weight:600}
.risk{font-size:28px;font-weight:800}a.genie{color:var(--orange);font-weight:600;text-decoration:none}
.small{font-size:12px;color:var(--muted)}
</style></head><body>
<header><h1>DSV Parcel Express · Data Workbench</h1><span class="tag">SYNTHETIC</span>
<span class="small" style="color:#cbd5e1;margin-left:auto">Booking Volume + Quality · Databricks</span></header>
<div class="wrap">
  <div class="kpis" id="kpis"></div>
  <div class="grid">
    <div class="card"><h3>First-Time-Right by channel</h3><table id="chan"></table></div>
    <div class="card"><h3>Top trade lanes by volume</h3><table id="lanes"></table></div>
  </div>
  <div class="card"><h3>Monthly quality trend (FTR & automation share)</h3><table id="trend"></table></div>
  <div class="grid">
    <div class="card"><h3>GenAI defect categories</h3><table id="defects"></table>
      <div class="small">Free-text defect reasons classified by Foundation Model (ai_query).</div></div>
    <div class="card"><h3>Live ML — First-Time-Right risk (what-if)</h3>
      <div class="score">
        <select id="channel"><option>FAX_OCR</option><option>EMAIL</option><option>PORTAL</option><option>API</option><option>EDI</option></select>
        <select id="mode"><option>AIR</option><option>OCEAN</option><option>ROAD</option></select>
        <select id="ctype"><option>HEALTHCARE</option><option>SPARE_PARTS</option><option>SAMPLES</option><option>PRODUCTION</option></select>
        <button onclick="scoreIt()">Score booking</button>
      </div>
      <div id="riskout" style="margin-top:14px"></div>
      <div class="small">Model: dsv.ml.ftr_risk_classifier via serving endpoint.</div>
    </div>
  </div>
  <div class="card"><h3>Natural-language exploration</h3>
    <div id="genie">Analysts can ask questions in plain English in the Genie space.</div></div>
</div>
<script>
const pct=x=>x==null?'-':(100*x).toFixed(1)+'%';
async function j(u){const r=await fetch(u);return r.json()}
async function load(){
  const s=await j('/api/summary');
  document.getElementById('kpis').innerHTML=[
    ['FTR rate',pct(s.ftr_rate)],['Automation share',pct(s.automation_share)],
    ['No-show rate',pct(s.no_show_rate)],['Amendment rate',pct(s.amendment_rate)],
    ['Avg lead time',s.avg_lead_time_days+'d'],['Bookings',Number(s.bookings).toLocaleString()]
  ].map(k=>`<div class="kpi"><div class="v">${k[1]}</div><div class="l">${k[0]}</div></div>`).join('');

  const ch=await j('/api/quality_by_channel');
  document.getElementById('chan').innerHTML='<tr><th>Channel</th><th>Bookings</th><th>FTR</th><th>Amend</th><th>No-show</th></tr>'+
    ch.map(r=>`<tr><td>${r.channel}</td><td>${Number(r.bookings).toLocaleString()}</td><td>${pct(+r.ftr_rate)}</td><td>${pct(+r.amendment_rate)}</td><td>${pct(+r.no_show_rate)}</td></tr>`).join('');

  const ln=await j('/api/top_lanes');
  document.getElementById('lanes').innerHTML='<tr><th>Lane</th><th>Mode</th><th>Bookings</th><th>FTR</th></tr>'+
    ln.map(r=>`<tr><td>${r.lane}</td><td>${r.mode}</td><td>${Number(r.bookings).toLocaleString()}</td><td>${pct(+r.ftr_rate)}</td></tr>`).join('');

  const tr=await j('/api/monthly_trend');
  document.getElementById('trend').innerHTML='<tr><th>Month</th><th>Bookings</th><th>FTR</th><th>Automation</th><th>No-show</th></tr>'+
    tr.map(r=>`<tr><td>${(r.booking_month||'').slice(0,10)}</td><td>${Number(r.bookings).toLocaleString()}</td><td>${pct(+r.ftr_rate)}</td><td>${pct(+r.electronic_share)}</td><td>${pct(+r.no_show_rate)}</td></tr>`).join('');

  const df=await j('/api/defect_categories');
  document.getElementById('defects').innerHTML= df.length? '<tr><th>Category</th><th>Count</th></tr>'+
    df.map(r=>`<tr><td>${r.defect_category}</td><td>${r.n}</td></tr>`).join('') : '<tr><td class="small">Run the GenAI classifier to populate.</td></tr>';

  const g=await j('/api/genie');
  if(g.url) document.getElementById('genie').innerHTML=`<a class="genie" href="${g.url}" target="_blank">Open the DSV Genie space →</a>`;
}
async function scoreIt(){
  const c=channel.value,m=mode.value,ct=ctype.value;
  const r=await j(`/api/score?channel=${c}&mode=${m}&customer_type=${ct}`);
  let risk=Array.isArray(r.needs_correction_risk)?r.needs_correction_risk[0]:r.needs_correction_risk;
  if(typeof risk==='object') risk=risk.needs_correction??risk['1']??risk['0'];
  const flagged=(+risk)>=1||(+risk)>=0.5;
  const label=flagged?'FLAG for pre-check':'Likely first-time-right';
  const color=flagged?'#FF3621':'#00A972';
  document.getElementById('riskout').innerHTML=`<div class="risk" style="color:${color}">${label}</div>`
    +`<div class="small">Model dsv.ml.ftr_risk_classifier scored this ${c}/${m}/${ct} booking.</div>`;
}
load();
</script></body></html>"""
