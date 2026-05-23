"""
parser.py — Load a KiCad or generic BOM CSV into a normalised DataFrame.

Column aliases resolved:
  Reference / Ref / Designator       → reference
  Value / Val                         → value
  Footprint / Package / Pkg           → footprint
  Description / Desc / Comment        → description
  Quantity / Qty / Count              → qty
  MPN / Part Number / Manufacturer PN → mpn
"""

from __future__ import annotations

import re
import pandas as pd


_ALIASES: dict[str, list[str]] = {
    "reference":   ["reference", "ref", "references", "designator", "refdes"],
    "value":       ["value", "val", "component value"],
    "footprint":   ["footprint", "package", "pkg", "pcb footprint"],
    "description": ["description", "desc", "comment", "comments"],
    "qty":         ["quantity", "qty", "count", "amount"],
    "mpn":         ["mpn", "part number", "manufacturer part number",
                    "manufacturer pn", "mfr pn", "mfr. part no"],
}


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    mapping: dict[str, str] = {}
    for col in df.columns:
        clean = col.strip().lower().lstrip("\ufeff")
        for canonical, aliases in _ALIASES.items():
            if clean in aliases and canonical not in mapping.values():
                mapping[col] = canonical
                break
    df = df.rename(columns=mapping)
    df.columns = [c.strip().lower().lstrip("\ufeff") for c in df.columns]
    return df


def _ensure_qty(df: pd.DataFrame) -> pd.DataFrame:
    """
    If the BOM is grouped (References = "R1,R2,R5"), derive qty from the
    comma count when a qty column is absent.  Keeps one row per unique part.
    """
    if "reference" not in df.columns:
        return df

    if "qty" not in df.columns:
        def _count(refs: str) -> int:
            return len([r.strip() for r in str(refs).split(",") if r.strip()])
        df["qty"] = df["reference"].apply(_count)

    df["qty"] = pd.to_numeric(df["qty"], errors="coerce").fillna(1).astype(int)
    return df


def load_bom(path: str) -> pd.DataFrame:
    """Return a clean, normalised BOM DataFrame from a CSV file."""
    df = pd.read_csv(path, encoding="utf-8-sig", encoding_errors="replace")
    df = _normalise_columns(df)
    df = _ensure_qty(df)
    df = df.dropna(how="all").reset_index(drop=True)
    if "mpn" not in df.columns:
        df["mpn"] = ""
    return df