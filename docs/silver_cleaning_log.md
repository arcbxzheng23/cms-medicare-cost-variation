# Silver Cleaning Log

**Deliverable:** Week 2 (LO1, LO4), cleaning log for `workspace.cms.silver_cms_inpatient`
**Author:** Ben Cheng · **Drafted:** 2026-10-08 · **Notebook:** `notebooks/02_silver_transform.py`
**Status:** Logic verified two ways before the Databricks run: (1) pandas recomputation of every expected value, and (2) a local Apache Spark 4.0.1 dry run of notebooks 01 and 02 against the real CSV, where all 32 checks passed and every summary in section 4 matched to the cent. Not testable locally: Unity Catalog volume, Delta-only statements (CHECK constraints, column comments, DESCRIBE HISTORY). Databricks results go in section 5.

---

## 1. Summary

| | Bronze | Silver |
|---|---|---|
| Rows | 145,879 | 145,879 (none removed) |
| Columns | 15 source + 3 lineage, all STRING | 29 typed, cleaned and derived columns (incl. 3 lineage) |
| Grain | hospital (CCN) x MS-DRG | unchanged |

Guiding rule: **Silver changes values and adds columns, it never drops rows.** Anything that should be left out of an analysis is flagged, so every exclusion is visible and reversible.

## 2. Transformations

| # | Transformation | Columns affected | Rows changed | DQ issue | Why |
|---|---|---|---:|---|---|
| T1 | Rename to snake_case | all | n/a | DQ-11 | Clear names; `Rndrng_Prvdr_St` becomes `provider_street_addr` so nobody mistakes it for state |
| T2 | Cast `Tot_Dschrgs` to INT | `tot_discharges` | 145,879 (0 failures) | DQ-01 | Needed for maths and weighting |
| T3 | Cast dollar columns to DECIMAL(18,7) | `avg_submitted_charge`, `avg_total_payment`, `avg_medicare_payment` | 145,879 (0 failures) | DQ-01, DQ-05 | DECIMAL is exact (no floating-point drift); 7 decimals preserves the source precision |
| T4 | Keep codes as STRING | `ccn`, `drg_cd`, `state_fips`, `zip5`, `ruca_code` | 0 | DQ-02 | Preserves leading zeros; enforced by a CHECK constraint on formats |
| T5 | Replace U+0096 with `-` and strip other C1 control characters | all text columns | 2 (CCN 670128) | DQ-08 | "Baylor Scott & White Medical Center - Pflugerville" now displays correctly |
| T6 | Collapse repeated whitespace and trim | all text columns | 2,103 names + 2,449 streets | DQ-09 | Consistent labels in Tableau and joins. Distinct names stay at 2,845, so no names were merged or split |
| T7 | Derive totals = average x discharges | `tot_submitted_charge`, `tot_total_payment`, `tot_medicare_payment` | new | DQ-04 | Allows correct discharge-weighted roll-ups: `SUM(tot_x) / SUM(tot_discharges)` |
| T8 | Derive **markup ratio** = charge / total payment | `markup_ratio` | new | Week 2 | How many dollars a hospital bills for each dollar it is paid |
| T9 | Derive Medicare share = Medicare payment / total payment | `medicare_share` | new | DQ-15 | Shows how much of the payment Medicare itself covers vs patient and third parties |
| T10 | RUCA grouping | `ruca_primary`, `ruca_group`, `urban_rural` | new | DQ-12 | Metropolitan 1-3, Micropolitan 4-6, Small town 7-9, Rural 10, Unknown 99. `urban_rural`: Urban = 1-3, Rural = 4-10. Unknown is kept, never guessed |
| T11 | Flags | `is_maryland`, `is_markup_below_1` | 3,531 / 223 | DQ-13 | Maryland's all-payer waiver makes its markups incomparable |
| T12 | CCN facility suffix | `ccn_facility_suffix` | new | DQ-18 | Last 4 digits of CCN; keeps facility type traceable |
| T13 | Lineage | `_bronze_ingest_ts`, `_source_file`, `_silver_processed_ts` | new | n/a | Every row traceable to its Bronze load and source file |

**Constraints added** (Delta CHECK constraints, so a future bad write fails loudly):
`tot_discharges >= 11` · all three dollar averages > 0 · Medicare payment ≤ total payment · CCN 6 digits, DRG 3 digits, FIPS 2 digits, ZIP 5 digits.

**Deliberately not done in Silver** (needs aggregation, so it belongs in Gold, Week 3): thin-DRG flag (DQ-16), hospitals with few DRGs (DQ-17), outliers within each DRG (DQ-14), per-DRG medians and hospital deviation.

## 3. Expected validation results

Computed independently in pandas from the same CSV. The Silver notebook asserts every one of these.

| Check | Expected |
|---|---|
| Rows | 145,879 (= Bronze) |
| Cast failures (any typed column) | 0 |
| Duplicate (ccn, drg_cd) | 0 |
| Hospitals / DRGs | 2,906 / 540 |
| Total discharges | 4,952,481 |
| Total payment | $90,927,479,550.00 |
| Total Medicare payment | $75,111,479,229.00 |
| Total submitted charges | $457,648,118,614.10 |
| Control characters, double spaces, untrimmed values left | 0 in every text column |
| Distinct provider names | 2,845 (unchanged) |
| Maryland rows / hospitals | 3,531 / 44 |
| Markup < 1 rows | 223 (61 in Maryland, 162 elsewhere) |
| RUCA groups (rows) | Metropolitan 131,744 · Micropolitan 11,426 · Small town 1,561 · Rural 570 · Unknown 578 |
| Urban / Rural / Unknown (rows) | 131,744 / 13,557 / 578 |

## 4. First look at the markup ratio

From the pandas check of the same logic. "Weighted" means totals divided by totals (DQ-04).

**National, with Maryland separated**

| Segment | Hospitals | Discharges | Payment per discharge | Weighted markup | Median row markup | Rows markup < 1 |
|---|---:|---:|---:|---:|---:|---:|
| Maryland | 44 | 130,650 | $23,701.39 | 1.11 | 1.12 | 61 |
| All other states + DC | 2,862 | 4,821,831 | $18,215.26 | 5.17 | 4.54 | 162 |
| National | 2,906 | 4,952,481 | $18,359.99 | 5.03 | 4.48 | 223 |

**By RUCA group (excluding Maryland)**

| Group | Hospitals | Discharges | Payment per discharge | Weighted markup |
|---|---:|---:|---:|---:|
| Metropolitan | 2,101 | 4,425,789 | $18,651.20 | 5.25 |
| Micropolitan | 515 | 323,532 | $13,221.78 | 3.88 |
| Small town | 196 | 37,260 | $13,222.17 | 3.32 |
| Rural | 38 | 15,699 | $12,685.63 | 4.08 |
| Unknown | 12 | 19,551 | $16,119.50 | 5.59 |

**States with the highest and lowest weighted markup (excluding Maryland)**

| Highest | Markup | Lowest | Markup |
|---|---:|---|---:|
| NV | 9.10 | MA | 2.67 |
| CO | 7.36 | RI | 2.74 |
| FL | 7.12 | MT | 2.92 |
| TX | 6.77 | WY | 3.00 |
| NJ | 6.54 | OR | 3.19 |

**Read with care.** These are raw comparisons, not adjusted for case mix: metropolitan hospitals treat more complex DRGs, which by itself raises payment per discharge. Fair comparisons need per-DRG normalization (each hospital's value divided by the DRG median), which is the Week 3 Gold work. Spark's `percentile_approx` gives approximate medians, so median values may differ from pandas in the second decimal.

## 5. Databricks run results

*To be filled in after the notebook runs: paste the validation table (all PASS), the three summary query outputs, and the Delta version number from `DESCRIBE HISTORY`.*

| Item | Result |
|---|---|
| Run date | |
| Validation checks | __ / 32 passed |
| Silver Delta version | |
| Differences from section 3 / 4 | |
