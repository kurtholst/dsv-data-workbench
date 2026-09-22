# DSV Parcel Express — Data Workbench (Databricks end-to-end prototype)

A working, end-to-end Databricks prototype for **DSV**'s Parcel Express line of business,
solving their stated need for a **Data Workbench**: data exploration, ad-hoc analytics, and
historical/granular analysis for **data analysts and business users**. One unified synthetic
booking dataset powers **both** of DSV's priority areas:

- **Booking Volume Analysis** — capacity utilization, volumetric trends & seasonality, booking velocity / lead times, customer & trade-lane concentration.
- **Booking Quality Analysis** — First-Time-Right (FTR), data completeness, defect/amendment rates, electronic-integration (EDI/API vs manual) share, no-show/cancellation rates.

> All data is **synthetic** (`data_gen/generate_bookings.py`). No real customer data is used.

## The integrated data journey (6 mandated stages)

| Stage | Databricks capability | What it does here |
|---|---|---|
| **Lakeflow** | Declarative pipeline | Ingest raw booking JSON from a UC Volume → Bronze → Silver (typed + quality flags) → Gold (KPI marts) |
| **Unity Catalog** | Governance | `dsv` catalog, medallion schemas, grants, tags, a metric view, end-to-end lineage |
| **Lakebase** | Operational serving | Sync Gold serving tables to Postgres for low-latency app reads |
| **ML / GenAI** | Intelligence | (1) First-Time-Right / amendment-risk classifier (MLflow → UC model → serving endpoint). (2) `ai_query` GenAI classifier turning free-text `defect_reason` into structured defect categories + remediation |
| **Genie** | Natural language | Genie space over Gold marts; analysts ask volume & quality questions in plain English |
| **Databricks App** | Business surface | FastAPI + React app + Lakeview dashboard surfacing KPIs, ML scores, and embedded Genie |

## Repo layout

```
data_gen/     synthetic booking generator + schema + committed sample
pipelines/    Lakeflow declarative pipeline (bronze/silver/gold + KPI marts)
uc/           catalog / schema / grants / tags / metric view SQL
lakebase/     serving sync config + notes
ml/           FTR classifier training + GenAI defect classifier
genie/        Genie space instructions + committed Q&A transcript
app/          FastAPI + React Databricks App
dashboard/    Lakeview dashboard build script + definition
evidence/     COMMITTED TEXT EXECUTION EVIDENCE (read this — proves the build ran)
deck/         business presentation (Demo2Win)
```

## Execution evidence

The `evidence/` directory contains committed **text** outputs proving each stage actually ran
(pipeline row counts, Gold query results, ML metrics, GenAI outputs, Genie transcripts, app
responses). See [`evidence/README.md`](evidence/README.md) for the index.

## Reproduce

```bash
# 1. Generate synthetic raw data
python data_gen/generate_bookings.py --rows 400000 --shards 8

# 2. Land + govern (Unity Catalog), run Lakeflow pipeline, train ML, sync Lakebase,
#    create Genie space, deploy app — see each subdirectory's README / SQL.
```

Target workspace: `dbc-0e21d0b3-3b8f.cloud.databricks.com` (Unity Catalog `dsv`).
