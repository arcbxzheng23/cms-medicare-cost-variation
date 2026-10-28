# Gold Build Log

**Deliverable:** Week 3 (LO1, LO4), build log for the Gold star schema in `workspace.cms`
**Author:** Ben Cheng · **Built:** 2026-10-27 · **Notebook:** `notebooks/03_gold_star_schema.ipynb`
**Status:** All tables built and reconciled in Databricks Free Edition (serverless). Every check below was run in the notebook; the HTML export with outputs is in `docs/run_evidence/`.

---

## 1. Summary

| Table | Built from | Grain | Rows |
|---|---|---|---:|
| `gold_dim_drg` | Silver | DRG | 540 |
| `gold_dim_hospital` | Silver | hospital (CCN) | 2,906 |
| `gold_fact_inpatient` | Silver | hospital x DRG | 145,879 |
| `gold_drg_benchmark` | fact + `gold_dim_hospital` (Maryland excluded) | DRG | 539 |
| `gold_hospital_drg_deviation` | fact + benchmark | hospital x DRG | 145,878 |
| `gold_hospital_drg_count` | fact | hospital (CCN) | 2,906 |

Guiding rule, same as Silver: **Gold never deletes rows for quality reasons.** Thin DRGs, low-DRG hospitals and outliers are flagged, so every exclusion is visible and reversible. The only rows missing from a Gold table are ones a join cannot score (DRG 950, see G6).

## 2. Profiling before building (cells 2 to 8)

| Check | Cell | Result |
|---|---|---|
| Silver schema | 2 | 29 columns |
| Silver row count | 3 | 145,879 |
| Grain: rows = distinct (ccn, drg_cd) | 4 | 145,879 = 145,879 |
| Distinct hospitals / DRGs | 5 | 2,906 / 540 |
| Hospitals with more than one name, city, state, ZIP, RUCA code or street address | 6 | 0 |
| Nulls in hospital attributes | 7 | 0 in every column |
| DRG codes with more than one description | 8 | 0 |

These confirm that `ccn` and `drg_cd` are clean keys, so `SELECT DISTINCT` builds each dimension with exactly one row per key.

## 3. Build steps

| # | Step | Table and columns | Cell | DQ issue | Why |
|---|---|---|---|---|---|
| G1 | DRG dimension | `gold_dim_drg`: `drg_cd`, `drg_desc` | 9 to 10 | DQ-06 | One description per code, keyed on `drg_cd` |
| G2 | Hospital dimension | `gold_dim_hospital`: `ccn`, name, street, city, state, ZIP, RUCA code and description, `urban_rural`, `is_maryland` | 11 | DQ-07, DQ-12, DQ-13 | Keyed on CCN because names are not unique; carries the Maryland flag and the rural/urban grouping |
| G3 | Fact table | `gold_fact_inpatient`: `ccn`, `drg_cd`, discharges, average and total charges and payments, `markup_ratio` | 12 | DQ-04 | Measures only, same grain as Silver |
| G4 | DRG benchmark | `gold_drg_benchmark`: `n_hospitals`, `median_payment`, `q1_payment`, `q3_payment`, `is_thin_drg` | 13 | DQ-13, DQ-15, DQ-16 | Plain median of `avg_total_payment` across non-Maryland hospitals, so each hospital counts once; thin = fewer than 30 hospitals |
| G5 | Hospital DRG count | `gold_hospital_drg_count`: `n_drgs`, `is_low_drg_hospital` | 15 | DQ-17 | Hospital-level comparisons need at least 5 DRGs |
| G6 | Missing-benchmark check | query only | 14 | DQ-22 | Finds DRGs with no benchmark: DRG 950 (Aftercare without CC/MCC), billed only by Maryland hospitals |
| G7 | Hospital deviation | `gold_hospital_drg_deviation`: `payment_ratio`, quartiles, `is_thin_drg`, `is_payment_outlier` | 16 to 17 | DQ-14 | A ratio to the DRG median is comparable across DRGs; outlier = above Q3 + 3 x IQR within the DRG, non-thin DRGs only. Maryland hospitals are scored against the non-Maryland median |

**Deliberately not done in Gold yet:** state and region roll-ups and the RUCA rural/urban comparison (Week 4), and a dollar-difference deviation for the savings estimate (Weeks 5 to 7).

## 4. Validation results

| Check | Expected | Result |
|---|---|---|
| `gold_dim_drg` rows | 540 (distinct DRGs) | 540 |
| `gold_dim_hospital` rows | 2,906 (distinct CCNs) | 2,906 |
| `gold_fact_inpatient` rows | 145,879 (= Silver) | 145,879 |
| `gold_drg_benchmark` rows | 540 or slightly fewer | 539 (DRG 950 has no non-Maryland hospitals) |
| `gold_hospital_drg_deviation` rows | 145,879 minus the DRG 950 rows | 145,878 (DRG 950 had 1 row) |
| Median `payment_ratio`, all rows | close to 1 | 1.005 |
| Thin DRGs (fewer than 30 hospitals) | about 225 (profiling, Maryland included) | 229 of 539 |
| Low-DRG hospitals (fewer than 5 DRGs) | 370 (profiling) | 370 of 2,906 |
| Payment outliers (3 x IQR, non-thin DRGs) | small share of rows | 2,358 rows (1.6%) |

## 5. Sensitivity checks (cells 18 to 19)

| Rule | Main setting | Result | Alternative | Result | Decision |
|---|---|---:|---|---:|---|
| Thin DRG (DQ-16) | fewer than 30 hospitals | 229 DRGs | fewer than 10 | 149 DRGs | Keep 30: a cutoff of 10 brings back only 80 DRGs |
| Payment outlier (DQ-14) | 3 x IQR | 2,358 rows | 1.5 x IQR | 7,572 rows | Keep 3 x IQR: payments are right-skewed, so 1.5 x IQR mostly flags normal high-end prices |

Week 3 deliverable complete: Gold star schema, benchmarks, deviation scores and flags built, validated and documented.
