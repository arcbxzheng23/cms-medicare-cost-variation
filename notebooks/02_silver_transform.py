# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Silver transform: typed, cleaned, enriched
# MAGIC
# MAGIC **Project:** IMT 600 Independent Study, Autumn 2026 (Ben Cheng; supervisor Steven Gustafson)
# MAGIC **Layer:** Silver · **Input:** `workspace.cms.bronze_cms_inpatient` · **Output:** `workspace.cms.silver_cms_inpatient`
# MAGIC
# MAGIC ### What Silver does (and does not do)
# MAGIC Silver turns the raw strings into a trustworthy, analysis-ready table at the **same grain** as Bronze (one row per hospital x DRG). Every change is listed in `docs/silver_cleaning_log.md` and traced to an issue ID in `docs/data_quality_log.md`.
# MAGIC
# MAGIC | Step | What | DQ issue |
# MAGIC |---|---|---|
# MAGIC | 1 | Rename to clear snake_case (e.g. `Rndrng_Prvdr_St` becomes `provider_street_addr`) | DQ-11 |
# MAGIC | 2 | Cast counts to INT and dollars to DECIMAL(18,7); codes stay STRING | DQ-01, DQ-02, DQ-05 |
# MAGIC | 3 | Clean text: fix the U+0096 character, strip control characters, collapse repeated spaces | DQ-08, DQ-09 |
# MAGIC | 4 | Derive totals (average x discharges) so later roll-ups can be discharge-weighted | DQ-04 |
# MAGIC | 5 | Derive **markup ratio** and Medicare share | Week 2 deliverable, DQ-15 |
# MAGIC | 6 | Derive RUCA rural/urban groups (Unknown kept as its own bucket) | DQ-12 |
# MAGIC | 7 | Flag Maryland and markup < 1; derive CCN facility suffix | DQ-13, DQ-18 |
# MAGIC
# MAGIC **Silver never deletes rows.** Problem rows are flagged so totals always reconcile to Bronze and every exclusion later is explicit.
# MAGIC Group-level flags (thin DRGs, hospitals with few DRGs, outliers within a DRG) need aggregation, so they are built in Gold (Week 3).
# MAGIC
# MAGIC **Run:** after `01_bronze_ingest` has passed. Safe to re-run (full refresh).

# COMMAND ----------

# DBTITLE 1,Config and expected values
CATALOG, SCHEMA = "workspace", "cms"
BRONZE_TABLE = f"{CATALOG}.{SCHEMA}.bronze_cms_inpatient"
SILVER_TABLE = f"{CATALOG}.{SCHEMA}.silver_cms_inpatient"

# Expected values computed independently in pandas from the same CSV (see docs/silver_cleaning_log.md).
# If Spark disagrees with any of these, one of the two implementations has a bug: investigate before moving on.
EXPECTED = {
    "rows": 145_879,
    "hospitals": 2_906,
    "drgs": 540,
    "total_discharges": 4_952_481,
    "total_payment": 90_927_479_550.00,        # sum(avg_total_payment x discharges), USD
    "total_medicare_payment": 75_111_479_229.00,
    "total_submitted_charge": 457_648_118_614.10,
    "maryland_rows": 3_531,
    "maryland_hospitals": 44,
    "markup_below_1_rows": 223,
    "distinct_provider_names": 2_845,           # cleaning must not merge or split any names
    "ruca_group_rows": {"Metropolitan": 131_744, "Micropolitan": 11_426, "Small town": 1_561, "Rural": 570, "Unknown": 578},
    "urban_rural_rows": {"Urban": 131_744, "Rural": 13_557, "Unknown": 578},
}

# COMMAND ----------

# DBTITLE 1,Text-cleaning function (one definition, reused for every text column)
# MAGIC %sql
# MAGIC -- A SQL function keeps the rule in one place, so every text column is cleaned the same way.
# MAGIC --   1. U+0096 (a Windows-1252 en dash decoded incorrectly) becomes '-'      (DQ-08)
# MAGIC --   2. any other C1 control character U+0080 to U+009F is removed          (DQ-08)
# MAGIC --   3. runs of whitespace collapse to one space, then trim                  (DQ-09)
# MAGIC CREATE OR REPLACE TEMPORARY FUNCTION clean_text(s STRING)
# MAGIC RETURNS STRING
# MAGIC RETURN trim(
# MAGIC   regexp_replace(
# MAGIC     regexp_replace(
# MAGIC       regexp_replace(s, '\\x{96}', '-'),
# MAGIC     '[\\x{80}-\\x{9F}]', ''),
# MAGIC   '\\s+', ' ')
# MAGIC );
# MAGIC
# MAGIC -- Quick unit test on the one known bad name plus a double-space example
# MAGIC SELECT clean_text(Rndrng_Prvdr_Org_Name) AS cleaned, Rndrng_Prvdr_Org_Name AS raw
# MAGIC FROM workspace.cms.bronze_cms_inpatient
# MAGIC WHERE Rndrng_Prvdr_CCN IN ('670128', '450885')
# MAGIC GROUP BY ALL;

# COMMAND ----------

# DBTITLE 1,Build the Silver table
# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE workspace.cms.silver_cms_inpatient
# MAGIC COMMENT 'Silver: CMS Medicare inpatient DY2024, one row per hospital (ccn) x MS-DRG (drg_cd). Typed, text-cleaned, with discharge-weighted totals, markup ratio, RUCA groups and quality flags. No rows removed. See docs/silver_cleaning_log.md.'
# MAGIC AS
# MAGIC WITH typed AS (
# MAGIC   SELECT
# MAGIC     -- keys and codes: stay STRING (leading zeros, DQ-02)
# MAGIC     Rndrng_Prvdr_CCN                                   AS ccn,
# MAGIC     DRG_Cd                                             AS drg_cd,
# MAGIC     Rndrng_Prvdr_State_Abrvtn                          AS state_abbr,
# MAGIC     Rndrng_Prvdr_State_FIPS                            AS state_fips,
# MAGIC     Rndrng_Prvdr_Zip5                                  AS zip5,
# MAGIC     Rndrng_Prvdr_RUCA                                  AS ruca_code,
# MAGIC     -- descriptive text: cleaned (DQ-08, DQ-09) and renamed (DQ-11)
# MAGIC     clean_text(Rndrng_Prvdr_Org_Name)                  AS provider_name,
# MAGIC     clean_text(Rndrng_Prvdr_City)                      AS provider_city,
# MAGIC     clean_text(Rndrng_Prvdr_St)                        AS provider_street_addr,
# MAGIC     clean_text(Rndrng_Prvdr_RUCA_Desc)                 AS ruca_desc,
# MAGIC     clean_text(DRG_Desc)                               AS drg_desc,
# MAGIC     -- measures: typed (DQ-01); DECIMAL keeps the full 7-decimal precision (DQ-05)
# MAGIC     try_cast(Tot_Dschrgs          AS INT)              AS tot_discharges,
# MAGIC     try_cast(Avg_Submtd_Cvrd_Chrg AS DECIMAL(18,7))    AS avg_submitted_charge,
# MAGIC     try_cast(Avg_Tot_Pymt_Amt     AS DECIMAL(18,7))    AS avg_total_payment,
# MAGIC     try_cast(Avg_Mdcr_Pymt_Amt    AS DECIMAL(18,7))    AS avg_medicare_payment,
# MAGIC     -- lineage
# MAGIC     _ingest_ts                                         AS _bronze_ingest_ts,
# MAGIC     _source_file
# MAGIC   FROM workspace.cms.bronze_cms_inpatient
# MAGIC   WHERE _corrupt_record IS NULL
# MAGIC )
# MAGIC SELECT
# MAGIC   ccn, provider_name, provider_street_addr, provider_city, state_abbr, state_fips, zip5,
# MAGIC   ruca_code, ruca_desc,
# MAGIC   -- RUCA grouping (DQ-12). Primary code = whole-number part; 99 = Unknown, never imputed.
# MAGIC   CAST(FLOOR(try_cast(ruca_code AS DOUBLE)) AS INT)    AS ruca_primary,
# MAGIC   CASE
# MAGIC     WHEN FLOOR(try_cast(ruca_code AS DOUBLE)) BETWEEN 1 AND 3 THEN 'Metropolitan'
# MAGIC     WHEN FLOOR(try_cast(ruca_code AS DOUBLE)) BETWEEN 4 AND 6 THEN 'Micropolitan'
# MAGIC     WHEN FLOOR(try_cast(ruca_code AS DOUBLE)) BETWEEN 7 AND 9 THEN 'Small town'
# MAGIC     WHEN FLOOR(try_cast(ruca_code AS DOUBLE)) = 10           THEN 'Rural'
# MAGIC     ELSE 'Unknown'
# MAGIC   END                                                  AS ruca_group,
# MAGIC   CASE
# MAGIC     WHEN FLOOR(try_cast(ruca_code AS DOUBLE)) BETWEEN 1 AND 3  THEN 'Urban'
# MAGIC     WHEN FLOOR(try_cast(ruca_code AS DOUBLE)) BETWEEN 4 AND 10 THEN 'Rural'
# MAGIC     ELSE 'Unknown'
# MAGIC   END                                                  AS urban_rural,
# MAGIC   substr(ccn, 3, 4)                                    AS ccn_facility_suffix,   -- DQ-18
# MAGIC   drg_cd, drg_desc,
# MAGIC   tot_discharges,
# MAGIC   avg_submitted_charge, avg_total_payment, avg_medicare_payment,
# MAGIC   -- totals (DQ-04): any roll-up must SUM these and divide by SUM(tot_discharges)
# MAGIC   avg_submitted_charge * tot_discharges                AS tot_submitted_charge,
# MAGIC   avg_total_payment    * tot_discharges                AS tot_total_payment,
# MAGIC   avg_medicare_payment * tot_discharges                AS tot_medicare_payment,
# MAGIC   -- ratios (DOUBLE is fine: they are unitless and used for comparison, not accounting)
# MAGIC   CAST(avg_submitted_charge AS DOUBLE) / CAST(avg_total_payment AS DOUBLE) AS markup_ratio,
# MAGIC   CAST(avg_medicare_payment AS DOUBLE) / CAST(avg_total_payment AS DOUBLE) AS medicare_share,
# MAGIC   -- flags (DQ-13)
# MAGIC   state_abbr = 'MD'                                    AS is_maryland,
# MAGIC   avg_submitted_charge < avg_total_payment             AS is_markup_below_1,
# MAGIC   _bronze_ingest_ts, _source_file,
# MAGIC   current_timestamp()                                  AS _silver_processed_ts
# MAGIC FROM typed;

# COMMAND ----------

# DBTITLE 1,Column comments and table constraints
# MAGIC %sql
# MAGIC -- Comments travel with the table into Catalog Explorer and Tableau, so the meaning is documented where people see it.
# MAGIC ALTER TABLE workspace.cms.silver_cms_inpatient ALTER COLUMN provider_street_addr COMMENT 'Street address (source column Rndrng_Prvdr_St, not the state)';
# MAGIC ALTER TABLE workspace.cms.silver_cms_inpatient ALTER COLUMN tot_total_payment    COMMENT 'avg_total_payment x tot_discharges. Use SUM(this)/SUM(tot_discharges) for weighted averages';
# MAGIC ALTER TABLE workspace.cms.silver_cms_inpatient ALTER COLUMN markup_ratio         COMMENT 'avg_submitted_charge / avg_total_payment (charge-to-payment markup)';
# MAGIC ALTER TABLE workspace.cms.silver_cms_inpatient ALTER COLUMN medicare_share       COMMENT 'avg_medicare_payment / avg_total_payment';
# MAGIC ALTER TABLE workspace.cms.silver_cms_inpatient ALTER COLUMN ruca_group           COMMENT 'Metropolitan (RUCA 1-3), Micropolitan (4-6), Small town (7-9), Rural (10), Unknown (99)';
# MAGIC ALTER TABLE workspace.cms.silver_cms_inpatient ALTER COLUMN is_maryland          COMMENT 'Maryland all-payer waiver: exclude from markup comparisons (DQ-13)';
# MAGIC
# MAGIC -- Delta CHECK constraints: any future write that breaks these rules fails instead of silently loading bad data.
# MAGIC ALTER TABLE workspace.cms.silver_cms_inpatient DROP CONSTRAINT IF EXISTS chk_discharges_floor;
# MAGIC ALTER TABLE workspace.cms.silver_cms_inpatient ADD CONSTRAINT chk_discharges_floor CHECK (tot_discharges >= 11);
# MAGIC ALTER TABLE workspace.cms.silver_cms_inpatient DROP CONSTRAINT IF EXISTS chk_positive_amounts;
# MAGIC ALTER TABLE workspace.cms.silver_cms_inpatient ADD CONSTRAINT chk_positive_amounts CHECK (avg_submitted_charge > 0 AND avg_total_payment > 0 AND avg_medicare_payment > 0);
# MAGIC ALTER TABLE workspace.cms.silver_cms_inpatient DROP CONSTRAINT IF EXISTS chk_medicare_le_total;
# MAGIC ALTER TABLE workspace.cms.silver_cms_inpatient ADD CONSTRAINT chk_medicare_le_total CHECK (avg_medicare_payment <= avg_total_payment);
# MAGIC ALTER TABLE workspace.cms.silver_cms_inpatient DROP CONSTRAINT IF EXISTS chk_code_formats;
# MAGIC ALTER TABLE workspace.cms.silver_cms_inpatient ADD CONSTRAINT chk_code_formats CHECK (ccn RLIKE '^[0-9]{6}$' AND drg_cd RLIKE '^[0-9]{3}$' AND state_fips RLIKE '^[0-9]{2}$' AND zip5 RLIKE '^[0-9]{5}$');

# COMMAND ----------

# MAGIC %md
# MAGIC ## Validation
# MAGIC Each check compares Spark's result with the value computed independently in pandas. All must pass before Week 3.

# COMMAND ----------

# DBTITLE 1,Reconcile Silver to Bronze and to the expected values
from pyspark.sql import functions as F

bronze = spark.table(BRONZE_TABLE)
silver = spark.table(SILVER_TABLE)
results = []

def check(name, actual, expected, tol=0):
    ok = abs(actual - expected) <= tol if isinstance(expected, (int, float)) else actual == expected
    results.append((name, str(actual), str(expected), "PASS" if ok else "FAIL"))

# 1. Completeness: same rows as Bronze, nothing dropped
check("rows = Bronze rows", silver.count(), bronze.count())
check("rows = expected", silver.count(), EXPECTED["rows"])

# 2. Casting: try_cast returns NULL on failure, so any NULL in a typed column is a failed cast
typed_cols = ["tot_discharges", "avg_submitted_charge", "avg_total_payment", "avg_medicare_payment", "ruca_primary", "markup_ratio"]
nulls = silver.select([F.sum(F.col(c).isNull().cast("int")).alias(c) for c in typed_cols]).first().asDict()
for c, v in nulls.items():
    check(f"cast failures in {c}", v, 0)

# 3. Grain and keys
check("duplicate (ccn, drg_cd)", silver.count() - silver.select("ccn", "drg_cd").distinct().count(), 0)
check("hospitals", silver.select("ccn").distinct().count(), EXPECTED["hospitals"])
check("DRGs", silver.select("drg_cd").distinct().count(), EXPECTED["drgs"])

# 4. Totals reconcile (to the cent)
agg = silver.agg(
    F.sum("tot_discharges").alias("d"),
    F.sum("tot_total_payment").cast("double").alias("tp"),
    F.sum("tot_medicare_payment").cast("double").alias("mp"),
    F.sum("tot_submitted_charge").cast("double").alias("ch"),
).first()
check("total discharges", agg.d, EXPECTED["total_discharges"])
check("total payment ($)", round(agg.tp, 2), EXPECTED["total_payment"], tol=1.0)
check("total Medicare payment ($)", round(agg.mp, 2), EXPECTED["total_medicare_payment"], tol=1.0)
check("total submitted charge ($)", round(agg.ch, 2), EXPECTED["total_submitted_charge"], tol=1.0)

# 5. Text cleaning worked and did not merge or split names
text_cols = ["provider_name", "provider_city", "provider_street_addr", "ruca_desc", "drg_desc"]
for c in text_cols:
    bad = silver.filter(F.col(c).rlike(r"[\x{80}-\x{9F}]") | F.col(c).rlike(r"\s{2,}") | (F.col(c) != F.trim(c))).count()
    check(f"dirty values left in {c}", bad, 0)
check("distinct provider names", silver.select("provider_name").distinct().count(), EXPECTED["distinct_provider_names"])

# 6. Flags and groups
check("Maryland rows", silver.filter("is_maryland").count(), EXPECTED["maryland_rows"])
check("Maryland hospitals", silver.filter("is_maryland").select("ccn").distinct().count(), EXPECTED["maryland_hospitals"])
check("markup < 1 rows", silver.filter("is_markup_below_1").count(), EXPECTED["markup_below_1_rows"])
for g, n in EXPECTED["ruca_group_rows"].items():
    check(f"ruca_group = {g}", silver.filter(F.col("ruca_group") == g).count(), n)
for g, n in EXPECTED["urban_rural_rows"].items():
    check(f"urban_rural = {g}", silver.filter(F.col("urban_rural") == g).count(), n)

report = spark.createDataFrame(results, ["check", "actual", "expected", "status"])
display(report)
failed = [r for r in results if r[3] == "FAIL"]
assert not failed, f"{len(failed)} Silver check(s) failed: {[r[0] for r in failed]}"
print(f"All {len(results)} Silver checks passed.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## First look at the markup ratio (Week 2 deliverable)
# MAGIC Weighted averages use totals (`SUM(tot_...)/SUM(...)`), never an average of averages (DQ-04).

# COMMAND ----------

# DBTITLE 1,National summary, with and without Maryland
# MAGIC %sql
# MAGIC SELECT
# MAGIC   CASE WHEN is_maryland THEN 'Maryland' ELSE 'All other states + DC' END   AS segment,
# MAGIC   COUNT(*)                                                                AS rows,
# MAGIC   COUNT(DISTINCT ccn)                                                     AS hospitals,
# MAGIC   SUM(tot_discharges)                                                     AS discharges,
# MAGIC   ROUND(SUM(tot_total_payment) / SUM(tot_discharges), 2)                  AS wtd_avg_payment_per_discharge,
# MAGIC   ROUND(SUM(tot_submitted_charge) / SUM(tot_total_payment), 2)            AS wtd_markup_ratio,
# MAGIC   ROUND(percentile_approx(markup_ratio, 0.5), 2)                          AS median_row_markup,
# MAGIC   SUM(CAST(is_markup_below_1 AS INT))                                     AS rows_markup_below_1
# MAGIC FROM workspace.cms.silver_cms_inpatient
# MAGIC GROUP BY ALL
# MAGIC UNION ALL
# MAGIC SELECT 'National (all rows)', COUNT(*), COUNT(DISTINCT ccn), SUM(tot_discharges),
# MAGIC        ROUND(SUM(tot_total_payment) / SUM(tot_discharges), 2),
# MAGIC        ROUND(SUM(tot_submitted_charge) / SUM(tot_total_payment), 2),
# MAGIC        ROUND(percentile_approx(markup_ratio, 0.5), 2),
# MAGIC        SUM(CAST(is_markup_below_1 AS INT))
# MAGIC FROM workspace.cms.silver_cms_inpatient

# COMMAND ----------

# DBTITLE 1,Markup and payment by RUCA group (excluding Maryland)
# MAGIC %sql
# MAGIC SELECT ruca_group,
# MAGIC        COUNT(DISTINCT ccn)                                          AS hospitals,
# MAGIC        SUM(tot_discharges)                                          AS discharges,
# MAGIC        ROUND(SUM(tot_total_payment) / SUM(tot_discharges), 2)       AS wtd_avg_payment_per_discharge,
# MAGIC        ROUND(SUM(tot_submitted_charge) / SUM(tot_total_payment), 2) AS wtd_markup_ratio
# MAGIC FROM workspace.cms.silver_cms_inpatient
# MAGIC WHERE NOT is_maryland
# MAGIC GROUP BY ALL
# MAGIC ORDER BY CASE ruca_group WHEN 'Metropolitan' THEN 1 WHEN 'Micropolitan' THEN 2 WHEN 'Small town' THEN 3 WHEN 'Rural' THEN 4 ELSE 5 END

# COMMAND ----------

# DBTITLE 1,Markup by state: top and bottom 5 (excluding Maryland)
# MAGIC %sql
# MAGIC WITH s AS (
# MAGIC   SELECT state_abbr,
# MAGIC          ROUND(SUM(tot_submitted_charge) / SUM(tot_total_payment), 2) AS wtd_markup_ratio,
# MAGIC          ROUND(SUM(tot_total_payment) / SUM(tot_discharges), 2)       AS wtd_avg_payment_per_discharge,
# MAGIC          COUNT(DISTINCT ccn)                                          AS hospitals
# MAGIC   FROM workspace.cms.silver_cms_inpatient
# MAGIC   WHERE NOT is_maryland
# MAGIC   GROUP BY 1
# MAGIC )
# MAGIC (SELECT 'Highest' AS rank_group, * FROM s ORDER BY wtd_markup_ratio DESC LIMIT 5)
# MAGIC UNION ALL
# MAGIC (SELECT 'Lowest', * FROM s ORDER BY wtd_markup_ratio ASC LIMIT 5)

# COMMAND ----------

# DBTITLE 1,Delta history and schema
# MAGIC %sql
# MAGIC DESCRIBE TABLE EXTENDED workspace.cms.silver_cms_inpatient

# COMMAND ----------

# MAGIC %md
# MAGIC ## Done
# MAGIC Paste the validation table and the three summary queries back into Cowork. The summary numbers go into `docs/silver_cleaning_log.md` as the Week 2 evidence.
