"""
Build two Lakeview dashboards for the DSV Data Workbench:
  1. Booking QUALITY  — FTR, automation share, defects, amendments, no-shows
  2. Booking VOLUME   — capacity, seasonality, lanes, booking velocity

Uses the fe-databricks-tools lakeview_builder helper. Deploys via the Lakeview API
(profile fe-bar). Prints the created dashboard IDs/URLs.
"""
import os, sys, json, subprocess

SKILL = "/Users/kurt.holst/.vibe/marketplace/plugins/fe-databricks-tools/skills/databricks-lakeview-dashboard/resources"
sys.path.insert(0, SKILL)
from lakeview_builder import LakeviewDashboard  # noqa: E402

PROFILE = "fe-bar"
WAREHOUSE = "74ec803467a6bcfb"
PARENT = "/Workspace/Users/kurt.holst@databricks.com"
HOST = "https://dbc-0e21d0b3-3b8f.cloud.databricks.com"


def _fix_table_widgets(dash: LakeviewDashboard) -> str:
    """The builder emits table widgets as version 1; the current Lakeview schema
    requires version 2 with an `allowHTMLByDefault` property, otherwise the widget
    is rejected as an invalid definition. Patch tables before serializing."""
    sd = dash.to_dict()
    for page in sd.get("pages", []):
        for w in page.get("layout", []):
            spec = w.get("widget", {}).get("spec", {})
            if spec.get("widgetType") == "table":
                spec["version"] = 2
                spec.setdefault("allowHTMLByDefault", False)
    return json.dumps(sd)


def deploy(dash: LakeviewDashboard, display_name: str) -> str:
    body = {
        "display_name": display_name,
        "warehouse_id": WAREHOUSE,
        "parent_path": PARENT,
        "serialized_dashboard": _fix_table_widgets(dash),
    }
    p = "/tmp/_lv_body.json"
    open(p, "w").write(json.dumps(body))
    out = subprocess.run(
        ["databricks", "api", "post", "/api/2.0/lakeview/dashboards",
         "--profile", PROFILE, "--json", f"@{p}"],
        capture_output=True, text=True)
    if out.returncode != 0:
        print("ERROR:", out.stderr[:800]); return ""
    d = json.loads(out.stdout)
    did = d.get("dashboard_id", "")
    # publish it
    subprocess.run(["databricks", "api", "post",
                    f"/api/2.0/lakeview/dashboards/{did}/published",
                    "--profile", PROFILE, "--json", json.dumps({"warehouse_id": WAREHOUSE})],
                   capture_output=True, text=True)
    print(f"{display_name}: {HOST}/dashboardsv3/{did}")
    return did


# =====================================================================
# 1) QUALITY dashboard
# =====================================================================
qd = LakeviewDashboard("DSV Booking Quality")

qd.add_dataset("summary", "Summary",
    "SELECT round(avg(first_time_right::int),4) AS ftr_rate, "
    "round(avg(is_electronic::int),4) AS automation_share, "
    "round(avg((amendment_count>0)::int),4) AS amendment_rate, "
    "round(avg(no_show::int),4) AS no_show_rate "
    "FROM dsv.silver.bookings_clean")
qd.add_dataset("by_channel", "By channel", "SELECT * FROM dsv.gold.quality_by_channel")
qd.add_dataset("trend", "Monthly trend",
    "SELECT booking_month, ftr_rate, electronic_share, no_show_rate FROM dsv.gold.quality_monthly_trend")
qd.add_dataset("completeness", "Completeness",
    "SELECT channel, rate_missing_address, rate_missing_customs_doc, rate_wrong_weight, "
    "rate_missing_service_code FROM dsv.gold.completeness_breakdown")
qd.add_dataset("defects", "GenAI defects",
    "SELECT defect_category, count(*) AS n FROM dsv.gold.defect_classification_flat GROUP BY defect_category")

qd.add_counter("summary", "ftr_rate", "SUM", "First-Time-Right rate", {"x": 0, "y": 0, "width": 2, "height": 3})
qd.add_counter("summary", "automation_share", "SUM", "Automation share", {"x": 2, "y": 0, "width": 2, "height": 3})
qd.add_counter("summary", "no_show_rate", "SUM", "No-show rate", {"x": 4, "y": 0, "width": 2, "height": 3})
qd.add_bar_chart("by_channel", "channel", "ftr_rate", "SUM", "FTR rate by channel",
                 {"x": 0, "y": 3, "width": 3, "height": 6})
qd.add_line_chart("trend", "booking_month", "ftr_rate", "SUM", None, "FTR rate over time",
                  {"x": 3, "y": 3, "width": 3, "height": 6})
qd.add_bar_chart("defects", "defect_category", "n", "SUM", "GenAI defect categories",
                 {"x": 0, "y": 9, "width": 3, "height": 6})
qd.add_bar_chart("completeness", "channel", "rate_missing_customs_doc", "SUM",
                 "Missing customs docs by channel", {"x": 3, "y": 9, "width": 3, "height": 6})
qd.add_table("by_channel", [
    {"field": "channel", "title": "Channel"},
    {"field": "bookings", "title": "Bookings", "type": "integer"},
    {"field": "ftr_rate", "title": "FTR", "type": "float"},
    {"field": "amendment_rate", "title": "Amendment rate", "type": "float"},
    {"field": "no_show_rate", "title": "No-show rate", "type": "float"},
], "Quality by channel (detail)", {"x": 0, "y": 15, "width": 6, "height": 6})

# =====================================================================
# 2) VOLUME dashboard
# =====================================================================
vd = LakeviewDashboard("DSV Booking Volume")

vd.add_dataset("summary", "Summary",
    "SELECT count(*) AS bookings, round(sum(weight_kg),0) AS total_weight_kg, "
    "round(avg(lead_time_days),2) AS avg_lead_time FROM dsv.silver.bookings_clean")
vd.add_dataset("by_mode_day", "Daily by mode", "SELECT * FROM dsv.gold.volume_daily_by_mode")
vd.add_dataset("lanes", "Top lanes",
    "SELECT lane, sum(bookings) AS bookings, round(sum(total_weight_kg),0) AS total_weight_kg "
    "FROM dsv.gold.lane_concentration GROUP BY lane ORDER BY bookings DESC LIMIT 12")
vd.add_dataset("velocity", "Velocity",
    "SELECT lead_bucket, sum(bookings) AS bookings FROM dsv.gold.booking_velocity GROUP BY lead_bucket ORDER BY lead_bucket")
vd.add_dataset("mode_month", "Monthly by mode",
    "SELECT date_trunc('MONTH', booking_date) AS booking_month, mode, sum(bookings) AS bookings "
    "FROM dsv.gold.volume_daily_by_mode GROUP BY 1, 2")

vd.add_counter("summary", "bookings", "SUM", "Total bookings", {"x": 0, "y": 0, "width": 2, "height": 3})
vd.add_counter("summary", "total_weight_kg", "SUM", "Total weight (kg)", {"x": 2, "y": 0, "width": 2, "height": 3})
vd.add_counter("summary", "avg_lead_time", "SUM", "Avg lead time (days)", {"x": 4, "y": 0, "width": 2, "height": 3})
vd.add_line_chart("mode_month", "booking_month", "bookings", "SUM", None, "Monthly volume by mode",
                  {"x": 0, "y": 3, "width": 6, "height": 6}, color_field="mode")
vd.add_bar_chart("lanes", "lane", "bookings", "SUM", "Top trade lanes by volume",
                 {"x": 0, "y": 9, "width": 3, "height": 6})
vd.add_bar_chart("velocity", "lead_bucket", "bookings", "SUM", "Booking velocity (lead-time buckets)",
                 {"x": 3, "y": 9, "width": 3, "height": 6})
vd.add_table("lanes", [
    {"field": "lane", "title": "Lane"},
    {"field": "bookings", "title": "Bookings", "type": "integer"},
    {"field": "total_weight_kg", "title": "Total weight (kg)", "type": "float"},
], "Top lanes (detail)", {"x": 0, "y": 15, "width": 6, "height": 6})


if __name__ == "__main__":
    qid = deploy(qd, "DSV Booking Quality")
    vid = deploy(vd, "DSV Booking Volume")
    print(json.dumps({"quality_dashboard_id": qid, "volume_dashboard_id": vid}))
