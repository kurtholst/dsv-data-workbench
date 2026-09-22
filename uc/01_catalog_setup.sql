-- ============================================================================
-- DSV Data Workbench — Unity Catalog setup
-- Creates the governed medallion namespace and the raw landing volume.
-- Run on the target workspace (profile: fe-bar).
-- ============================================================================

CREATE CATALOG IF NOT EXISTS dsv
  COMMENT 'DSV Parcel Express Data Workbench — governed analytics for booking volume & quality (SYNTHETIC data).';

CREATE SCHEMA IF NOT EXISTS dsv.bronze COMMENT 'Raw ingested bookings (as-landed).';
CREATE SCHEMA IF NOT EXISTS dsv.silver COMMENT 'Cleaned, typed bookings with quality flags.';
CREATE SCHEMA IF NOT EXISTS dsv.gold   COMMENT 'Business KPI marts for volume & quality analysis.';
CREATE SCHEMA IF NOT EXISTS dsv.ml     COMMENT 'ML models, features, and scored outputs.';

-- Raw landing volume for the synthetic booking JSON shards.
CREATE VOLUME IF NOT EXISTS dsv.bronze.raw_landing
  COMMENT 'Landing zone for raw Parcel Express booking files (newline-delimited JSON).';

-- ---------------------------------------------------------------------------
-- Catalog-level tags (data classification / domain metadata)
-- ---------------------------------------------------------------------------
ALTER CATALOG dsv SET TAGS ('domain' = 'supply_chain', 'lob' = 'parcel_express', 'data_class' = 'synthetic');
