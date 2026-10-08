"""Profile the raw CMS Medicare inpatient CSV exactly as it will land in Bronze.

Usage (from the repo root):
    python scripts/profile_raw_csv.py data/raw/MUP_INP_RY26_P03_V10_DY24_PrvSvc.CSV

Everything is read as a string with no NA conversion, so the profile describes the raw file,
not a cleaned version of it. Numeric stats come from a separate, explicit conversion step that
also counts values that fail to convert. Output: a printed report plus docs/profile_output.json.
"""
import json
import sys
from pathlib import Path

import pandas as pd

DOLLAR_COLS = ["Avg_Submtd_Cvrd_Chrg", "Avg_Tot_Pymt_Amt", "Avg_Mdcr_Pymt_Amt"]
COUNT_COLS = ["Tot_Dschrgs"]


def detect_encoding(path: Path) -> str:
    raw = path.read_bytes()
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"


def main(csv_path: str) -> None:
    path = Path(csv_path)
    raw_bytes = path.read_bytes()
    encoding = detect_encoding(path)
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False, encoding=encoding)

    out = {
        "file": path.name,
        "bytes": len(raw_bytes),
        "encoding": encoding,
        "has_bom": raw_bytes.startswith(b"\xef\xbb\xbf"),
        "line_endings": "CRLF" if b"\r\n" in raw_bytes[:100000] else "LF",
        "rows": len(df),
        "columns": list(df.columns),
        "per_column": {},
    }

    for c in df.columns:
        s = df[c]
        stripped = s.str.strip()
        lens = s.str.len()
        col = {
            "non_empty": int((stripped != "").sum()),
            "blank_or_empty": int((stripped == "").sum()),
            "leading_trailing_ws": int((stripped != s).sum()),
            "distinct": int(s.nunique()),
            "min_len": int(lens.min()),
            "max_len": int(lens.max()),
            "non_ascii": int(s.map(lambda v: not v.isascii()).sum()),
            "top5": s.value_counts().head(5).to_dict(),
        }
        if c in DOLLAR_COLS + COUNT_COLS:
            num = pd.to_numeric(s.str.replace(r"[$,]", "", regex=True), errors="coerce")
            col.update({
                "convert_failures": int(num.isna().sum()),
                "has_dollar_or_comma": int(s.str.contains(r"[$,]", regex=True).sum()),
                "decimals_max": int(s.str.extract(r"\.(\d+)$")[0].str.len().astype(float).fillna(0).max()),
                "min": float(num.min()), "p25": float(num.quantile(.25)), "median": float(num.median()),
                "mean": float(num.mean()), "p75": float(num.quantile(.75)), "p99": float(num.quantile(.99)),
                "max": float(num.max()), "std": float(num.std()),
                "zeros": int((num == 0).sum()), "negatives": int((num < 0).sum()),
            })
        out["per_column"][c] = col

    dest = Path(__file__).resolve().parents[1] / "docs" / "profile_output.json"
    dest.write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps({k: v for k, v in out.items() if k != "per_column"}, indent=2))
    for c, v in out["per_column"].items():
        print(f"\n== {c}")
        for k, val in v.items():
            print(f"  {k}: {val}")
    print(f"\nWrote {dest}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/raw/MUP_INP_RY26_P03_V10_DY24_PrvSvc.CSV")
