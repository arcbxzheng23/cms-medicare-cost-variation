# CMS Medicare Inpatient Cost Variation

**For which hospital procedures does cost vary most in ways that quality and ownership do not explain, and where should a health system and payer look for savings?**

An end-to-end lakehouse analytics project on two joined CMS datasets (Medicare inpatient payments and hospital quality and ownership): a medallion (Bronze, Silver, Gold) pipeline in Databricks with Delta Lake and Spark SQL, descriptive and diagnostic analysis in Python, an interactive Tableau dashboard, and a written findings report.

IMT 600 Independent Study, Autumn 2026 · Pin-Chu (Ben) Cheng · Faculty supervisor: Steven Gustafson

---

## Research questions and hypotheses

From the approved IMT 600 proposal. The data will refine these.

1. For which hospital procedures does cost vary most in ways that quality and ownership do not explain?
2. Where should a health system and payer look for savings?

| ID | Hypothesis | Status |
|---|---|---|
| H1 | Cost varies more by hospital than by region or severity | Partly answered (Week 4): state payment index spans 0.84 to 1.45, hospital index 0.61 to 9.95. Formal test in Week 6 |
| H2 | Higher-cost hospitals do not have higher quality ratings | Week 6. Data ready: 2,517 inpatient hospitals with a 1 to 5 star rating |
| H3 | For-profit hospitals show higher charge-to-payment markups | Week 6. Data ready: 1,875 non-profit, 631 for-profit, 393 government inpatient hospitals |
| H4 | Rural and urban hospitals differ in cost for the same procedure | Answered (Week 4): urban paid 41% more per discharge raw, 11% more after case-mix adjustment. Significance test in Week 6 |

## Data sources

### 1. Medicare Inpatient Hospitals, by Provider and Service (cost data)

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

### 2. Hospital General Information (hospital attributes)

| | |
|---|---|
| Dataset | CMS Provider Data Catalog, *Hospital General Information* (dataset `xubh-q36u`) |
| Snapshot | CMS archived snapshot of 2024-10-30, inside the claims year (DQ-24) |
| File | `Hospital_General_Information_2024-10-30.csv` (renamed from `Hospital_General_Information.csv` inside the archive) |
| Grain | One row = one hospital (`Facility ID` = CCN) |
| Size | 5,394 rows x 39 columns |
| Used for | Ownership, hospital type, emergency services, overall star rating (1 to 5 or Not Available) |
| Join | `Facility ID` = `ccn`, both 6-character text. 2,899 of 2,906 inpatient hospitals match (DQ-25) |

Download `hospitals_2024-10-30.zip` from the CMS Provider Data Catalog hospitals archive (data.cms.gov/provider-data/archived-data/hospitals), extract `Hospital_General_Information.csv`, rename it as above, and upload it to the same Databricks volume.

## Architecture

```
Inpatient CSV (data.cms.gov)                 Hospital General Information CSV (Provider Data Catalog)
   │  upload                                    │  upload
   ▼                                            ▼
/Volumes/workspace/cms/raw/                  landing zone (Unity Catalog volume, both files)
   │  01_bronze_ingest.py                       │  05_hospital_info.ipynb
   ▼                                            ▼
bronze_cms_inpatient                         bronze_hospital_info           Bronze: raw, all STRING, + lineage
   │  02_silver_transform.py                    │  05_hospital_info.ipynb
   ▼                                            ▼
silver_cms_inpatient                         silver_hospital_info           Silver: typed, cleaned
   │  03 and 04 notebooks                       │  05_hospital_info.ipynb
   ▼                                            ▼
gold_* star schema and aggregates  ◄── ccn ──  gold_dim_hospital_profile    Gold: joined on CCN
   │
   ├──► Python analysis: hypothesis tests and regression (06_python_analysis.ipynb, Week 6)
   └──► Tableau dashboard (Weeks 7-8)
```

## Repository layout

```
cms-medicare-cost-variation/
├── README.md
├── .gitignore
├── notebooks/          Databricks notebooks (01 and 02 as source .py, 03 as .ipynb; importable via Repos)
│   ├── 01_bronze_ingest.py
│   ├── 02_silver_transform.py
│   ├── 03_gold_star_schema.ipynb
│   ├── 04_gold_aggregates.ipynb
│   └── 05_hospital_info.ipynb
├── scripts/            Local Python utilities
│   └── profile_raw_csv.py
├── docs/               Project documentation
│   ├── data_profiling_notes.md
│   ├── data_quality_log.md
│   ├── gold_build_log.md
│   ├── silver_cleaning_log.md
│   ├── run_evidence/   HTML exports of the Databricks runs, with all outputs
│   └── profile_output.json
├── data/raw/           Local copy of the source CSV (git-ignored)
├── dashboards/         Tableau workbook (Weeks 7-8)
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

## Gold layer

**Purpose.** Reshape Silver into a star schema for analysis and Tableau, and add the per-DRG benchmarks, hospital deviation scores and data quality flags that need aggregation across rows.

**Tables.** All Delta, built by `notebooks/03_gold_star_schema.ipynb` in Spark SQL.

| Table | Grain | Rows | Contents |
|---|---|---|---|
| `gold_dim_hospital` | One row per hospital (CCN) | 2,906 | Name, street, city, state, ZIP, RUCA code and description, `urban_rural`, `is_maryland` |
| `gold_dim_drg` | One row per DRG | 540 | `drg_cd`, `drg_desc` |
| `gold_fact_inpatient` | Hospital x DRG | 145,879 | Discharges, average and total charges and payments, `markup_ratio` |
| `gold_drg_benchmark` | One row per DRG, Maryland excluded | 539 | `n_hospitals`; median, Q1 and Q3 of `avg_total_payment`; `is_thin_drg` (fewer than 30 hospitals) |
| `gold_hospital_drg_deviation` | Hospital x DRG | 145,878 | `payment_ratio` (payment / DRG median), quartiles, `is_thin_drg`, `is_payment_outlier` (above Q3 + 3 x IQR, non-thin DRGs only) |
| `gold_hospital_drg_count` | One row per hospital | 2,906 | `n_drgs`, `is_low_drg_hospital` (fewer than 5 DRGs) |

**Design choices.**
- *Keys checked first.* Profiling cells confirm one row per hospital x DRG, one set of attributes per CCN, one description per DRG code, and no nulls in the hospital attributes.
- *Benchmark = plain median of total payment, Maryland excluded.* Each hospital counts once, and Maryland's all-payer waiver would distort the typical price. Maryland hospitals are still scored against the non-Maryland median.
- *Deviation as a ratio.* A `payment_ratio` of 1.25 means 25% above the DRG's typical payment, which is comparable across cheap and expensive DRGs.
- *Flags, not deletions.* Thin DRGs (229 of 539), low-DRG hospitals (370 of 2,906) and payment outliers (2,358 rows) are flagged so later analysis can filter them.
- *Sensitivity checks.* A thin-DRG cutoff of 10 leaves 149 thin DRGs, and 1.5 x IQR flags 7,572 outliers; the main rules were kept.

DRG 950 is reported only by Maryland hospitals, so it has no benchmark and drops out of the deviation table (DQ-22). Every Gold decision is recorded in [`docs/data_quality_log.md`](docs/data_quality_log.md) (DQ-14, DQ-16, DQ-17, DQ-22), and every build step and validation result is listed in [`docs/gold_build_log.md`](docs/gold_build_log.md).

### Week 4 aggregates

Built in `notebooks/04_gold_aggregates.ipynb` on top of the star schema. The headline measure is a **case-mix-adjusted payment index**: actual total payment divided by expected payment, where expected = discharges x the DRG's national median payment. An index of 1.00 means paid the national median for that exact mix of DRGs.

| Table | Grain | Rows | Contents |
|---|---|---|---|
| `gold_dim_state` | One row per state (50 + DC) | 51 | Census region and division |
| `gold_state_summary` | One row per state | 51 | Volume, payment per discharge, weighted markup, expected payment, `payment_index` (NULL for Maryland), `is_small_state` |
| `gold_region_summary` | Division, region and national rows (`geo_level`) | 14 | Same measures via `GROUP BY ROLLUP`; Maryland excluded from the index only |
| `gold_hospital_index` | One row per non-Maryland hospital | 2,862 | Index, DRG count, Week 3 outlier-cell count and share, `is_low_drg_hospital`, `is_hospital_outlier` (above Q3 + 3 x IQR, at least 5 DRGs; 51 flagged) |
| `gold_ruca_summary` | RUCA group, urban/rural and national rows (`ruca_level`) | 9 | Same measures by rural/urban status, Maryland excluded |

Every table reconciles to the Silver totals to the cent. Key findings: state index ranges from 0.84 (AR) to 1.45 (NY); the 51 hospital outliers are almost all public safety-net systems; the urban payment premium falls from 41% raw to 11% after case-mix adjustment; and $8.6B (9.8% of non-Maryland payments) was paid above the state median for each DRG, much of it designed policy adjustment (DQ-23). Decisions, checks and findings are in Part 2 of [`docs/gold_build_log.md`](docs/gold_build_log.md).

### Week 5: hospital attributes (second dataset)

Built in `notebooks/05_hospital_info.ipynb` from the CMS Hospital General Information snapshot of 2024-10-30.

| Table | Grain | Rows | Contents |
|---|---|---|---|
| `bronze_hospital_info` | One row per hospital in the CMS file | 5,394 | All 39 source columns as STRING with their original names (Delta column mapping), plus `_ingest_ts`, `_source_file` |
| `silver_hospital_info` | One row per hospital | 5,394 | `ccn`, name, state, `hospital_type`, original `hospital_ownership`, `ownership_group` (For-profit, Non-profit, Government, Federal (VA/DoD)), `has_emergency_services`, `star_rating` (INT, NULL when not available), `rating_category` ('1' to '5' or 'Unrated') |
| `gold_dim_hospital_profile` | One row per inpatient hospital | 2,906 | The Silver attributes joined on `ccn`, plus `is_profile_matched`. Joins to `gold_dim_hospital` and `gold_hospital_index` on `ccn` |

2,899 of 2,906 inpatient hospitals match, all of them Acute Care Hospitals. Among them: 1,875 non-profit, 631 for-profit, 393 government; star ratings 1 to 5 for 2,517 and Unrated for 382. The 7 unmatched hospitals keep NULL attributes (DQ-25).

## Weekly roadmap

| Week | Focus | Status |
|---|---|---|
| 1 | Environment + Git; Bronze ingest; profile all columns | Done (2026-10-08) |
| 2 | Silver: clean, type, markup ratio; data-quality log | Done (2026-10-08) |
| 3 | Gold star schema; per-DRG medians and hospital deviation | Done (2026-10-27) |
| 4 | Gold by state/region, hospital outliers, RUCA rural/urban | Done (2026-11-02) |
| 5 | Second dataset: Hospital General Information Bronze, Silver, and CCN join to Gold (completes LO1) | Done (2026-11-03) |
| 6 | Python: H1 to H4 hypothesis tests; regression of cost on quality, ownership and location; residual-ranked hospitals | Nov 4 to 10 |
| 7 | Sense-check findings with data and healthcare contacts; Tableau prototype (v1) | Nov 11 to 17 |
| 8 | Tableau dashboard v2 for a non-technical viewer | Nov 18 to 24 |
| 9 | Short report draft with one recommendation | Nov 25 to Dec 1 |
| 10 | Finalize dashboard, report, repo and README | Dec 2 to 8 |
| 11 | Final walkthrough with supervisor | Dec 9 to 18 |

### Changes from the proposal

- **Second dataset integrated in Week 5** rather than Weeks 1 to 3. Weeks 1 to 4 built the full inpatient pipeline first; no result from those weeks depends on the second dataset, so nothing was rebuilt.
- **Case-mix-adjusted payment index added** (Week 4). Raw payment per discharge mixes hospital prices with the mix of procedures each hospital treats, so comparisons use actual vs expected payment.
- **Hypothesis tests moved from Week 4 to Week 6**, alongside the regression, because H2 and H3 need the second dataset.
- **CCN normalization:** the proposal expected the inpatient file to have lost leading zeros. Reading every column as text in Bronze preserved them, and Silver enforces a 6-digit format (DQ-02), so the join needs no padding.

## AI assistance

This project uses Claude (Anthropic) as a coding and writing assistant. To be transparent about who did what:

| Week | Claude | Me (Ben Cheng) |
|---|---|---|
| 1 to 2 | Drafted the profiling script, the Bronze and Silver notebooks, the README, and the profiling, data-quality and cleaning logs | Reviewed every file, set up GitHub and Databricks, ran and validated both pipelines (all checks passed), and own the methodology decisions recorded in the logs |
| 3 | Specs, concept explanations, hints and code review. Also used as an automation tool to type up documentation (data-quality log entries, notebook comments, README updates) from my decisions and results | Writing the code and analysis myself, and making every methodology decision and producing every result that the documentation records |
| 4 (2026-10-27) | Proposed the Week 4 build plan: the five Gold tables, the case-mix-adjusted payment index, expected checks against Silver, and the design questions to settle. No code | Reviewed the plan and set the Week 4 scope |
| 4 (2026-11-02) | Recommended answers to the design questions and supplied the Census region reference data. Provided example SQL for notebook cells 2 to 17 (`gold_dim_state`, `gold_state_summary`, `gold_region_summary` and their checks). From cell 18 on, hints, concept explanations and code review, plus a fill-in-the-blank skeleton for the RUCA summary (cell 27) and corrected lines when I was stuck (the outlier flag in cell 20, parts of cell 33). Wrote the cell comment headers and typed up documentation from my results | Chose and own every design decision; adapted, ran, debugged and verified every cell in Databricks, including fixing syntax errors and restructuring check cells; wrote cells 18 onward myself (hospital index with the multi-key join that avoids fan-out, outlier thresholds, RUCA checks, sensitivity check and payment variation query); caught a misread in review; interpreted all results and findings |

| 5 (2026-11-02) | Compared the repo to the approved proposal and identified the missing second dataset; profiled the new file and previewed the join locally; drafted the revised roadmap and the five design questions; wrote notebook 05 cells 1 to 4 (decisions, config, file check, Bronze ingest, adapted from my Week 1 notebook), the README changes and the decision log entries at my request | Chose every design decision (snapshot, unrated hospitals, ownership groups, unmatched hospitals) and uploaded the data |
| 5 (2026-11-03) | Found and downloaded the CMS archived 2024-10-30 snapshot at my request and previewed its join; fixed Cell 4's write for column names with spaces (Delta column mapping); updated cell headers and expected values for the 2024 file at my request; gave cell-by-cell comment outlines, hints and code review, plus corrected lines when I was stuck (the Non-profit LIKE pattern in cell 8, the CASE in cell 11a); typed up this documentation from my results | Chose to switch to the 2024 snapshot and to keep the 7 unmatched hospitals; wrote cells 5 to 11c myself (Bronze checks, category profiles, join preview and unmatched list, Silver table with ownership and rating mapping, Gold hospital profile and all checks); ran and verified every cell in Databricks |

All results in this repo come from runs I performed in Databricks; `docs/run_evidence/` holds the exported notebooks with their outputs.

## Data quality and methodology

See [`docs/data_quality_log.md`](docs/data_quality_log.md) for every known issue and how each layer handles it, and [`docs/data_profiling_notes.md`](docs/data_profiling_notes.md) for the column-by-column profile of the raw file.
