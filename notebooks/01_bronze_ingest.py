# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Bronze ingestion: CMS Medicare Inpatient (by Provider and Service, DY2024)
# MAGIC
# MAGIC **Project:** IMT 600 Independent Study, Autumn 2026 (Ben Cheng; supervisor Steven Gustafson)
# MAGIC **Layer:** Bronze (raw, as-is)
# MAGIC **Output table:** `workspace.cms.bronze_cms_inpatient`
# MAGIC
# MAGIC ### What Bronze means in this project
# MAGIC In a medallion architecture each layer has one job:
# MAGIC
# MAGIC | Layer | Job | This project |
# MAGIC |---|---|---|
# MAGIC | **Bronze** | Land the source exactly as received, plus lineage columns. No cleaning, no typing. | Raw CSV, every column a string, plus `_ingest_ts` and `_source_file` |
# MAGIC | Silver | Clean, type, validate, derive | Week 2: cast dollars/counts, markup ratio |
# MAGIC | Gold | Business-ready models | Weeks 3-4: star schema, variation tables |
# MAGIC
# MAGIC Keeping Bronze untyped means a bad cast or a cleaning bug in Silver can always be fixed by re-running Silver from Bronze, without going back to the source file.
# MAGIC
# MAGIC ### How to run (Databricks Free Edition)
# MAGIC 1. Run cell **1** (config) and cell **2** (creates the schema and a Unity Catalog volume).
# MAGIC 2. Upload the CSV into the volume: **Catalog > workspace > cms > Volumes > raw > Upload to this volume**.
# MAGIC 3. Run the rest of the notebook top to bottom. It is safe to re-run: the table is overwritten each time, so the result is identical.

# COMMAND ----------

# DBTITLE 1,Config
# Everything that could change between environments lives here, so the rest of the notebook never hard-codes a path.
CATALOG = "workspace"   # default catalog in Databricks Free Edition
SCHEMA = "cms"          # one schema for the project; layers are distinguished by table prefix (bronze_, silver_, gold_)
VOLUME = "raw"          # Unity Catalog volume that holds landed source files
FILE_NAME = "MUP_INP_RY26_P03_V10_DY24_PrvSvc.CSV"

BRONZE_TABLE = f"{CATALOG}.{SCHEMA}.bronze_cms_inpatient"
SOURCE_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}/{FILE_NAME}"

# Expected shape, taken from local profiling of the same file (docs/data_profiling_notes.md).
EXPECTED_ROWS = 145_879
EXPECTED_SOURCE_COLS = 15

print("Source:", SOURCE_PATH)
print("Target:", BRONZE_TABLE)

# COMMAND ----------

# DBTITLE 1,Create schema and landing volume (idempotent)
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA} COMMENT 'IMT 600: CMS Medicare inpatient cost variation'")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{VOLUME} COMMENT 'Landing zone for raw source files'")

# COMMAND ----------

# DBTITLE 1,Confirm the file landed in the volume
# If this fails, upload the CSV into the volume first (see step 2 at the top).
files = dbutils.fs.ls(f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}/")
display(files)
assert any(f.name == FILE_NAME for f in files), f"{FILE_NAME} not found in the volume"

# COMMAND ----------

# DBTITLE 1,Read the CSV with every column as a string
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType

# Step A: read only the header row to get the source column names exactly as CMS wrote them.
header_cols = spark.read.option("header", True).csv(SOURCE_PATH).columns
assert len(header_cols) == EXPECTED_SOURCE_COLS, f"Expected {EXPECTED_SOURCE_COLS} columns, got {len(header_cols)}"

# Step B: build an explicit all-string schema, plus a _corrupt_record column.
# Why explicit instead of inferSchema=False? Same string result, but it lets Spark put any malformed line
# into _corrupt_record instead of silently dropping or mangling it. Bronze should never lose data quietly.
bronze_schema = StructType(
    [StructField(c, StringType(), True) for c in header_cols]
    + [StructField("_corrupt_record", StringType(), True)]
)

raw_df = (
    spark.read
    .schema(bronze_schema)
    .option("header", True)
    .option("enforceSchema", False)        # check the file header against our schema names
    .option("mode", "PERMISSIVE")          # keep malformed rows, route them to _corrupt_record
    .option("columnNameOfCorruptRecord", "_corrupt_record")
    .option("quote", '"')
    .option("escape", '"')                 # CSV standard: a quote inside a quoted field is written as ""
    .option("multiLine", False)
    .option("encoding", "UTF-8")
    .csv(SOURCE_PATH)
)

# Step C: add lineage columns. These are the only things Bronze adds to the source.
bronze_df = (
    raw_df
    .withColumn("_ingest_ts", F.current_timestamp())        # when this load ran (UTC)
    .withColumn("_source_file", F.col("_metadata.file_path"))  # which file each row came from
)

bronze_df.printSchema()

# COMMAND ----------

# DBTITLE 1,Write the Bronze Delta table
(
    bronze_df.write
    .format("delta")
    .mode("overwrite")                      # full refresh: re-running gives the same table
    .option("overwriteSchema", "true")
    .saveAsTable(BRONZE_TABLE)
)

spark.sql(f"""
COMMENT ON TABLE {BRONZE_TABLE} IS
'Bronze: CMS Medicare Inpatient Hospitals by Provider and Service, DY2024 (RY26 release), loaded as-is. All source columns are STRING. One row = one hospital (CCN) x MS-DRG. Lineage: _ingest_ts, _source_file. Malformed lines, if any, land in _corrupt_record.'
""")
print("Wrote", BRONZE_TABLE)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Validation
# MAGIC These checks are the evidence that the load is complete and faithful. If any assert fails, stop and investigate before moving to Silver.

# COMMAND ----------

# DBTITLE 1,Row count, column count, types, corrupt records
from pyspark.sql.types import StringType

bronze = spark.table(BRONZE_TABLE)

row_count = bronze.count()
corrupt_count = bronze.filter(F.col("_corrupt_record").isNotNull()).count()
source_fields = [f for f in bronze.schema.fields if not f.name.startswith("_")]
non_string = [f.name for f in source_fields if not isinstance(f.dataType, StringType)]

print(f"Rows:               {row_count:,} (expected {EXPECTED_ROWS:,})")
print(f"Source columns:     {len(source_fields)} (expected {EXPECTED_SOURCE_COLS})")
print(f"Non-string columns: {non_string or 'none'}")
print(f"Corrupt records:    {corrupt_count}")

assert row_count == EXPECTED_ROWS, "Row count does not match the source file"
assert len(source_fields) == EXPECTED_SOURCE_COLS, "Column count does not match the source file"
assert not non_string, "Bronze must keep every source column as STRING"
assert corrupt_count == 0, "Malformed CSV lines found; inspect _corrupt_record"
print("All Bronze checks passed.")

# COMMAND ----------

# DBTITLE 1,Per-column profile in Spark (cross-check against docs/data_profiling_notes.md)
# Row count, nulls, empty strings, distinct values, and min/max string length for every source column.
profile_rows = []
for c in [f.name for f in source_fields]:
    stats = bronze.agg(
        F.count(F.lit(1)).alias("rows"),
        F.sum(F.col(c).isNull().cast("int")).alias("nulls"),
        F.sum((F.trim(F.col(c)) == "").cast("int")).alias("blanks"),
        F.countDistinct(c).alias("distinct"),
        F.min(F.length(c)).alias("min_len"),
        F.max(F.length(c)).alias("max_len"),
    ).first().asDict()
    profile_rows.append({"column": c, **stats})

display(spark.createDataFrame(profile_rows))

# COMMAND ----------

# DBTITLE 1,Numeric columns: try_cast reveals values that will not convert in Silver
# MAGIC %sql
# MAGIC -- try_cast returns NULL instead of failing, so cast_failures counts values Silver will have to handle.
# MAGIC SELECT 'Tot_Dschrgs' AS col,
# MAGIC        COUNT(*) - COUNT(try_cast(Tot_Dschrgs AS INT)) AS cast_failures,
# MAGIC        MIN(try_cast(Tot_Dschrgs AS INT)) AS min_val, MAX(try_cast(Tot_Dschrgs AS INT)) AS max_val,
# MAGIC        ROUND(AVG(try_cast(Tot_Dschrgs AS INT)), 2) AS mean_val,
# MAGIC        percentile_approx(try_cast(Tot_Dschrgs AS INT), 0.5) AS median_val
# MAGIC FROM workspace.cms.bronze_cms_inpatient
# MAGIC UNION ALL
# MAGIC SELECT 'Avg_Submtd_Cvrd_Chrg', COUNT(*) - COUNT(try_cast(Avg_Submtd_Cvrd_Chrg AS DECIMAL(18,7))),
# MAGIC        MIN(try_cast(Avg_Submtd_Cvrd_Chrg AS DECIMAL(18,7))), MAX(try_cast(Avg_Submtd_Cvrd_Chrg AS DECIMAL(18,7))),
# MAGIC        ROUND(AVG(try_cast(Avg_Submtd_Cvrd_Chrg AS DECIMAL(18,7))), 2),
# MAGIC        percentile_approx(try_cast(Avg_Submtd_Cvrd_Chrg AS DECIMAL(18,7)), 0.5)
# MAGIC FROM workspace.cms.bronze_cms_inpatient
# MAGIC UNION ALL
# MAGIC SELECT 'Avg_Tot_Pymt_Amt', COUNT(*) - COUNT(try_cast(Avg_Tot_Pymt_Amt AS DECIMAL(18,7))),
# MAGIC        MIN(try_cast(Avg_Tot_Pymt_Amt AS DECIMAL(18,7))), MAX(try_cast(Avg_Tot_Pymt_Amt AS DECIMAL(18,7))),
# MAGIC        ROUND(AVG(try_cast(Avg_Tot_Pymt_Amt AS DECIMAL(18,7))), 2),
# MAGIC        percentile_approx(try_cast(Avg_Tot_Pymt_Amt AS DECIMAL(18,7)), 0.5)
# MAGIC FROM workspace.cms.bronze_cms_inpatient
# MAGIC UNION ALL
# MAGIC SELECT 'Avg_Mdcr_Pymt_Amt', COUNT(*) - COUNT(try_cast(Avg_Mdcr_Pymt_Amt AS DECIMAL(18,7))),
# MAGIC        MIN(try_cast(Avg_Mdcr_Pymt_Amt AS DECIMAL(18,7))), MAX(try_cast(Avg_Mdcr_Pymt_Amt AS DECIMAL(18,7))),
# MAGIC        ROUND(AVG(try_cast(Avg_Mdcr_Pymt_Amt AS DECIMAL(18,7))), 2),
# MAGIC        percentile_approx(try_cast(Avg_Mdcr_Pymt_Amt AS DECIMAL(18,7)), 0.5)
# MAGIC FROM workspace.cms.bronze_cms_inpatient

# COMMAND ----------

# DBTITLE 1,Code ranges: states, RUCA, DRGs, hospitals
# MAGIC %sql
# MAGIC SELECT COUNT(DISTINCT Rndrng_Prvdr_State_Abrvtn) AS states,
# MAGIC        COUNT(DISTINCT Rndrng_Prvdr_State_FIPS)   AS state_fips,
# MAGIC        COUNT(DISTINCT Rndrng_Prvdr_RUCA)         AS ruca_codes,
# MAGIC        COUNT(DISTINCT DRG_Cd)                    AS drgs,
# MAGIC        COUNT(DISTINCT Rndrng_Prvdr_CCN)          AS hospitals,
# MAGIC        COUNT(DISTINCT Rndrng_Prvdr_CCN, DRG_Cd)  AS hospital_drg_pairs,
# MAGIC        COUNT(*)                                  AS rows
# MAGIC FROM workspace.cms.bronze_cms_inpatient

# COMMAND ----------

# DBTITLE 1,RUCA code distribution
# MAGIC %sql
# MAGIC SELECT Rndrng_Prvdr_RUCA, Rndrng_Prvdr_RUCA_Desc, COUNT(*) AS rows, COUNT(DISTINCT Rndrng_Prvdr_CCN) AS hospitals
# MAGIC FROM workspace.cms.bronze_cms_inpatient
# MAGIC GROUP BY ALL
# MAGIC ORDER BY try_cast(Rndrng_Prvdr_RUCA AS DOUBLE)

# COMMAND ----------

# DBTITLE 1,Key and relationship checks (see profiling notes, section 5)
# MAGIC %sql
# MAGIC -- Expected: dup_pairs 0; the four ccns_with_multiple_* columns 0; names_shared_by_ccns 40; descs_shared_by_codes 8
# MAGIC SELECT
# MAGIC   (SELECT COUNT(*) FROM (SELECT Rndrng_Prvdr_CCN, DRG_Cd FROM workspace.cms.bronze_cms_inpatient GROUP BY ALL HAVING COUNT(*) > 1)) AS dup_pairs,
# MAGIC   (SELECT COUNT(*) FROM (SELECT Rndrng_Prvdr_CCN FROM workspace.cms.bronze_cms_inpatient GROUP BY 1 HAVING COUNT(DISTINCT Rndrng_Prvdr_Org_Name) > 1)) AS ccns_with_multiple_names,
# MAGIC   (SELECT COUNT(*) FROM (SELECT Rndrng_Prvdr_CCN FROM workspace.cms.bronze_cms_inpatient GROUP BY 1 HAVING COUNT(DISTINCT Rndrng_Prvdr_St) > 1)) AS ccns_with_multiple_streets,
# MAGIC   (SELECT COUNT(*) FROM (SELECT Rndrng_Prvdr_CCN FROM workspace.cms.bronze_cms_inpatient GROUP BY 1 HAVING COUNT(DISTINCT Rndrng_Prvdr_State_Abrvtn) > 1)) AS ccns_with_multiple_states,
# MAGIC   (SELECT COUNT(*) FROM (SELECT Rndrng_Prvdr_CCN FROM workspace.cms.bronze_cms_inpatient GROUP BY 1 HAVING COUNT(DISTINCT Rndrng_Prvdr_RUCA) > 1)) AS ccns_with_multiple_ruca,
# MAGIC   (SELECT COUNT(*) FROM (SELECT Rndrng_Prvdr_Org_Name FROM workspace.cms.bronze_cms_inpatient GROUP BY 1 HAVING COUNT(DISTINCT Rndrng_Prvdr_CCN) > 1)) AS names_shared_by_ccns,
# MAGIC   (SELECT COUNT(*) FROM (SELECT DRG_Desc FROM workspace.cms.bronze_cms_inpatient GROUP BY 1 HAVING COUNT(DISTINCT DRG_Cd) > 1)) AS descs_shared_by_codes

# COMMAND ----------

# DBTITLE 1,Markup preview by state (Maryland check, DQ-13)
# MAGIC %sql
# MAGIC -- Preview only; the markup ratio is formally built in Silver. Expect MD at the bottom with a median near 1.12.
# MAGIC SELECT Rndrng_Prvdr_State_Abrvtn AS state,
# MAGIC        COUNT(*) AS rows,
# MAGIC        ROUND(percentile_approx(try_cast(Avg_Submtd_Cvrd_Chrg AS DOUBLE) / try_cast(Avg_Tot_Pymt_Amt AS DOUBLE), 0.5), 2) AS median_markup,
# MAGIC        SUM(CASE WHEN try_cast(Avg_Submtd_Cvrd_Chrg AS DOUBLE) < try_cast(Avg_Tot_Pymt_Amt AS DOUBLE) THEN 1 ELSE 0 END) AS rows_markup_below_1
# MAGIC FROM workspace.cms.bronze_cms_inpatient
# MAGIC GROUP BY 1
# MAGIC ORDER BY median_markup
# MAGIC LIMIT 10

# COMMAND ----------

# DBTITLE 1,Delta table history (shows the write you just did)
# MAGIC %sql
# MAGIC DESCRIBE HISTORY workspace.cms.bronze_cms_inpatient

# COMMAND ----------

# MAGIC %md
# MAGIC ## Done
# MAGIC Paste the outputs of the validation cells (row/column checks through the markup preview) back into the Cowork session so they can be compared line by line with the local profile in `docs/data_profiling_notes.md`.
