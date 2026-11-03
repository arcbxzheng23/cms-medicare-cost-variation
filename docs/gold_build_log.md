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

---

# Part 2: Week 4 aggregates (in progress)

**Deliverable:** Week 4 (LO1, LO4), state, region and hospital roll-ups on top of the Week 3 star schema
**Author:** Ben Cheng · **Started:** 2026-11-02 · **Notebook:** `04_gold_aggregates` (in Databricks; export to `notebooks/` and `docs/run_evidence/` when the week is complete)
**Status:** `gold_dim_state`, `gold_state_summary` and `gold_region_summary` built and reconciled. `gold_hospital_index` base query validated; outlier thresholds and flag not built yet. RUCA summary not started.

## 6. Week 4 design decisions (notebook cell 1)

| # | Decision | Reason |
|---|---|---|
| W4-1 | Headline measure = **payment index** = Σ actual total payment / Σ (discharges x DRG median payment) | Adjusts for case mix: 1.00 = paid the national DRG median for that exact mix of DRGs. Raw payment per discharge and weighted markup kept as descriptive columns |
| W4-2 | Expected payment uses all 539 DRG benchmarks; non-thin only (310) to be run as a sensitivity check | Dropping thin DRGs would measure some hospitals on part of their volume; discharge weighting keeps their effect small |
| W4-3 | Hospital outlier = payment index above Q3 + 3 x IQR across hospitals; low-DRG hospitals not flagged | Same rule as DQ-14 and same exclusion as DQ-17. Upper fence only: the index has a floor near 0.6 but a long right tail (max 9.95) |
| W4-4 | RUCA: binary `urban_rural` is the headline; the four RUCA groups kept in the table; Unknown (99) its own bucket | Small town (1,561 rows) and Rural (570 rows) are too thin for headline findings (DQ-12) |
| W4-5 | `gold_dim_state` carries Census region (4) and division (9); regions used for reporting | One extra column avoids a rebuild if Week 5 needs divisions |
| W4-6 | Maryland kept in state and region summaries for volume and markup; its payment index is NULL / excluded | No IPPS benchmark (DQ-13) |

## 7. Week 4 build steps

| # | Step | Table and columns | Cells | DQ issue | Why |
|---|---|---|---|---|---|
| G8 | State dimension | `gold_dim_state`: `state_abbr`, `census_region`, `census_division` (inline `VALUES`, US Census Bureau regions; DC in South / South Atlantic) | 2 to 6 | DQ-21 | Lookup for regional roll-ups, keyed on the state abbreviation already in `gold_dim_hospital` |
| G9 | State summary | `gold_state_summary`: region, division, `is_small_state` (fewer than 10 hospitals), `n_hospitals`, discharges, payment, charges, `payment_per_discharge`, `markup_ratio`, `expected_payment`, `payment_index` | 7 to 12 | DQ-04, DQ-13, DQ-22 | Totals over totals. LEFT JOIN to the benchmark keeps Maryland's DRG 950 rows in its volume and markup; a CASE sets Maryland's index to NULL |
| G10 | Region summary | `gold_region_summary`: `geo_level` (division / region / national), region, division, volume, payment, markup, `payment_index` | 13 to 17 | DQ-04, DQ-13 | One `GROUP BY ROLLUP` builds 9 division rows, 4 region rows and 1 national row; `GROUPING()` labels the grain. Conditional sums keep Maryland in volume and markup but out of both sides of the index |
| G11 | Hospital index (in progress) | base query: name, city, state, region, `urban_rural`, `n_drgs`, `is_low_drg_hospital`, discharges, payment, expected payment, `payment_index`, `n_outlier_cells`, `share_outlier_cells` | 18 to 20 | DQ-13, DQ-14, DQ-17 | Inner join to the benchmark (every non-Maryland row has one, cell 11, and an inner join keeps actual and expected on the same rows). The deviation table joins on both `ccn` and `drg_cd` because it has the same grain as the fact table; joining on `ccn` alone would fan out |

## 8. Week 4 validation results

| Table | Check | Expected | Result |
|---|---|---|---|
| `gold_dim_state` | Rows / distinct states | 51 / 51 | 51 / 51 |
| `gold_dim_state` | Hospitals with no matching state | 0 | 0 |
| `gold_dim_state` | Hospitals per region | sum 2,906 | Midwest 685, Northeast 437, South 1,203, West 581 = 2,906 |
| `gold_dim_state` | Joined hospital rows (catches duplicate states) | 2,906 | 2,906 |
| `gold_state_summary` | Rows | 51 | 51 |
| `gold_state_summary` | Markup NV / MA (Silver values) | 9.10 / 2.67 | 9.10 / 2.67 |
| `gold_state_summary` | Maryland payment index | NULL | NULL |
| `gold_state_summary` | Total payment (Silver total) | 90,927,479,550.00 | 90,927,479,550.00 |
| `gold_state_summary` | Non-Maryland fact rows with no benchmark | 0 | 0 |
| `gold_region_summary` | Rows per grain | 9 / 4 / 1 | 9 / 4 / 1 |
| `gold_region_summary` | National markup / payment per discharge / total payment | 5.03 / 18,359.99 / 90,927,479,550.00 | 5.03 / 18,359.99 / 90,927,479,550.00 |
| `gold_region_summary` | Region rows sum to national payment | 90,927,479,550.00 | 90,927,479,550.00 |
| hospital base (cell 20) | Rows / distinct CCNs | 2,862 (2,906 minus 44 Maryland) | 2,862 / 2,862 |
| hospital base (cell 20) | Σ payment / Σ expected across hospitals | national index 1.104 | 1.104 |
| hospital base (cell 20) | NULLs; share of outlier cells above 1 | 0; 0 | 0; 0 |
| hospital base (cell 20) | Low-DRG hospitals | 370 in Week 3, all hospitals | 369 (the 370th is a Maryland hospital) |
| hospital base (cell 20) | Week 3 outlier cells | 2,358 in Week 3, Maryland included | 1,922 (the other 436 flagged cells are Maryland rows) |

## 9. Week 4 findings so far

- **National payment index = 1.104**, above 1.00 because the benchmark is a plain median and payments are right-skewed. The median hospital index is 0.989: most hospitals are paid slightly below the median, while a minority of large academic and safety-net hospitals paid well above it lift the volume-weighted total. Charts should use 1.104 as the average line, or divide by it (decision pending, before Week 6).
- **States:** index ranges from 0.843 (AR) to 1.449 (NY), a 1.72x spread. Top: NY, AK, CA, HI, DC, CT. Bottom: AR, MS, LA, VT, KY, IA.
- **Case-mix adjustment matters:** DC has the highest raw payment per discharge ($32,967) but ranks 5th on the index (1.383).
- **Markup does not track payment:** NV has the highest markup (9.10) but an index of 1.10; MA has the lowest markup (2.67) but an index of 1.226; FL marks up 7.12 and is paid below median (0.957).
- **Maryland markup 1.11:** charges almost equal payments under all-payer rate setting, consistent with DQ-13.
- **Small states:** DC, DE, VT (6 hospitals each), ND (7), AK (8), WY and RI (9) have fewer than 10 hospitals; flagged `is_small_state`.
- **Regions:** West 1.271, Northeast 1.252, Midwest 1.026, South 0.986. **Divisions:** Pacific highest (1.373), East South Central lowest (0.915). New England has the lowest markup (2.98) but an index of 1.214; West South Central has the highest markup (6.17) but an index of 0.970.
- **Hospital tails:** index runs from 0.605 to 9.95. Low-DRG hospitals appear at both ends (4 of the top 10 and 4 of the bottom 10), supporting DQ-17. The bottom includes specialty surgical hospitals; the top includes academic and specialty centers.
- **Most Week 3 outlier cells:** academic medical centers (Stanford, UCSF, UCLA, UC San Diego, University Health San Antonio) and public safety-net or trauma hospitals (Grady, Zuckerberg SF General, LA General, Jacobi, Boston Medical Center). Safety-net hospitals have 80% to 85% of their DRG cells flagged, versus 34% at Stanford. These hospitals receive teaching (IME), disproportionate-share (DSH) and wage-index add-ons by design, so a high index reflects payment policy and patient severity, not necessarily inefficiency (DQ-23).

## 10. Week 4 still to do

- `gold_hospital_index`: thresholds CTE (Q1, Q3 across non-low-DRG hospitals) and `is_hospital_outlier`; checks
- `gold_ruca_summary`: four RUCA groups and binary `urban_rural`; checks against Silver (Metro markup 5.25, Micro 3.88)
- Sensitivity check W4-2 (non-thin benchmarks only)
- State-level payment variation above the DRG median (the dollar figure for the resume and Week 7)
- Export the notebook to `notebooks/04_gold_aggregates.ipynb` and the run to `docs/run_evidence/`
