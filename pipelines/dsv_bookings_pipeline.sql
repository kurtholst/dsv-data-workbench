-- ============================================================================
-- DSV Data Workbench — Lakeflow Declarative Pipeline (SQL)
-- Ingest raw booking JSON from the UC Volume, then build the medallion layers
-- with data-quality expectations. Target catalog: dsv.
--
-- Bronze : raw_bookings         (streaming ingest from /Volumes/dsv/bronze/raw_landing)
-- Silver : bookings_clean       (typed + derived quality/volume fields + expectations)
-- Gold   : several KPI marts for Booking Volume + Booking Quality analysis
-- ============================================================================

-- ---------------------------------------------------------------------------
-- BRONZE — stream raw JSON shards exactly as landed (Auto Loader)
-- ---------------------------------------------------------------------------
CREATE OR REFRESH STREAMING TABLE bronze.raw_bookings
  COMMENT 'Raw Parcel Express bookings as landed (newline-delimited JSON).'
AS
SELECT
  *,
  _metadata.file_name              AS _source_file,
  current_timestamp()              AS _ingest_ts
FROM STREAM read_files(
  '/Volumes/dsv/bronze/raw_landing/',
  format => 'json'
);

-- ---------------------------------------------------------------------------
-- SILVER — typed, cleaned, with derived analysis fields + DQ expectations
-- ---------------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW silver.bookings_clean (
  CONSTRAINT valid_booking_id   EXPECT (booking_id IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT valid_timestamps   EXPECT (departure_ts >= booking_ts),
  CONSTRAINT non_negative_weight EXPECT (weight_kg >= 0)
)
  COMMENT 'Cleaned, typed bookings with derived quality & volume fields.'
AS
SELECT
  booking_id,
  CAST(booking_ts   AS TIMESTAMP)                          AS booking_ts,
  CAST(departure_ts AS TIMESTAMP)                          AS departure_ts,
  CAST(lead_time_days AS DOUBLE)                           AS lead_time_days,
  mode,
  channel,
  -- automation flag: EDI/API are electronically integrated, others are manual
  CASE WHEN channel IN ('API','EDI') THEN true ELSE false END AS is_electronic,
  customer_id,
  customer_type,
  origin_hub, origin_country,
  destination_hub, destination_country,
  concat(origin_hub, '-', destination_hub)                 AS lane,
  CAST(is_international AS BOOLEAN)                         AS is_international,
  service_code,
  CAST(weight_kg AS DOUBLE)                                AS weight_kg,
  CAST(volume_m3 AS DOUBLE)                                AS volume_m3,
  CAST(teu AS DOUBLE)                                      AS teu,
  CAST(ldm AS DOUBLE)                                      AS ldm,
  CAST(chargeable_kg AS DOUBLE)                            AS chargeable_kg,
  CAST(booked_capacity AS DOUBLE)                          AS booked_capacity,
  CAST(available_capacity AS DOUBLE)                       AS available_capacity,
  -- capacity utilization ratio (guard divide-by-zero)
  CASE WHEN available_capacity > 0
       THEN round(booked_capacity / available_capacity, 4) END AS capacity_utilization,
  CAST(first_time_right AS BOOLEAN)                        AS first_time_right,
  CAST(missing_address AS BOOLEAN)                         AS missing_address,
  CAST(missing_customs_doc AS BOOLEAN)                     AS missing_customs_doc,
  CAST(wrong_weight AS BOOLEAN)                            AS wrong_weight,
  CAST(missing_service_code AS BOOLEAN)                    AS missing_service_code,
  -- total completeness defects on the booking
  (CAST(missing_address AS INT) + CAST(missing_customs_doc AS INT)
   + CAST(wrong_weight AS INT) + CAST(missing_service_code AS INT)) AS defect_count,
  CAST(amendment_count AS INT)                             AS amendment_count,
  CAST(cancelled AS BOOLEAN)                               AS cancelled,
  CAST(no_show AS BOOLEAN)                                 AS no_show,
  defect_reason,
  date(CAST(booking_ts AS TIMESTAMP))                      AS booking_date,
  date_trunc('week',  CAST(booking_ts AS TIMESTAMP))       AS booking_week,
  date_trunc('month', CAST(booking_ts AS TIMESTAMP))       AS booking_month
FROM bronze.raw_bookings;

-- ---------------------------------------------------------------------------
-- GOLD — Booking VOLUME marts
-- ---------------------------------------------------------------------------

-- Daily volume + capacity utilization by mode (seasonality / capacity view)
CREATE OR REFRESH MATERIALIZED VIEW gold.volume_daily_by_mode
  COMMENT 'Daily booking volume, weight and capacity utilization by transport mode.'
AS
SELECT
  booking_date,
  mode,
  count(*)                                   AS bookings,
  round(sum(weight_kg), 1)                   AS total_weight_kg,
  round(sum(volume_m3), 2)                   AS total_volume_m3,
  round(avg(capacity_utilization), 4)        AS avg_capacity_utilization,
  round(avg(lead_time_days), 2)              AS avg_lead_time_days
FROM silver.bookings_clean
GROUP BY booking_date, mode;

-- Trade-lane concentration (high-value lane identification / risk)
CREATE OR REFRESH MATERIALIZED VIEW gold.lane_concentration
  COMMENT 'Volume and quality aggregated by trade lane for concentration/risk analysis.'
AS
SELECT
  lane, origin_hub, destination_hub, mode,
  count(*)                                   AS bookings,
  count(DISTINCT customer_id)                AS distinct_customers,
  round(sum(weight_kg), 1)                   AS total_weight_kg,
  round(avg(first_time_right::INT), 4)       AS ftr_rate,
  round(avg(lead_time_days), 2)              AS avg_lead_time_days
FROM silver.bookings_clean
GROUP BY lane, origin_hub, destination_hub, mode;

-- Booking velocity: lead-time buckets by week (how early bookings arrive)
CREATE OR REFRESH MATERIALIZED VIEW gold.booking_velocity
  COMMENT 'Weekly booking velocity by lead-time bucket.'
AS
SELECT
  booking_week,
  CASE
    WHEN lead_time_days < 1  THEN '0_same_day'
    WHEN lead_time_days < 3  THEN '1_1-3_days'
    WHEN lead_time_days < 7  THEN '2_3-7_days'
    WHEN lead_time_days < 14 THEN '3_1-2_weeks'
    ELSE '4_2wk_plus'
  END                                         AS lead_bucket,
  count(*)                                    AS bookings,
  round(avg(lead_time_days), 2)               AS avg_lead_time_days
FROM silver.bookings_clean
GROUP BY booking_week, lead_bucket;

-- ---------------------------------------------------------------------------
-- GOLD — Booking QUALITY marts
-- ---------------------------------------------------------------------------

-- First-Time-Right and electronic-integration share by channel
CREATE OR REFRESH MATERIALIZED VIEW gold.quality_by_channel
  COMMENT 'FTR, defect, amendment and no-show rates by booking channel.'
AS
SELECT
  channel,
  is_electronic,
  count(*)                                    AS bookings,
  round(avg(first_time_right::INT), 4)        AS ftr_rate,
  round(avg(defect_count), 3)                 AS avg_defects_per_booking,
  round(avg((amendment_count > 0)::INT), 4)   AS amendment_rate,
  round(avg(cancelled::INT), 4)               AS cancel_rate,
  round(avg(no_show::INT), 4)                 AS no_show_rate
FROM silver.bookings_clean
GROUP BY channel, is_electronic;

-- Completeness: which data points are most often missing
CREATE OR REFRESH MATERIALIZED VIEW gold.completeness_breakdown
  COMMENT 'Incidence of each completeness defect, overall and by channel.'
AS
SELECT
  channel,
  count(*)                                    AS bookings,
  round(avg(missing_address::INT), 4)         AS rate_missing_address,
  round(avg(missing_customs_doc::INT), 4)     AS rate_missing_customs_doc,
  round(avg(wrong_weight::INT), 4)            AS rate_wrong_weight,
  round(avg(missing_service_code::INT), 4)    AS rate_missing_service_code
FROM silver.bookings_clean
GROUP BY channel;

-- Monthly quality trend (FTR / automation share over time)
CREATE OR REFRESH MATERIALIZED VIEW gold.quality_monthly_trend
  COMMENT 'Monthly FTR rate, automation share, and defect trend.'
AS
SELECT
  booking_month,
  count(*)                                    AS bookings,
  round(avg(first_time_right::INT), 4)        AS ftr_rate,
  round(avg(is_electronic::INT), 4)           AS electronic_share,
  round(avg(defect_count), 3)                 AS avg_defects_per_booking,
  round(avg(no_show::INT), 4)                 AS no_show_rate
FROM silver.bookings_clean
GROUP BY booking_month;
