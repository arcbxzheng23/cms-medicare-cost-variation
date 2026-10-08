# Data Profiling Notes: Bronze Source File

**Deliverable:** Week 1 (LO1), data-profiling notes
**Author:** Ben Cheng · **Profiled:** 2026-10-05
**File:** `MUP_INP_RY26_P03_V10_DY24_PrvSvc.CSV` (CMS Medicare Inpatient Hospitals, by Provider and Service, data year 2024)
**Method:** `scripts/profile_raw_csv.py` (pandas, every column read as text with no missing-value conversion, so this describes the file exactly as Bronze stores it). Full machine-readable output: `docs/profile_output.json`. The same checks are repeated in Spark in `notebooks/01_bronze_ingest.py` (the validation section).

---

## 1. File-level facts

| Property | Value |
|---|---|
| Size | 37,976,130 bytes (36.2 MB) |
| SHA-256 | `2ab6da15be4cd47c4ecc05e0f54545e4493ee4eea58df626d1aa2e6b19b65e0d` |
| Encoding | UTF-8, no byte-order mark |
| Line endings | LF; 145,880 lines = 1 header + 145,879 data rows (no multi-line fields) |
| Delimiter / quoting | Comma; fields containing commas are wrapped in double quotes (e.g. RUCA and DRG descriptions) |
| Rows x columns | **145,879 x 15** |
| Grain | One row = one hospital (CCN) x one MS-DRG. Verified unique: 0 duplicate (CCN, DRG) pairs, 0 fully duplicate rows |
| Nulls / blanks | **0 in every column** |
| Leading/trailing whitespace | 0 in every column |

Takeaway: the file is structurally clean. Every issue below is about meaning and consistency, not parsing.

## 2. Column-by-column profile

All 15 columns have 145,879 non-empty values and 0 nulls, so those columns are omitted from the table.

| # | Column | Distinct | Length (min to max) | Pattern / content | Notes |
|---|---|---|---|---|---|
| 1 | `Rndrng_Prvdr_CCN` | 2,906 | 6 to 6 | All 6-digit numeric strings | 24,798 rows start with `0`. Must stay a string. |
| 2 | `Rndrng_Prvdr_Org_Name` | 2,845 | 3 to 50 | Title case, CMS-abbreviated ("Hlth", "Ctr") | Fewer names than CCNs: 40 names belong to 2+ hospitals. 1 name contains a control character (see DQ-08). |
| 3 | `Rndrng_Prvdr_City` | 1,762 | 3 to 20 | Title case | Top: New York (1,397 rows), Baltimore, Boston, Chicago, Houston |
| 4 | `Rndrng_Prvdr_St` | 2,897 | 9 to 43 | **Street address**, not state | 97.2% start with a digit; the rest are "One Hoag Drive", "Po Box 287", etc. |
| 5 | `Rndrng_Prvdr_State_FIPS` | 51 | 2 to 2 | 2-digit code | 23,683 rows start with `0`. Exactly 1:1 with state abbreviation. |
| 6 | `Rndrng_Prvdr_Zip5` | 2,687 | 5 to 5 | 5-digit code | 12,973 rows start with `0` |
| 7 | `Rndrng_Prvdr_State_Abrvtn` | 51 | 2 to 2 | USPS code | 50 states + DC; no territories (no PR, GU, VI) |
| 8 | `Rndrng_Prvdr_RUCA` | 19 | 1 to 4 | Codes `1` to `10.3`, plus `99` | Mixed integer and decimal codes (`1`, `1.1`, `10.3`). See section 4. |
| 9 | `Rndrng_Prvdr_RUCA_Desc` | 15 | 7 to 100 | USDA ERS text | 15 descriptions for 19 codes, because secondary-flow codes reuse text |
| 10 | `DRG_Cd` | 540 | 3 to 3 | 3-digit MS-DRG code | 14,415 rows start with `0` (e.g. `003`) |
| 11 | `DRG_Desc` | 528 | 9 to 88 | ALL CAPS | **Truncated at 88 characters**, so 20 codes share 8 descriptions |
| 12 | `Tot_Dschrgs` | 668 | 2 to 4 | Integer text | No decimals, no commas |
| 13 | `Avg_Submtd_Cvrd_Chrg` | 145,354 | 4 to 12 | Decimal text | Up to 7 decimal places (unrounded averages); no `$` or `,` |
| 14 | `Avg_Tot_Pymt_Amt` | 142,991 | 4 to 12 | Decimal text | Same format as above |
| 15 | `Avg_Mdcr_Pymt_Amt` | 142,662 | 4 to 12 | Decimal text | Same format as above |

**Most frequent values (context):**
- Hospitals with the most DRG rows: CCN `100007` Adventhealth Orlando (387), `330101` New York-Presbyterian Hospital (373), `330214` Nyu Langone Hospitals (356); names as spelled in the file.
- States by rows: CA 13,302 · FL 12,045 · TX 9,955 · NY 8,310 · PA 6,904.
- DRGs by hospital count: 871 Septicemia w/o MV >96 hrs with MCC (2,661 hospitals) · 291 Heart failure and shock with MCC (2,587) · 193 Simple pneumonia with MCC (2,442).

## 3. Numeric columns (stored as text; converted here only to profile)

Conversion: every value converted to a number. **0 conversion failures, 0 zeros, 0 negatives** in all four columns.

| Statistic | `Tot_Dschrgs` | `Avg_Submtd_Cvrd_Chrg` | `Avg_Tot_Pymt_Amt` | `Avg_Mdcr_Pymt_Amt` |
|---|---:|---:|---:|---:|
| Min | 11 | $2,058.38 | $1,849.08 | $386.80 |
| 25th pct | 14 | $36,845.23 | $9,057.23 | $7,078.13 |
| **Median** | **20** | **$61,619.59** | **$13,217.42** | **$10,850.70** |
| Mean | 33.95 | $96,366.09 | $19,151.32 | $15,782.65 |
| 75th pct | 35 | $110,042.34 | $20,959.95 | $17,252.63 |
| 99th pct | 235 | $561,050.40 | $91,384.50 | $76,379.44 |
| Max | 3,400 | $7,196,636.94 | $1,443,309.67 | $1,436,667.83 |
| Std dev | 50.57 | $129,334.70 | $22,673.39 | $19,662.87 |
| Sum | 4,952,481 discharges | n/a (averages; see DQ-04) | n/a | n/a |

Observations:
- **All four are heavily right-skewed** (mean well above median, 99th pct to max jumps by 10x or more). Medians and per-DRG normalization will be more reliable than means.
- **`Tot_Dschrgs` minimum is exactly 11**, confirming the CMS rule that cells with 10 or fewer discharges are excluded.
- Extremes: max charge is Temple University Hospital (PA), DRG 018, 16 discharges. Max total payment is Ascension St Vincent Hospital (IN), DRG 466 (hip/knee revision with MCC), 18 discharges. Both are low-volume cells, which is typical of extreme averages.
- Logical checks: Medicare payment is never greater than total payment (0 rows). Submitted charge is below total payment in **223 rows** (see DQ-13).

## 4. Code ranges

**States.** 51 values (50 states + DC), each with exactly one FIPS code.

**Hospitals and DRGs.**

| Measure | Value |
|---|---|
| Hospitals (CCN) | 2,906 |
| MS-DRG codes | 540 |
| Hospital x DRG pairs | 145,879 (= rows) |
| Hospitals per DRG | min 1 · median 53 · mean 270 · max 2,661 |
| DRGs with fewer than 5 hospitals | 100 |
| DRGs with fewer than 30 hospitals | 225 |
| DRGs per hospital | min 1 · median 32 · mean 50 · max 387 |
| Hospitals with only 1 DRG row | 93 (370 have fewer than 5) |

**CCN facility type.** The last four digits of a CCN show the facility type. 2,899 hospitals (145,758 rows) are in the short-term acute range `0001` to `0879`. 7 hospitals (121 rows) fall in `0880` to `0899`. There are no critical-access, rehab, psych, or children's ranges, which matches the methodology's "IPPS short-term only" scope.

**RUCA codes** (USDA rural-urban commuting areas; decimal codes are secondary-flow subcategories):

| Code | Description (abridged) | Rows | Hospitals |
|---|---|---:|---:|
| 1 | Metropolitan core | 127,031 | 1,992 |
| 1.1 | Metro, secondary flow 30% to <50% to larger urbanized area | 2,407 | 48 |
| 2 | Metropolitan high commuting | 2,243 | 91 |
| 2.1 | Metro high commuting, secondary flow | 36 | 2 |
| 3 | Metropolitan low commuting | 27 | 8 |
| 4 | Micropolitan core | 10,265 | 467 |
| 4.1 | Micropolitan, secondary flow | 504 | 25 |
| 5 | Micropolitan high commuting | 647 | 23 |
| 6 | Micropolitan low commuting | 10 | 2 |
| 7 | Small town core | 1,335 | 168 |
| 7.1 / 7.2 | Small town, secondary flow | 60 / 78 | 11 / 5 |
| 8 / 8.2 | Small town high commuting | 75 / 3 | 11 / 1 |
| 9 | Small town low commuting | 10 | 2 |
| 10 | Rural | 482 | 36 |
| 10.1 / 10.3 | Rural, secondary flow | 87 / 1 | 1 / 1 |
| **99** | **Unknown** | **578** | **12** |

The data is overwhelmingly metropolitan: code 1 alone is 87% of rows and 69% of hospitals. Rural/urban comparisons in Week 4 will rest on small groups. RUCA 99 (Unknown) is concentrated in SD (316 rows) and CA (130).

## 5. Relationships and key checks

| Check | Result | Meaning |
|---|---|---|
| (CCN, DRG_Cd) unique | Pass (0 duplicates) | Confirms the grain; this is the natural primary key |
| CCN to name / city / street / ZIP / state / RUCA | Pass (each CCN has exactly 1 value of each) | Hospital attributes can move cleanly into a `dim_hospital` in Gold |
| Name to CCN | **Not unique**: 40 names map to 2+ CCNs (e.g. "Good Samaritan Hospital", "Mercy Medical Center" x4 each) | Always join and group on CCN, never on name |
| DRG_Cd to DRG_Desc | Pass (each code has 1 description) | |
| DRG_Desc to DRG_Cd | **Not unique**: 8 descriptions map to 20 codes, due to truncation at 88 characters (e.g. DRGs 456/457/458 all read "SPINAL FUSION EXCEPT CERVICAL WITH SPINAL CURVATURE, MALIGNANCY, INFECTION OR EXTENSIVE") | Always key on DRG_Cd |
| State abbreviation to FIPS | Pass (1:1, 51 pairs) | |
| Medicare payment ≤ total payment | Pass (0 violations) | Consistent with the data dictionary definitions |
| Charge ≥ total payment | 223 exceptions | See DQ-13 |

## 6. Preview of Week 2 derived measures

Not built in Bronze; computed here only to anticipate issues.

| Measure | Min | 1st pct | Median | Mean | 99th pct | Max |
|---|---:|---:|---:|---:|---:|---:|
| Markup ratio = charge / total payment | 0.15 | 1.10 | 4.48 | 5.17 | 15.60 | 34.82 |
| Medicare share = Medicare pmt / total pmt | 0.045 | | 0.829 | 0.811 | | 1.000 |

Maryland's median markup is **1.12**, compared with 2.2 to 3.0 for the next-lowest states and about 4.5 nationally. This matches the CMS methodology note that Maryland is exempt from IPPS and uses all-payer rate setting. Maryland needs separate treatment in any markup analysis.

## 7. Source documentation reviewed

- *Medicare FFS Provider Utilization & Payment Data, Inpatient PUF: A Methodological Overview* (CMS, May 2024). Confirms: MEDPAR source on a **calendar-year** basis; IPPS short-term hospitals only; FFS only (no Medicare Advantage); records from 10 or fewer discharges excluded; Maryland waiver.
- *Data Dictionary, Medicare Inpatient Hospitals by Provider and Service* (CMS, May 2023). Definitions used above: total payment includes the DRG amount, teaching, DSH, capital, and outlier payments plus beneficiary co-pay/deductible and third-party payments; Medicare payment excludes the beneficiary and third-party parts. Note: this dictionary is the 2023 version and calls the ID column `Rndrng_CCN` (the file uses `Rndrng_Prvdr_CCN`), see DQ-20.

## 8. Data-quality flags carried to Silver

The full list, with evidence and planned handling, is in [`data_quality_log.md`](data_quality_log.md). In short:

1. Cast numerics in Silver; never cast code columns (leading zeros). (DQ-01, DQ-02)
2. Suppression floor of 11 and averages-not-totals: weight by `Tot_Dschrgs`. (DQ-03, DQ-04)
3. Key on `DRG_Cd` and CCN, never on descriptions or names. (DQ-06, DQ-07)
4. Text clean-up: control character, double spaces, rename the misleading `Rndrng_Prvdr_St`. (DQ-08 to DQ-11)
5. RUCA rural/urban mapping including an Unknown bucket. (DQ-12)
6. Maryland and markup < 1. (DQ-13)
7. Outliers and thin groups: low-volume cells, DRGs with few hospitals, hospitals with few DRGs. (DQ-14 to DQ-17)

## 9. Reproduce

```bash
# from the repo root, with the CSV in data/raw/
python3 scripts/profile_raw_csv.py data/raw/MUP_INP_RY26_P03_V10_DY24_PrvSvc.CSV
shasum -a 256 data/raw/MUP_INP_RY26_P03_V10_DY24_PrvSvc.CSV
```
The relationship checks in section 5 and the RUCA and markup breakdowns are also run in Spark SQL by the Bronze notebook, so the two profiles can be compared directly. A local Apache Spark 4.0.1 dry run (2026-10-08) reproduced every count in this document exactly. One expected difference: Spark's `percentile_approx` gives approximate medians (e.g. charge median $61,615.50 vs exact $61,619.59), so medians may differ slightly while all counts, minimums, maximums and means match.
