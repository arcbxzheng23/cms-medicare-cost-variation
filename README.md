# CMS Medicare Inpatient Cost Variation

**How much does the same inpatient procedure cost across hospitals and regions, and where are the biggest outliers and savings opportunities?**

An end-to-end lakehouse analytics project on CMS Medicare inpatient data: a medallion (Bronze, Silver, Gold) pipeline in Databricks with Delta Lake and Spark SQL, descriptive and diagnostic analysis in Python, an interactive Tableau dashboard, and a written findings report.

IMT 600 Independent Study, Autumn 2026 · Pin-Chu (Ben) Cheng · Faculty supervisor: Steven Gustafson

---

## Data source

| | |
|---|---|
| Dataset | CMS *Medicare Inpatient Hospitals, by Provider and Service* |
| Data year | 2024 (release RY26) |
| File | `MUP_INP_RY26_P03_V10_DY24_PrvSvc.CSV` |
| Grain | One row = one hospital (CCN) x one MS-DRG |
| Size | 145,879 rows x 15 columns |
| Coverage | Original Medicare Part A (fee-for-service) inpatient claims only. Excludes Medicare Advantage, Medicaid, private insurance, and uninsured patients. |
| Suppression | CMS suppresses any hospital x DRG cell with fewer than 11 discharges, so low-volume combinations are absent, not zero. |

The raw file is **not committed** to this repo. To reproduce:
1. Download the 2024 CSV from data.cms.gov (Medicare Inpatient Hospitals, by Provider and Service).
2. Save it as `data/raw/MUP_INP_RY26_P03_V10_DY24_PrvSvc.CSV` for local profiling.
3. Upload the same file to the Databricks volume described below.

## Architecture

```
CSV (data.cms.gov)
   │  upload
   ▼
/Volumes/workspace/cms/raw/                  landing zone (Unity Catalog volume)
   │  notebooks/01_bronze_ingest.py
   ▼
workspace.cms.bronze_cms_inpatient           Bronze: raw, all STRING, + lineage columns
   │  (Week 2)
   ▼
workspace.cms.silver_cms_inpatient           Silver: typed, cleaned, markup ratio
   │  (Weeks 3-4)
   ▼
workspace.cms.gold_*                         Gold: star schema (fact + hospital/DRG dims), variation tables
   │
   ├──► Python analysis (Weeks 5-7)
   └──► Tableau dashboard (Week 8)
```

## Repository layout

```
cms-medicare-cost-variation/
├── README.md
├── .gitignore
├── notebooks/          Databricks notebooks (source format .py, importable via Repos)
│   ├── 01_bronze_ingest.py
│   └── 02_silver_transform.py
├── scripts/            Local Python utilities
│   └── profile_raw_csv.py
├── docs/               Project documentation
│   ├── data_profiling_notes.md
│   ├── data_quality_log.md
│   ├── silver_cleaning_log.md
│   ├── run_evidence/   HTML exports of the Databricks runs, with all outputs
│   └── profile_output.json
├── data/raw/           Local copy of the source CSV (git-ignored)
├── dashboards/         Tableau workbook (Week 8)
└── reports/            Written findings report (Week 9)
```

## Bronze layer

**Purpose.** Land the source file exactly as received so every later layer can be rebuilt from it. Bronze does no cleaning, no type conversion, and no filtering.

**Table.** `workspace.cms.bronze_cms_inpatient` (Delta)

| Column(s) | Type | Notes |
|---|---|---|
| 15 source columns | STRING | Names and values exactly as in the CSV header and rows |
| `_corrupt_record` | STRING | Holds any line Spark could not parse. Expected to be all NULL. |
| `_ingest_ts` | TIMESTAMP | When the load ran |
| `_source_file` | STRING | Path of the file each row came from |

**Design choices.**
- *Everything as STRING.* Type inference can silently turn codes like ZIP `01234` or FIPS `01` into integers and drop the leading zero. Casting is a Silver decision, made explicitly and logged.
- *Explicit schema with `_corrupt_record` (PERMISSIVE mode).* Malformed lines are kept and flagged instead of dropped.
- *Full refresh (`overwrite`).* The source is a single annual file, so re-running the notebook produces an identical table. Delta keeps the history of each write (`DESCRIBE HISTORY`).
- *Validation in the notebook.* Asserts check row count, column count, all-string types, and zero corrupt records, and Spark-side profiling cross-checks the local profile in `docs/data_profiling_notes.md`.

**Run it.**
1. In Databricks (Free Edition), connect this repo under *Workspace > Repos* (or import `notebooks/01_bronze_ingest.py`).
2. Run the first two cells to create the `workspace.cms` schema and the `raw` volume.
3. Upload the CSV to *Catalog > workspace > cms > Volumes > raw*.
4. Run all remaining cells. All asserts should pass.
5. Then open `notebooks/02_silver_transform.py` and use *Run all* (it defines a temporary SQL function that later cells need).

## Silver layer

**Purpose.** Turn Bronze's raw strings into a typed, cleaned, analysis-ready table at the same grain, without dropping any rows.

**Table.** `workspace.cms.silver_cms_inpatient` (Delta), built by `notebooks/02_silver_transform.py` in Spark SQL.

| Group | Columns |
|---|---|
| Keys and codes (STRING) | `ccn`, `drg_cd`, `state_abbr`, `state_fips`, `zip5`, `ruca_code`, `ccn_facility_suffix` |
| Descriptive text (cleaned) | `provider_name`, `provider_street_addr`, `provider_city`, `ruca_desc`, `drg_desc` |
| Measures | `tot_discharges` (INT); `avg_submitted_charge`, `avg_total_payment`, `avg_medicare_payment` (DECIMAL(18,7)) |
| Derived totals | `tot_submitted_charge`, `tot_total_payment`, `tot_medicare_payment` (average x discharges) |
| Derived ratios | `markup_ratio` = charge / total payment; `medicare_share` = Medicare payment / total payment |
| Groupings and flags | `ruca_primary`, `ruca_group`, `urban_rural`, `is_maryland`, `is_markup_below_1` |
| Lineage | `_bronze_ingest_ts`, `_source_file`, `_silver_processed_ts` |

**Design choices.**
- *No rows removed.* Problem rows are flagged, so totals always reconcile to Bronze.
- *Weighted roll-ups only.* Values are averages, so every aggregate uses `SUM(tot_x) / SUM(tot_discharges)`.
- *Maryland flagged.* Its all-payer waiver makes charges close to payments (markup about 1.1 vs 5.2 elsewhere).
- *Delta CHECK constraints* enforce the discharge floor of 11, positive amounts, Medicare ≤ total payment, and code formats.
- *32 validation checks* reconcile Spark's output to values computed independently in pandas.

Every transformation is listed in [`docs/silver_cleaning_log.md`](docs/silver_cleaning_log.md).

## Weekly roadmap

| Week | Focus | Status |
|---|---|---|
| 1 | Environment + Git; Bronze ingest; profile all columns | Done (2026-10-08) |
| 2 | Silver: clean, type, markup ratio; data-quality log | Done (2026-10-08) |
| 3 | Gold star schema; per-DRG medians and hospital deviation | |
| 4 | Gold by state/region, hospital outliers, RUCA rural/urban | |
| 5 | Python exploratory and statistical analysis | |
| 6 | Core visuals | |
| 7 | Prioritization, savings estimate, draft recommendation | |
| 8 | Tableau dashboard | |
| 9 | Written findings report | |
| 10 | Finalize repo and documentation | |
| 11 | Final walkthrough presentation | |

## Data quality and methodology

See [`docs/data_quality_log.md`](docs/data_quality_log.md) for every known issue and how each layer handles it, and [`docs/data_profiling_notes.md`](docs/data_profiling_notes.md) for the column-by-column profile of the raw file.
