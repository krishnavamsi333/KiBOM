"""
checker.py — QA analysis over the enriched BOM DataFrame.

Detects component type from reference prefix + value + description,
then checks required fields defined in rules.py.
"""

from __future__ import annotations

import re

from rules import RULES


# ── Component type detection ───────────────────────────────────────────────────

_RES_UNIT_RE   = re.compile(r'^[\d\.]+\s*[kKmMrR]?\s*([ΩΩ]|[Oo]hm|[Rr]$)', re.IGNORECASE)
_RES_SHORT_RE  = re.compile(r'^[\d\.]+\s*[kKmM]$', re.IGNORECASE)
_CAP_RE        = re.compile(r'\d+\s*(uf|nf|pf)', re.IGNORECASE)
_IND_RE        = re.compile(r'\d+\s*(uh|mh|nh|henry)', re.IGNORECASE)
_FUSE_RE       = re.compile(r'\d+(\.\d+)?\s*A\b', re.IGNORECASE)
_CONN_RE       = re.compile(r'conn|connector|header|socket|plug', re.IGNORECASE)
_DIODE_MPN_RE  = re.compile(r'^(SMBJ|SMDJ|SS\d|1N\d|BAT|BAS|GS)', re.IGNORECASE)


def detect_type(value: str, desc: str = "", ref: str = "") -> str:
    """Return a component type string for a single BOM row."""
    v = (value or "").strip()
    d = (desc  or "").strip().lower()
    # Use only the first reference designator for prefix detection
    r = (ref   or "").strip().split(",")[0].strip().upper()

    # Reference prefix is the most reliable signal
    if r.startswith("C"):                           return "capacitor"
    if r.startswith("R") and not r.startswith("RE"): return "resistor"
    if r.startswith("L") and not r.startswith("LE"): return "inductor"
    if r.startswith("F"):                           return "fuse"
    if r.startswith("J"):                           return "connector"
    if r.startswith("Q"):                           return "transistor"
    if r.startswith("D"):
        return "led" if ("led" in d or "led" in v.lower()) else "diode"
    if r.startswith(("U", "IC")):                  return "ic"

    # Value-based fallback
    if _RES_UNIT_RE.match(v) or _RES_SHORT_RE.match(v): return "resistor"
    if _CAP_RE.search(v):                               return "capacitor"
    if _IND_RE.search(v):                               return "inductor"
    if _FUSE_RE.fullmatch(v) or "fuse" in d:            return "fuse"
    if _CONN_RE.search(v) or _CONN_RE.search(d):        return "connector"
    if "led" in v.lower() or "led" in d:               return "led"
    if _DIODE_MPN_RE.match(v):                          return "diode"
    return "ic"


# ── Value extractors ──────────────────────────────────────────────────────────

def _find(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1) if m else None

def extract_voltage(v: str)   -> str | None: return _find(r'(\d+(?:\.\d+)?V)',  v)
def extract_tolerance(v: str) -> str | None: return _find(r'(\d+(?:\.\d+)?%)',  v)
def extract_power(v: str)     -> str | None: return _find(r'(\d+(?:\.\d+)?W)',  v)


# ── Main analysis ─────────────────────────────────────────────────────────────

def analyze_bom(df) -> object:
    types: list[str]  = []
    issues: list[str] = []

    for _, row in df.iterrows():
        value = str(row.get("value",       "") or "")
        desc  = str(row.get("description", "") or "")
        ref   = str(row.get("reference",   "") or "")

        ctype = detect_type(value, desc, ref)
        types.append(ctype)

        required = RULES.get(ctype, [])
        source   = str(row.get("enrich_source", "")).lower()
        skipped  = source == "skipped"

        if skipped:
            issues.append("")
            continue

        mpn_val = str(row.get("mpn", "")).strip()
        has_mpn = mpn_val not in ("", "nan", "None")
        row_issues: list[str] = []

        if "mpn"       in required and not has_mpn:                   row_issues.append("Missing MPN")
        if "voltage"   in required and not extract_voltage(value):    row_issues.append("Missing voltage rating")
        if "tolerance" in required and not extract_tolerance(value):  row_issues.append("Missing tolerance")
        if "power"     in required and not extract_power(value):      row_issues.append("Missing power rating")
        if "color"     in required:
            colors = ("red","green","blue","yellow","white","amber","orange")
            if not any(c in value.lower() or c in desc.lower() for c in colors):
                row_issues.append("Missing LED color")

        # Flag "not found in any supplier" only when we also have no BOM MPN
        if source == "not found" and not has_mpn:
            row_issues.append("Not found in any supplier")

        issues.append(", ".join(row_issues))

    df["component_type"] = types
    df["issues"]         = issues
    return df