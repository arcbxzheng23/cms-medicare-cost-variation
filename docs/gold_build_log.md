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

# Part 2: Week 4 aggregates

**Deliverable:** Week 4 (LO1, LO4), state, region, hospital and rural/urban roll-ups on top of the Week 3 star schema
**Author:** Ben Cheng · **Built:** 2026-11-02 · **Notebook:** `notebooks/04_gold_aggregates.ipynb`
**Status:** All Week 4 tables built and reconciled in Databricks Free Edition (serverless). Every check below was run in the notebook; the HTML export with outputs is in `docs/run_evidence/`.

## 6. Week 4 design decisions (notebook cell 1)

| # | Decision | Reason |
|---|---|---|
| W4-1 | Headline measure = **payment index** = Σ actual total payment / Σ (discharges x DRG median payment) | Adjusts for case mix: 1.00 = paid the national DRG median for that exact mix of DRGs. Raw payment per discharge and weighted markup kept as descriptive columns |
| W4-2 | Expected payment uses all 539 DRG benchmarks; non-thin only (310) run as a sensitivity check | Dropping thin DRGs would measure some hospitals on part of their volume. Confirmed in cell 32: no state index moves by more than 0.006 |
| W4-3 | Hospital outlier = payment index above Q3 + 3 x IQR across hospitals with at least 5 DRGs; low-DRG hospitals never flagged | Same rule as DQ-14 and same exclusion as DQ-17. Upper fence only: the index has a floor near 0.6 but a long right tail (max 9.95) |
| W4-4 | RUCA: binary `urban_rural` is the headline; the five RUCA groups kept in the table; Unknown (99) its own group | Small town (196 hospitals) and Rural (38) are too thin for headline findings (DQ-12) |
| W4-5 | `gold_dim_state` carries Census region (4) and division (9); regions used for reporting | One extra column avoids a rebuild if Week 5 needs divisions |
| W4-6 | Maryland kept in state and region summaries for volume and markup; its payment index is NULL or excluded. Hospital index and RUCA summary exclude Maryland entirely | No IPPS benchmark (DQ-13) |

## 7. Week 4 build steps

| # | Step | Table and columns | Cells | DQ issue | Why |
|---|---|---|---|---|---|
| G8 | State dimension | `gold_dim_state`: `state_abbr`, `census_region`, `census_division` (inline `VALUES`, US Census Bureau regions; DC in South / South Atlantic) | 2 to 6 | DQ-21 | Lookup for regional roll-ups, keyed on the state abbreviation already in `gold_dim_hospital` |
| G9 | State summary | `gold_state_summary`: region, division, `is_small_state` (fewer than 10 hospitals), `n_hospitals`, discharges, payment, charges, `payment_per_discharge`, `markup_ratio`, `expected_payment`, `payment_index` | 7 to 12 | DQ-04, DQ-13, DQ-22 | Totals over totals. LEFT JOIN to the benchmark keeps Maryland's DRG 950 rows in its volume and markup; a CASE sets Maryland's index to NULL |
| G10 | Region summary | `gold_region_summary`: `geo_level` (division / region / national), region, division, volume, payment, markup, `payment_index` | 13 to 17 | DQ-04, DQ-13 | One `GROUP BY ROLLUP` builds 9 division rows, 4 region rows and 1 national row; `GROUPING()` labels the grain. Conditional sums keep Maryland in volume and markup but out of both sides of the index |
| G11 | Hospital index | `gold_hospital_index`: name, city, state, region, `urban_rural`, `n_drgs`, `is_low_drg_hospital`, discharges, payment, expected payment, `payment_index`, `n_outlier_cells`, `share_outlier_cells`, `q1`, `q3`, `is_hospital_outlier` | 18 to 26 | DQ-13, DQ-14, DQ-17, DQ-23 | `base` CTE (validated as a preview in cells 18 to 19) plus a one-row `thresholds` CTE cross-joined to every hospital. Inner join to the benchmark (every non-Maryland row has one, cell 11). The Week 3 deviation table joins on both `ccn` and `drg_cd` because it has the same grain as the fact table; joining on `ccn` alone would fan out |
| G12 | RUCA summary | `gold_ruca_summary`: `ruca_level` (ruca_group / urban_rural / national), `urban_rural`, `ruca_group`, volume, payment, markup, `expected_payment`, `payment_index` | 27 to 31 | DQ-04, DQ-12, DQ-13 | `fact_ruca` CTE derives `ruca_group` from `ruca_code` (cast to DOUBLE, floored, CASE; ELSE NULL so an unmapped code would surface). `ROLLUP(urban_rural, ruca_group)` gives 5 + 3 + 1 rows. Maryland excluded |
| G13 | Sensitivity check | query only | 32 | DQ-16, W4-2 | State index recomputed with non-thin DRGs only (thin rows dropped from both actual and expected) and compared with the main index |
| G14 | Payment variation | query only | 33 | DQ-03, DQ-23 | Dollars paid above the state median for each DRG: state x DRG payment per discharge, plain median across states per DRG, excess summed over above-median states |

## 8. Week 4 validation results

| Table | Check | Cell | Expected | Result |
|---|---|---|---|---|
| `gold_dim_state` | Rows / distinct states | 3 | 51 / 51 | 51 / 51 |
| `gold_dim_state` | Hospitals with no matching state | 4 | 0 | 0 |
| `gold_dim_state` | Hospitals per region | 5 | sum 2,906 | Midwest 685, Northeast 437, South 1,203, West 581 = 2,906 |
| `gold_dim_state` | Joined hospital rows (catches duplicate states) | 6 | 2,906 | 2,906 |
| `gold_state_summary` | Rows | 8 | 51 | 51 |
| `gold_state_summary` | Markup NV / MA (Silver values) | 9 | 9.10 / 2.67 | 9.10 / 2.67 |
| `gold_state_summary` | Maryland payment index | 9 | NULL | NULL |
| `gold_state_summary` | Total payment (Silver total) | 10 | 90,927,479,550.00 | 90,927,479,550.00 |
| `gold_state_summary` | Non-Maryland fact rows with no benchmark | 11 | 0 | 0 |
| `gold_region_summary` | Rows per grain | 14 | 9 / 4 / 1 | 9 / 4 / 1 |
| `gold_region_summary` | National markup / payment per discharge / total payment | 15 | 5.03 / 18,359.99 / 90,927,479,550.00 | 5.03 / 18,359.99 / 90,927,479,550.00 |
| `gold_region_summary` | Region rows sum to national payment | 16 | 90,927,479,550.00 | 90,927,479,550.00 |
| `gold_hospital_index` | Rows | 21 | 2,862 (2,906 minus 44 Maryland) | 2,862 |
| `gold_hospital_index` | Σ payment / Σ expected | 22 | national index 1.104 | 1.10419 |
| `gold_hospital_index` | Low-DRG hospitals flagged | 23 | 0 | 0 |
| `gold_hospital_index` | Q1 / Q3 / upper fence | 24 | 0.889 / 1.140 / 1.891 | 0.88941 / 1.13978 / 1.89087 |
| `gold_hospital_index` | Hospitals flagged | 25 | small share of 2,493 eligible | 51 (2.0%) |
| `gold_hospital_index` | Low-DRG hospitals / Week 3 outlier cells | 19 | 370 / 2,358 in Week 3 (Maryland included) | 369 / 1,922 (the 370th low-DRG hospital and the other 436 flagged cells are Maryland's) |
| `gold_ruca_summary` | Rows per grain (an unmapped code would add a sixth group) | 28 | 5 / 3 / 1 | 5 / 3 / 1 |
| `gold_ruca_summary` | Hospitals by group (Silver, Maryland excluded) | 29 | 2,101 / 515 / 196 / 38 / 12 | 2,101 / 515 / 196 / 38 / 12 |
| `gold_ruca_summary` | Markup by group | 29 | 5.25 / 3.88 / 3.32 / 4.08 / 5.59 | 5.25 / 3.88 / 3.32 / 4.08 / 5.59 |
| `gold_ruca_summary` | Payment per discharge by group | 29 | 18,651.20 / 13,221.78 / 13,222.17 / 12,685.63 / 16,119.50 | identical |
| `gold_ruca_summary` | National row: hospitals, discharges, payment per discharge, markup, index | 30 | 2,862 / 4,821,831 / 18,215.26 / 5.17 / 1.104 | 2,862 / 4,821,831 / 18,215.26 / 5.17 / 1.104 |
| Sensitivity (W4-2) | Largest change in state index, non-thin only | 32 | below 0.02 | 0.006 (DC); ranking unchanged |
| Payment variation | Total payment across state x DRG rows | 33 | 87,830,892,845 (non-Maryland) | 87,830,892,845.00 |

## 9. Week 4 findings

- **National payment index = 1.104**, above 1.00 because the benchmark is a plain median and payments are right-skewed. The median hospital index is 0.989: most hospitals are paid slightly below the median, while a minority of large academic and safety-net hospitals paid well above it lift the volume-weighted total. Charts should use 1.104 as the average line, or divide by it (decision before Week 6).
- **States:** index ranges from 0.843 (AR) to 1.449 (NY), a 1.72x spread. Top: NY, AK, CA, HI, DC, CT. Bottom: AR, MS, LA, VT, KY, IA.
- **Case-mix adjustment matters:** DC has the highest raw payment per discharge ($32,967) but ranks 5th on the index (1.383).
- **Markup does not track payment:** NV has the highest markup (9.10) but an index of 1.10; MA has the lowest markup (2.67) but an index of 1.226; FL marks up 7.12 and is paid below median (0.957).
- **Maryland markup 1.11:** charges almost equal payments under all-payer rate setting, consistent with DQ-13.
- **Small states:** DC, DE, VT (6 hospitals each), ND (7), AK (8), WY and RI (9); flagged `is_small_state`.
- **Regions:** West 1.271, Northeast 1.252, Midwest 1.026, South 0.986. **Divisions:** Pacific highest (1.373), East South Central lowest (0.915). New England has the lowest markup (2.98) but an index of 1.214; West South Central has the highest markup (6.17) but an index of 0.970.
- **Hospital tails:** index runs from 0.605 to 9.95. Low-DRG hospitals appear at both ends, supporting DQ-17. Specialty surgical hospitals sit at the bottom.
- **Hospital outliers (51 of 2,493 eligible):** almost entirely public, county-run safety-net systems: NYC Health + Hospitals (Kings County, Woodhull, Queens, Bellevue, Elmhurst, Lincoln, Harlem, Jacobi), LA County (LA General, Harbor-UCLA, Olive View-UCLA), Texas county systems (Harris Health, the top hospital at 9.95; Parkland; JPS), Cook County (Stroger), Zuckerberg SF General, Contra Costa Regional, SUNY Downstate and Truman (Kansas City). Many have only 9 to 44 DRGs despite their size, because most of their patients are on Medicaid or uninsured. Safety-net hospitals have 80% to 85% of their DRG cells flagged, versus 34% at Stanford. These hospitals receive disproportionate-share, uncompensated-care and wage-index add-ons by design (DQ-23).
- **Kaiser Foundation hospitals** (San Francisco, Santa Clara, South San Francisco, Los Angeles) are also flagged, with only 6 to 20 DRGs. Most Kaiser Medicare members are in Medicare Advantage, which is outside this data (DQ-21), so their few fee-for-service cases are likely unusual ones. A data-scope effect, not a pricing finding.
- **Rural vs urban:** urban hospitals are paid 41% more per discharge in raw dollars ($18,651 vs $13,199), but only 11% more after case-mix adjustment (index 1.111 vs 1.001). About three-quarters of the raw gap is case mix. Within rural: Small town 1.048, Micropolitan 0.996, Rural 0.987 (thin groups; a question for Week 5, not a finding). Markup is lower in rural hospitals (3.83 vs 5.25).
- **Thin DRGs do not drive the results:** using only the 310 non-thin benchmarks moves no state index by more than 0.006.
- **Payment variation:** $8.57B, 9.75% of non-Maryland payments ($87.8B), was paid above the state median for each DRG. Per DQ-23 this is payment variation, not savings: much of it reflects the wage index and teaching and safety-net add-ons.

## 10. Notes for Week 5

- Test how much of the state index spread the CMS wage index explains (DQ-23)
- Decide how charts show the 1.104 national average (reference line or rescaled index)
- Memorial Hospital Los Banos (rural CA, 8 DRGs, index 2.98) fits neither the safety-net nor the Kaiser pattern
- Small town vs Micropolitan difference: check special rural hospital statuses

Week 4 deliverable complete: state, region, hospital and rural/urban Gold tables built, validated against Silver to the cent, and documented.
