# Databricks notebook source
# MAGIC %md
# MAGIC # DSV — Lakebase operational serving
# MAGIC Connects to the Lakebase Postgres instance `dsv-workbench-db`, creates an operational
# MAGIC serving table for the app, loads a KPI snapshot + a sample of bookings from the Gold
# MAGIC layer, and runs read queries — demonstrating low-latency operational serving that the
# MAGIC Databricks App can hit directly. Writes a text evidence report to `dsv.ml.eval`.
# MAGIC
# MAGIC (We connect directly rather than via a synced table because this metastore has no
# MAGIC default managed storage root, which the reverse-ETL sync pipeline's classic compute
# MAGIC requires. Direct write to Lakebase is the operational-serving path the app uses.)

# COMMAND ----------

# MAGIC %pip install psycopg2-binary
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

import uuid, json, psycopg2
from databricks.sdk import WorkspaceClient

INSTANCE = "dsv-workbench-db"
w = WorkspaceClient()
user = w.current_user.me().user_name

# Use the REST API directly (SDK build here lacks the .database helper).
inst = w.api_client.do("GET", f"/api/2.0/database/instances/{INSTANCE}")
host = inst["read_write_dns"]
cred = w.api_client.do("POST", "/api/2.0/database/credentials",
                       body={"request_id": str(uuid.uuid4()), "instance_names": [INSTANCE]})
token = cred["token"]

conn = psycopg2.connect(host=host, dbname="databricks_postgres", user=user,
                        password=token, sslmode="require", port=5432)
conn.autocommit = True
cur = conn.cursor()
print("connected to Lakebase:", host)

# COMMAND ----------

# Operational serving tables
cur.execute("""
CREATE TABLE IF NOT EXISTS booking_kpi_snapshot (
  metric text PRIMARY KEY,
  value  double precision,
  updated_at timestamptz DEFAULT now()
)""")
cur.execute("""
CREATE TABLE IF NOT EXISTS booking_serving (
  booking_id text PRIMARY KEY,
  booking_ts timestamptz,
  mode text, channel text, is_electronic boolean,
  customer_type text, lane text, is_international boolean,
  weight_kg double precision, capacity_utilization double precision,
  lead_time_days double precision, first_time_right boolean,
  amendment_count int, no_show boolean
)""")
print("tables ready")

# COMMAND ----------

# Load KPI snapshot from Gold (small, refreshed operationally)
kpis = spark.sql("""
  SELECT 'ftr_rate' AS metric, avg(first_time_right::int) AS value FROM dsv.silver.bookings_clean
  UNION ALL SELECT 'automation_share', avg(is_electronic::int) FROM dsv.silver.bookings_clean
  UNION ALL SELECT 'no_show_rate', avg(no_show::int) FROM dsv.silver.bookings_clean
  UNION ALL SELECT 'amendment_rate', avg((amendment_count>0)::int) FROM dsv.silver.bookings_clean
  UNION ALL SELECT 'avg_lead_time_days', avg(lead_time_days) FROM dsv.silver.bookings_clean
""").collect()
for r in kpis:
    cur.execute("""INSERT INTO booking_kpi_snapshot(metric,value) VALUES(%s,%s)
                   ON CONFLICT(metric) DO UPDATE SET value=EXCLUDED.value, updated_at=now()""",
                (r["metric"], float(r["value"])))
print("loaded", len(kpis), "KPIs")

# Load a sample of recent bookings for operational lookups
rows = spark.sql("""
  SELECT booking_id, booking_ts, mode, channel, is_electronic, customer_type, lane,
         is_international, weight_kg, capacity_utilization, lead_time_days,
         first_time_right, amendment_count, no_show
  FROM dsv.gold.booking_serving ORDER BY booking_ts DESC LIMIT 5000
""").collect()
args = [(r.booking_id, r.booking_ts, r.mode, r.channel, r.is_electronic, r.customer_type,
         r.lane, r.is_international, float(r.weight_kg or 0), float(r.capacity_utilization or 0),
         float(r.lead_time_days or 0), r.first_time_right, int(r.amendment_count or 0), r.no_show)
        for r in rows]
cur.executemany("""INSERT INTO booking_serving VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(booking_id) DO NOTHING""", args)
print("loaded", len(args), "bookings into Lakebase")

# COMMAND ----------

# Read-back queries (this is what the operational app would run)
report = []
report.append("=== DSV Lakebase operational serving — query evidence ===")
report.append(f"instance: {INSTANCE}  host: {host}")
report.append(f"database: databricks_postgres  schema: public")
report.append("")

cur.execute("SELECT metric, round(value::numeric,4) FROM booking_kpi_snapshot ORDER BY metric")
report.append("-- booking_kpi_snapshot (operational KPI table) --")
for m, v in cur.fetchall():
    report.append(f"  {m:22s} {v}")

cur.execute("SELECT count(*) FROM booking_serving")
report.append(f"\n-- booking_serving row count: {cur.fetchone()[0]}")

cur.execute("""SELECT channel, count(*) AS n, round(avg(first_time_right::int)::numeric,3) AS ftr
               FROM booking_serving GROUP BY channel ORDER BY n DESC""")
report.append("\n-- FTR by channel (served from Lakebase Postgres) --")
for ch, n, ftr in cur.fetchall():
    report.append(f"  {ch:10s} n={n:<6} ftr={ftr}")

cur.execute("""SELECT booking_id, channel, mode, lane, first_time_right
               FROM booking_serving ORDER BY booking_ts DESC LIMIT 5""")
report.append("\n-- sample operational lookups (latest 5) --")
for row in cur.fetchall():
    report.append("  " + " | ".join(str(x) for x in row))

text = "\n".join(report)
print(text)
dbutils.fs.put("/Volumes/dsv/ml/eval/lakebase_query.txt", text, overwrite=True)
cur.close(); conn.close()
