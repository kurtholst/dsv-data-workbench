-- ============================================================================
-- DSV Data Workbench — governance: grants + column tags
-- Models the two personas from the DSV brief: data analysts and business users.
-- Uses account groups if present; falls back gracefully if a group is absent
-- (run the GRANTs that apply to your workspace's group names).
-- ============================================================================

-- Analysts get to read + explore the governed marts and use the raw/silver for
-- ad-hoc, granular, historical analysis (the "Data Workbench" ask).
GRANT USE CATALOG ON CATALOG dsv TO `account users`;
GRANT USE SCHEMA  ON SCHEMA  dsv.gold   TO `account users`;
GRANT USE SCHEMA  ON SCHEMA  dsv.silver TO `account users`;
GRANT SELECT      ON SCHEMA  dsv.gold   TO `account users`;
GRANT SELECT      ON SCHEMA  dsv.silver TO `account users`;

-- ---------------------------------------------------------------------------
-- Column tagging: mark quality vs volume columns so analysts can discover
-- the right fields, and flag the free-text field that feeds GenAI.
-- (Applied after the pipeline creates silver.bookings_clean.)
-- ---------------------------------------------------------------------------
ALTER TABLE dsv.silver.bookings_clean ALTER COLUMN first_time_right   SET TAGS ('kpi_family' = 'quality');
ALTER TABLE dsv.silver.bookings_clean ALTER COLUMN amendment_count    SET TAGS ('kpi_family' = 'quality');
ALTER TABLE dsv.silver.bookings_clean ALTER COLUMN no_show            SET TAGS ('kpi_family' = 'quality');
ALTER TABLE dsv.silver.bookings_clean ALTER COLUMN channel            SET TAGS ('kpi_family' = 'quality', 'topic' = 'automation_share');
ALTER TABLE dsv.silver.bookings_clean ALTER COLUMN defect_reason      SET TAGS ('kpi_family' = 'quality', 'genai_input' = 'true');
ALTER TABLE dsv.silver.bookings_clean ALTER COLUMN booked_capacity    SET TAGS ('kpi_family' = 'volume');
ALTER TABLE dsv.silver.bookings_clean ALTER COLUMN lead_time_days     SET TAGS ('kpi_family' = 'volume', 'topic' = 'booking_velocity');
ALTER TABLE dsv.silver.bookings_clean ALTER COLUMN origin_hub         SET TAGS ('kpi_family' = 'volume', 'topic' = 'lane');
ALTER TABLE dsv.silver.bookings_clean ALTER COLUMN destination_hub    SET TAGS ('kpi_family' = 'volume', 'topic' = 'lane');
