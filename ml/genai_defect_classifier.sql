-- ============================================================================
-- DSV Data Workbench — GenAI defect classifier
-- Turns the free-text `defect_reason` on failed bookings into a STRUCTURED
-- defect category + a concrete remediation suggestion, using ai_query against a
-- Databricks Foundation Model endpoint (Claude). This is the "make it
-- intelligent" GenAI stage for Booking Quality.
--
-- Output: dsv.gold.defect_classification  (queryable, feeds the app + Genie)
-- ============================================================================

CREATE OR REPLACE TABLE dsv.gold.defect_classification
COMMENT 'GenAI-classified booking defects with remediation (from free-text defect_reason).'
AS
WITH failed AS (
  SELECT booking_id, channel, mode, lane, defect_reason
  FROM dsv.silver.bookings_clean
  WHERE defect_reason IS NOT NULL AND length(defect_reason) > 0
  -- keep the sample bounded and representative for the demo run
  LIMIT 500
)
SELECT
  booking_id,
  channel,
  mode,
  lane,
  defect_reason,
  ai_query(
    'databricks-claude-sonnet-4-6',
    CONCAT(
      'You are a logistics booking-quality analyst at a freight forwarder. ',
      'Classify the booking defect below into exactly one category from this set: ',
      'ADDRESS, CUSTOMS, WEIGHT_DIMS, SERVICE_CODE, DUPLICATE, SCHEDULING, HAZMAT, OTHER. ',
      'Then give a one-sentence, actionable remediation. ',
      'Return strict JSON: {"category": "...", "remediation": "..."}. ',
      'Defect: ', defect_reason
    ),
    responseFormat => 'STRUCT<category:STRING, remediation:STRING>'
  ) AS classification
FROM failed;

-- Flatten for easy analysis / serving
CREATE OR REPLACE VIEW dsv.gold.defect_classification_flat AS
SELECT
  booking_id, channel, mode, lane, defect_reason,
  classification.category    AS defect_category,
  classification.remediation AS remediation
FROM dsv.gold.defect_classification;

-- Evidence query: category distribution by channel
SELECT defect_category, channel, count(*) AS n
FROM dsv.gold.defect_classification_flat
GROUP BY defect_category, channel
ORDER BY n DESC;
