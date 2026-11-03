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
| DQ-03 | CMS suppression: cells with ≤10 discharges are excluded | `Tot_Dschrgs` min = 11 exactly | High | Report | Treat absent hospital x DRG combos as *unknown*, not zero. Results describe higher-volume cells only. State this in every chart and the report | Open. Week 4: every index, outlier flag and the $8.57B payment-variation figure describe reported (11+ discharge) cells only |
| DQ-04 | Values are averages, not totals | Column names `Avg_*`; data dictionary definitions | High | Silver/Gold | Derive `tot_*_amt = avg x Tot_Dschrgs` in Silver. Any roll-up (state, DRG, hospital) must be discharge-weighted, never a plain average of averages | Totals derived in Silver T7 (verified in Databricks 2026-10-08); weighting applies in Gold |
| DQ-05 | Unrounded averages | Up to 7 decimal places | Low | Gold | Keep full precision through Gold; round to cents only for display (Tableau / report) | Applied in Gold summaries: full precision stored, ROUND only in result queries (Week 4); final display rounding in Tableau |
| DQ-06 | `DRG_Desc` truncated at 88 characters | 8 descriptions shared by 20 codes (e.g. 456/457/458, 216/217, 219/220/221) | Med | Gold | Key on `DRG_Cd` everywhere. In `dim_drg`, show code + description (e.g. "457 · Spinal fusion..."). Optional: join full MS-DRG titles from the CMS MS-DRG definitions table | Keyed on `drg_cd` in every Gold table (Weeks 3 to 4); code + description display label still to add in Tableau (Week 8) |
| DQ-07 | Hospital names not unique | 40 names belong to 2+ CCNs ("Good Samaritan Hospital", "Mercy Medical Center", "St Mary's Medical Center" x4 each) | Med | Gold | Key on CCN. Display label = name + city + state | Keyed on `ccn` in every Gold table; `gold_hospital_index` carries name, city and state for display labels (Week 4); combined label to build in Tableau (Week 8) |
| DQ-10 | Inconsistent casing | Names are CMS title case ("Nyu Langone Hospitals", "Hlth"); DRG_Desc is ALL CAPS | Low | Gold | Leave as is for traceability; optionally add a display-cased DRG description | Open |
| DQ-13 | Maryland all-payer waiver; markup < 1 | 223 rows (80 hospitals) have charge < total payment, 61 of them in MD. MD median markup 1.12 vs ~4.5 nationally. CMS methodology confirms MD is exempt from IPPS | High | Silver/Analysis | Add `is_maryland` flag. Exclude MD from markup comparisons (or show separately); keep MD in payment analyses with a note. Do not delete rows | Flagged in Silver T11 (verified in Databricks 2026-10-08); exclusion applied in analysis. Week 4: payment index NULL for Maryland in `gold_state_summary`, Maryland excluded from both sides of the index in `gold_region_summary`, and excluded entirely from `gold_hospital_index` and `gold_ruca_summary`; 436 of the 2,358 Week 3 outlier cells are Maryland rows |
| DQ-14 | Extreme values in low-volume cells | Max charge $7.20M (Temple Univ. Hosp., DRG 018, 16 discharges); max payment $1.44M (Ascension St Vincent, DRG 466, 18 discharges). All dollar columns strongly right-skewed | Med | Gold/Analysis | Do not drop. Use medians, per-DRG normalization (ratio to DRG median), and flag outliers with a robust rule (e.g. > 3 x IQR above Q3 within the DRG). Report outliers alongside their discharge count | Handled in Gold: rule = payment above Q3 + 3 x IQR within the DRG, thin DRGs excluded; `is_payment_outlier` in `gold_hospital_drg_deviation` flags 2,358 of 145,878 rows (2026-10-27). Sensitivity check: 1.5 x IQR flags 7,572 rows (about 3.2 times as many), mostly normal high-end prices in right-skewed data; 3 x IQR kept as the main rule. Week 4: 1,922 of the flagged cells belong to non-Maryland hospitals and 436 to Maryland hospitals (scored against the non-Maryland median); the hospital-level index uses the same 3 x IQR rule |
| DQ-16 | Thin DRGs | Hospitals per DRG: median 53, min 1. 100 DRGs have < 5 hospitals, 225 have < 30 | Med | Gold | Set a minimum hospital count for DRG-level variation stats (proposed ≥ 30; test sensitivity at 10). Keep thin DRGs in the fact table but mark them `is_thin_drg` | Handled in Gold: cutoff 30 chosen; 229 of 539 non-Maryland DRGs flagged `is_thin_drg` in `gold_drg_benchmark` (2026-10-27). Sensitivity check: 149 DRGs have fewer than 10 hospitals, so a cutoff of 10 would bring back only 80 DRGs; 30 kept as the main rule. Week 4: state payment index with non-thin DRGs only moves no state by more than 0.006, so thin DRGs are kept in expected payment |
| DQ-17 | Hospitals with few DRGs | 93 hospitals have 1 DRG row; 370 have < 5 | Med | Gold | Hospital-level cost indices require a minimum DRG count (proposed ≥ 5); flag the rest | Handled in Gold: cutoff 5 chosen; 370 of 2,906 hospitals flagged `is_low_drg_hospital` in `gold_hospital_drg_count` (2026-10-27). Week 4: 369 of the 2,862 non-Maryland hospitals are low-DRG; they stay in `gold_hospital_index` but are never flagged as hospital outliers |
| DQ-19 | Calendar-year data spans two DRG versions | Methodology: MEDPAR is calendar year since the April 2023 update. CY2024 covers the end of FY2024 (MS-DRG v41) and the start of FY2025 (v42, from Oct 1 2024) | Low | Report | Note as a limitation; check that no DRG code in the file changed meaning between v41 and v42 | Open |
| DQ-20 | Documentation drift | Local data dictionary is the May 2023 (RY23) version: calls the ID `Rndrng_CCN` and describes it as "outpatient"; file uses `Rndrng_Prvdr_CCN` | Low | Docs | Download the current RY26 data dictionary and methodology from data.cms.gov and store them in `docs/` | Open |
| DQ-21 | Population scope | Original Medicare FFS, IPPS short-term hospitals only; no Medicare Advantage, Medicaid, private, uninsured; no territories (51 = 50 states + DC) | High | Report | State scope in the README, the dashboard, and the report. Findings describe Medicare FFS prices only, not hospital prices overall | Open. Week 4: Kaiser Foundation hospitals appear among the hospital outliers with only 6 to 20 DRGs, likely because most Kaiser Medicare members are in Medicare Advantage, which this data excludes; treat as a scope effect |
| DQ-22 | DRG with no non-Maryland benchmark | DRG 950 (Aftercare without CC/MCC) is reported only by Maryland hospitals. `gold_drg_benchmark` (Maryland excluded) has 539 rows vs 540 in `gold_dim_drg`; found with a LEFT JOIN on `drg_cd` | Low | Gold | Keep DRG 950 rows in the fact table and `gold_dim_drg`. With no non-Maryland median, these rows get no deviation score. Note in the report | Found in Gold 2026-10-27; documented, no fix needed |
| DQ-23 | Geographic and policy payment adjustments | State payment index ranges 0.843 (AR) to 1.449 (NY); top states are high-wage areas, and the hospitals with the most outlier cells are academic and safety-net hospitals (80% to 85% of cells flagged at Zuckerberg SF General, LA General, Jacobi). IPPS deliberately pays more through the area wage index, teaching (IME) and disproportionate-share (DSH) add-ons, and outlier payments | High | Analysis/Report | Do not describe index differences as overpayment or waste. Call dollar figures "payment variation", not "savings", unless adjusted. Week 5: test how much of the state spread the CMS wage index explains | Opened 2026-11-02 (Week 4). Evidence: the 51 hospital outliers are almost all public safety-net systems; urban vs rural gap falls from 41% raw to 11% after case-mix adjustment; $8.57B (9.75% of non-Maryland payments) paid above the state median per DRG, reported as variation, not savings |

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
| 2026-11-02 | Headline measure = payment index (Σ actual total payment / Σ discharges x DRG median), totals over totals | Adjusts for case mix, so states and hospitals with costlier DRG mixes are not mistaken for higher payers (DQ-04, DQ-15) |
| 2026-11-02 | Expected payment uses all 539 benchmarks; non-thin only as a sensitivity check | Keeps every discharge on both sides of the index; discharge weighting limits the effect of thin DRGs (DQ-16) |
| 2026-11-02 | Hospital outlier = payment index above Q3 + 3 x IQR across non-low-DRG hospitals; upper fence only | Same rule as DQ-14; the index has a floor near 0.6 but a right tail to 9.95 (DQ-14, DQ-17) |
| 2026-11-02 | RUCA headline = binary `urban_rural`; four RUCA groups kept; Unknown kept separate | Small town and Rural groups are too thin for headlines (DQ-12) |
| 2026-11-02 | Census regions (4) and divisions (9) in `gold_dim_state`; regions used for reporting | Readable headline grain, finer grain available for Week 5 |
| 2026-11-02 | Maryland kept in state and region summaries for volume and markup; payment index NULL or excluded | No IPPS benchmark (DQ-13) |
| 2026-11-02 | `is_small_state` flags states with fewer than 10 hospitals (7 states) | Indexes from few hospitals are unstable; the flag travels into Tableau for footnotes or shading |
| 2026-11-02 | Hospital index and RUCA summary exclude Maryland entirely | No benchmark, and the Silver reference values for RUCA groups exclude Maryland (DQ-13) |
| 2026-11-02 | Payment variation reported as dollars above the state median per DRG ($8.57B, 9.75%), not as savings | Much of the variation is designed policy adjustment (DQ-23) |

## Closed issues

Issues move here once they are fixed and verified, with nothing left for later layers or the report. Closed 2026-10-27 (DQ-01, 02, 08, 09, 11, 12, 18) and 2026-11-02 (DQ-15); the Status column says how each was resolved.

| ID | Issue | Evidence | Sev. | Layer | Planned handling | Status |
|---|---|---|---|---|---|---|
| DQ-01 | Numeric columns stored as text | `Tot_Dschrgs` and the three `Avg_*` dollar columns are STRING in Bronze by design | High | Silver | Cast `Tot_Dschrgs` to INT and dollar columns to DECIMAL(18,7) with `try_cast`; assert 0 cast failures | Handled in Silver T2/T3 (verified in Databricks 2026-10-08) |
| DQ-02 | Code columns have leading zeros | Rows starting with `0`: CCN 24,798 · FIPS 23,683 · DRG 14,415 · ZIP 12,973 | High | All | Keep CCN, FIPS, ZIP, DRG_Cd as STRING in every layer; add a Silver assert on fixed lengths (6/2/5/3) | Handled in Silver T4 + constraint (verified in Databricks 2026-10-08) |
| DQ-08 | Control character in a hospital name | U+0096 (a Windows-1252 en dash decoded incorrectly) in CCN `670128` "Baylor Scott & White Medical Center [U+0096] Pflugerville", 2 rows | Low | Silver | Replace U+0096 with `-`; general rule: strip C1 control characters (U+0080 to U+009F) | Handled in Silver T5 (verified in Databricks 2026-10-08) |
| DQ-09 | Repeated internal spaces | Org name: 34 hospitals / 2,103 rows (e.g. "Macneal  Hospital"); street: 2,449 rows | Low | Silver | `regexp_replace(col, '\\s+', ' ')` and `trim` on text columns | Handled in Silver T6 (verified in Databricks 2026-10-08) |
| DQ-11 | Misleading column name | `Rndrng_Prvdr_St` is the **street address**, not state (confirmed by the data dictionary); 2.8% are PO boxes or named addresses | Med | Silver | Rename to `prvdr_street_addr`; adopt clean snake_case names for all columns in Silver | Handled in Silver T1 (verified in Databricks 2026-10-08) |
| DQ-12 | RUCA needs a rural/urban grouping | 19 codes for 15 descriptions; decimal sub-codes (`1.1`, `10.3`); `99` = Unknown (578 rows, 12 hospitals, mostly SD and CA). Code 1 = 87% of rows | Med | Silver | Derive `ruca_primary = floor(code)` and `ruca_group`: 1 to 3 Metropolitan, 4 to 6 Micropolitan, 7 to 9 Small town, 10 Rural, 99 Unknown. Also a binary `urban_rural` (Metro vs non-Metro). Keep Unknown as its own bucket, do not impute | Handled in Silver T10 (verified in Databricks 2026-10-08). Week 4: `gold_ruca_summary` derives the group from `ruca_code` in Gold; hospital counts and markups match Silver exactly |
| DQ-18 | Facility-type range | 2,899 CCNs in short-term acute range 0001 to 0879; 7 CCNs (121 rows) in 0880 to 0899 | Low | Silver | Derive `ccn_type` from digits 3 to 6. Confirm the meaning of 0880 to 0899 in the CMS CCN numbering guide before deciding whether to keep them | Silver T12; all 7 CCNs in 0880-0899 are Texas acute-care hospitals (CCN 4508xx), kept in scope |
| DQ-15 | Choice of cost measure | Medicare share of total payment ranges 4.5% to 100% (median 82.9%) | Med | Methodology | Decide in Week 2: proposed primary = `Avg_Tot_Pymt_Amt` (full payment for the stay), secondary = `Avg_Mdcr_Pymt_Amt`; charges used only for markup | Decided 2026-10-27: `avg_total_payment` is the primary cost measure for benchmarks, deviation and the payment index; charges used only for markup. Closed 2026-11-02 |
