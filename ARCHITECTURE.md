# Architecture — DSV Parcel Express Data Workbench

An integrated, end-to-end data journey on Databricks. Every stage feeds the next; nothing is
siloed. All data is synthetic.

```
                        ┌─────────────────────────────────────────────────────────────┐
                        │                       UNITY CATALOG (govern)                 │
                        │   catalog `dsv`  ·  grants  ·  tags  ·  lineage  ·  metric    │
                        └─────────────────────────────────────────────────────────────┘
                                   ▲            ▲             ▲              ▲
 raw JSON            LAKEFLOW      │            │             │              │
 (synthetic)        declarative   │            │             │              │
 400k bookings  ─▶  pipeline  ─▶  Bronze  ─▶  Silver  ─▶   Gold marts  ─┬─▶ GENIE (NL Q&A)
 in UC Volume       (Auto Loader, (raw)    (typed +      (7 KPI marts:  │   analysts ask in
                     DQ expects)            quality       volume +      │   plain English
                                            flags)        quality)      │
                                                             │          ├─▶ LAKEBASE (serve)
                                                             │          │   Postgres operational
                                                             │          │   tables, low-latency
                                                             ▼          │
                                                    ML + GenAI (intelligence)   │
                                            ┌──────────────────────────────┐    │
                                            │ FTR risk classifier           │   │
                                            │  MLflow → UC model → serving   │   │
                                            │ GenAI defect classifier        │   │
                                            │  ai_query (Claude) categories  │   │
                                            └──────────────────────────────┘    │
                                                             │                   │
                                                             ▼                   ▼
                        ┌─────────────────────────────────────────────────────────────┐
                        │        DATABRICKS APP (FastAPI) + 2 LAKEVIEW DASHBOARDS       │
                        │   KPIs · quality/volume analytics · live ML what-if · Genie   │
                        │   Booking Quality dashboard  ·  Booking Volume dashboard      │
                        └─────────────────────────────────────────────────────────────┘
```

## Stage detail

| Stage | Object(s) | Notes |
|---|---|---|
| Lakeflow | pipeline `dsv-bookings-medallion` | Serverless declarative pipeline. Bronze via `read_files` Auto Loader; Silver materialized view with `EXPECT` data-quality constraints; 7 Gold marts. |
| Unity Catalog | catalog `dsv`; schemas `bronze/silver/gold/ml`; volume `bronze.raw_landing` | Catalog tags (`domain=operations`, `lob=parcel_express`); column tags marking quality vs volume fields; grants to analysts + the app service principal. |
| Lakebase | instance `dsv-workbench-db`, db `databricks_postgres` | Operational serving. Postgres tables `booking_kpi_snapshot` + `booking_serving` loaded from Gold; the app reads these for low-latency KPIs/lookups. |
| ML | `dsv.ml.ftr_risk_classifier` (UC model) + serving endpoint `dsv-ftr-risk` | LogisticRegression on booking-time features; scores First-Time-Right risk so risky bookings get pre-emptive checks (DSV "AI factory"). |
| GenAI | `dsv.gold.defect_classification[_flat]` | `ai_query('databricks-claude-sonnet-4-6', …)` classifies free-text defect reasons into categories + remediation. |
| Genie | space `01f1b68e95721a3794aeba7cf820b791` | Curated instructions + example SQL over the Gold marts; analysts ask volume & quality questions in NL. |
| App + BI | app `dsv-workbench`; dashboards Quality + Volume | FastAPI app surfaces KPIs, quality/volume analytics, live ML what-if scoring, and links to Genie; two published Lakeview dashboards. |

## Why these choices
- **One unified dataset** answers both Booking Volume and Booking Quality, matching DSV's ask for a single Data Workbench rather than two siloed tools.
- **Medallion + DQ expectations** give analysts trustworthy granular and historical data for ad-hoc analysis.
- **ML + GenAI on the same governed tables** turn analytics into action (route risky bookings, categorize defects) without moving data.
- **Genie + App** serve the two personas in the brief: data analysts (NL exploration, granular drill-down) and business users (dashboards, KPIs).
