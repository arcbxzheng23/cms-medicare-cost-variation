# Data-Quality Log

Running log of data-quality issues and methodology decisions for the CMS Medicare inpatient pipeline (LO4). Each issue is found in profiling (Week 1), handled in the layer named, and closed with a note on what was done.

**Source:** `MUP_INP_RY26_P03_V10_DY24_PrvSvc.CSV` · **Evidence:** [`data_profiling_notes.md`](data_profiling_notes.md) · **Opened:** 2026-10-05 (Week 1)

Severity: **High** = would produce wrong numbers if ignored · **Med** = would bias or confuse results · **Low** = cosmetic or documentation.

---

## Checks that passed (no action needed)

| Check | Result |
|---|---|
| Row and column count | 145,879 x 15, matches source |
| Encoding / parsing | UTF-8, no BOM, LF, no multi-line fields, 145,880 lines = header + rows |
| Nulls and blanks | 0 in all 15 columns |
| Duplicates | 0 duplicate rows; (CCN, DRG_Cd) is unique |
| Hospital attributes | Each CCN has exactly one name, city, street, ZIP, state, RUCA |
| State codes | 51 abbreviations, 1:1 with FIPS |
| Numeric format | No `$`, commas, scientific notation, zeros, or negatives; 0 conversion failures |
| Payment logic | Medicare payment ≤ total payment in every row |

## Issues (status column shows where each is handled)

| ID | Issue | Evidence | Sev. | Layer | Planned handling | Status |
|---|---|---|---|---|---|---|
| DQ-01 | Numeric columns stored as text | `Tot_Dschrgs` and the three `Avg_*` dollar columns are STRING in Bronze by design | High | Silver | Cast `Tot_Dschrgs` to INT and dollar columns to DECIMAL(18,7) with `try_cast`; assert 0 cast failures | Handled in Silver T2/T3 (verified in Databricks 2026-10-08) |
| DQ-02 | Code columns have leading zeros | Rows starting with `0`: CCN 24,798 · FIPS 23,683 · DRG 14,415 · ZIP 12,973 | High | All | Keep CCN, FIPS, ZIP, DRG_Cd as STRING in every layer; add a Silver assert on fixed lengths (6/2/5/3) | Handled in Silver T4 + constraint (verified in Databricks 2026-10-08) |
| DQ-03 | CMS suppression: cells with ≤10 discharges are excluded | `Tot_Dschrgs` min = 11 exactly | High | Report | Treat absent hospital x DRG combos as *unknown*, not zero. Results describe higher-volume cells only. State this in every chart and the report | Open |
| DQ-04 | Values are averages, not totals | Column names `Avg_*`; data dictionary definitions | High | Silver/Gold | Derive `tot_*_amt = avg x Tot_Dschrgs` in Silver. Any roll-up (state, DRG, hospital) must be discharge-weighted, never a plain average of averages | Totals derived in Silver T7 (verified in Databricks 2026-10-08); weighting applies in Gold |
| DQ-05 | Unrounded averages | Up to 7 decimal places | Low | Gold | Keep full precision through Gold; round to cents only for display (Tableau / report) | Open |
| DQ-06 | `DRG_Desc` truncated at 88 characters | 8 descriptions shared by 20 codes (e.g. 456/457/458, 216/217, 219/220/221) | Med | Gold | Key on `DRG_Cd` everywhere. In `dim_drg`, show code + description (e.g. "457 · Spinal fusion..."). Optional: join full MS-DRG titles from the CMS MS-DRG definitions table | Open |
| DQ-07 | Hospital names not unique | 40 names belong to 2+ CCNs ("Good Samaritan Hospital", "Mercy Medical Center", "St Mary's Medical Center" x4 each) | Med | Gold | Key on CCN. Display label = name + city + state | Open |
| DQ-08 | Control character in a hospital name | U+0096 (a Windows-1252 en dash decoded incorrectly) in CCN `670128` "Baylor Scott & White Medical Center [U+0096] Pflugerville", 2 rows | Low | Silver | Replace U+0096 with `-`; general rule: strip C1 control characters (U+0080 to U+009F) | Handled in Silver T5 (verified in Databricks 2026-10-08) |
| DQ-09 | Repeated internal spaces | Org name: 34 hospitals / 2,103 rows (e.g. "Macneal  Hospital"); street: 2,449 rows | Low | Silver | `regexp_replace(col, '\\s+', ' ')` and `trim` on text columns | Handled in Silver T6 (verified in Databricks 2026-10-08) |
| DQ-10 | Inconsistent casing | Names are CMS title case ("Nyu Langone Hospitals", "Hlth"); DRG_Desc is ALL CAPS | Low | Gold | Leave as is for traceability; optionally add a display-cased DRG description | Open |
| DQ-11 | Misleading column name | `Rndrng_Prvdr_St` is the **street address**, not state (confirmed by the data dictionary); 2.8% are PO boxes or named addresses | Med | Silver | Rename to `prvdr_street_addr`; adopt clean snake_case names for all columns in Silver | Handled in Silver T1 (verified in Databricks 2026-10-08) |
| DQ-12 | RUCA needs a rural/urban grouping | 19 codes for 15 descriptions; decimal sub-codes (`1.1`, `10.3`); `99` = Unknown (578 rows, 12 hospitals, mostly SD and CA). Code 1 = 87% of rows | Med | Silver | Derive `ruca_primary = floor(code)` and `ruca_group`: 1 to 3 Metropolitan, 4 to 6 Micropolitan, 7 to 9 Small town, 10 Rural, 99 Unknown. Also a binary `urban_rural` (Metro vs non-Metro). Keep Unknown as its own bucket, do not impute | Handled in Silver T10 (verified in Databricks 2026-10-08) |
| DQ-13 | Maryland all-payer waiver; markup < 1 | 223 rows (80 hospitals) have charge < total payment, 61 of them in MD. MD median markup 1.12 vs ~4.5 nationally. CMS methodology confirms MD is exempt from IPPS | High | Silver/Analysis | Add `is_maryland` flag. Exclude MD from markup comparisons (or show separately); keep MD in payment analyses with a note. Do not delete rows | Flagged in Silver T11 (verified in Databricks 2026-10-08); exclusion applied in analysis |
| DQ-14 | Extreme values in low-volume cells | Max charge $7.20M (Temple Univ. Hosp., DRG 018, 16 discharges); max payment $1.44M (Ascension St Vincent, DRG 466, 18 discharges). All dollar columns strongly right-skewed | Med | Gold/Analysis | Do not drop. Use medians, per-DRG normalization (ratio to DRG median), and flag outliers with a robust rule (e.g. > 3 x IQR above Q3 within the DRG). Report outliers alongside their discharge count | Handled in Gold: rule = payment above Q3 + 3 x IQR within the DRG, thin DRGs excluded; `is_payment_outlier` in `gold_hospital_drg_deviation` flags 2,358 of 145,878 rows (2026-10-27). Sensitivity check: 1.5 x IQR flags 7,572 rows (about 3.2 times as many), mostly normal high-end prices in right-skewed data; 3 x IQR kept as the main rule |
| DQ-15 | Choice of cost measure | Medicare share of total payment ranges 4.5% to 100% (median 82.9%) | Med | Methodology | Decide in Week 2: proposed primary = `Avg_Tot_Pymt_Amt` (full payment for the stay), secondary = `Avg_Mdcr_Pymt_Amt`; charges used only for markup | Open |
| DQ-16 | Thin DRGs | Hospitals per DRG: median 53, min 1. 100 DRGs have < 5 hospitals, 225 have < 30 | Med | Gold | Set a minimum hospital count for DRG-level variation stats (proposed ≥ 30; test sensitivity at 10). Keep thin DRGs in the fact table but mark them `is_thin_drg` | Handled in Gold: cutoff 30 chosen; 229 of 539 non-Maryland DRGs flagged `is_thin_drg` in `gold_drg_benchmark` (2026-10-27). Sensitivity check: 149 DRGs have fewer than 10 hospitals, so a cutoff of 10 would bring back only 80 DRGs; 30 kept as the main rule |
| DQ-17 | Hospitals with few DRGs | 93 hospitals have 1 DRG row; 370 have < 5 | Med | Gold | Hospital-level cost indices require a minimum DRG count (proposed ≥ 5); flag the rest | Handled in Gold: cutoff 5 chosen; 370 of 2,906 hospitals flagged `is_low_drg_hospital` in `gold_hospital_drg_count` (2026-10-27) |
| DQ-18 | Facility-type range | 2,899 CCNs in short-term acute range 0001 to 0879; 7 CCNs (121 rows) in 0880 to 0899 | Low | Silver | Derive `ccn_type` from digits 3 to 6. Confirm the meaning of 0880 to 0899 in the CMS CCN numbering guide before deciding whether to keep them | Silver T12; all 7 CCNs in 0880-0899 are Texas acute-care hospitals (CCN 4508xx), kept in scope |
| DQ-19 | Calendar-year data spans two DRG versions | Methodology: MEDPAR is calendar year since the April 2023 update. CY2024 covers the end of FY2024 (MS-DRG v41) and the start of FY2025 (v42, from Oct 1 2024) | Low | Report | Note as a limitation; check that no DRG code in the file changed meaning between v41 and v42 | Open |
| DQ-20 | Documentation drift | Local data dictionary is the May 2023 (RY23) version: calls the ID `Rndrng_CCN` and describes it as "outpatient"; file uses `Rndrng_Prvdr_CCN` | Low | Docs | Download the current RY26 data dictionary and methodology from data.cms.gov and store them in `docs/` | Open |
| DQ-21 | Population scope | Original Medicare FFS, IPPS short-term hospitals only; no Medicare Advantage, Medicaid, private, uninsured; no territories (51 = 50 states + DC) | High | Report | State scope in the README, the dashboard, and the report. Findings describe Medicare FFS prices only, not hospital prices overall | Open |
| DQ-22 | DRG with no non-Maryland benchmark | DRG 950 (Aftercare without CC/MCC) is reported only by Maryland hospitals. `gold_drg_benchmark` (Maryland excluded) has 539 rows vs 540 in `gold_dim_drg`; found with a LEFT JOIN on `drg_cd` | Low | Gold | Keep DRG 950 rows in the fact table and `gold_dim_drg`. With no non-Maryland median, these rows get no deviation score. Note in the report | Found in Gold 2026-10-27; documented, no fix needed |

## Decisions made

| Date | Decision | Reason |
|---|---|---|
| 2026-10-05 | Bronze stores all 15 source columns as STRING, plus `_corrupt_record`, `_ingest_ts`, `_source_file` | Preserves the source exactly (leading zeros, full precision) and makes every later layer rebuildable (DQ-01, DQ-02) |
| 2026-10-05 | Bronze load is a full refresh (`overwrite`) | Single annual source file; re-runs are idempotent and Delta history keeps prior versions |
| 2026-10-05 | No rows are deleted in any layer for quality reasons; problem rows are flagged instead | Keeps totals reconcilable to the source and makes exclusions explicit and reversible |
| 2026-10-08 | Silver dollars stored as DECIMAL(18,7); ratios as DOUBLE | Exact money arithmetic with full source precision; ratios are unitless comparisons |
| 2026-10-08 | RUCA: Metropolitan 1-3, Micropolitan 4-6, Small town 7-9, Rural 10, Unknown 99; Urban = 1-3, Rural = 4-10 | Standard USDA ERS primary-code grouping; Unknown not imputed |
| 2026-10-08 | Maryland flagged (`is_maryland`), excluded from markup comparisons but kept for payment analysis | All-payer waiver makes its charges structurally close to payments |
| 2026-10-08 | Group-level flags (thin DRGs, hospitals with few DRGs, within-DRG outliers) deferred to Gold | They require aggregation across rows, which is Gold's job |
| 2026-10-27 | Gold DRG benchmark (`gold_drg_benchmark`) = plain median of `avg_total_payment` across hospitals per DRG, Maryland excluded | Payment is the primary cost measure (DQ-15); a plain median counts each hospital once; Maryland's all-payer waiver would distort the benchmark (DQ-13) |
| 2026-10-27 | Thin DRG = fewer than 30 non-Maryland hospitals (`is_thin_drg`); sensitivity check at 10 | Medians from few hospitals are unstable (DQ-16) |
| 2026-10-27 | Low-DRG hospital = fewer than 5 DRG rows (`is_low_drg_hospital` in `gold_hospital_drg_count`) | Hospital-level comparisons need enough DRGs to be meaningful (DQ-17) |
| 2026-10-27 | Hospital deviation = ratio of `avg_total_payment` to the DRG median (`payment_ratio` in `gold_hospital_drg_deviation`); Maryland hospitals scored against the non-Maryland median | A ratio is comparable across cheap and expensive DRGs; a dollar difference can be added later for the savings estimate |
| 2026-10-27 | Payment outlier = above Q3 + 3 x IQR within the DRG, only in non-thin DRGs (`is_payment_outlier`); 1.5 x IQR as a sensitivity check | Payments are right-skewed, so 1.5 x IQR would flag normal high-end prices; quartiles from thin DRGs are unstable (DQ-14) |

## Closed issues

None yet.
