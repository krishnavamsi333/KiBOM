"""
services/query_builder.py — Build the best search query for a BOM row.
"""

from __future__ import annotations

import re

import pandas as pd


# ── Regexes ───────────────────────────────────────────────────────────────────

_KICAD_FP_NOISE = re.compile(
    r"(_Pad\w+|_HandSolder|_Dual|_SMD|_THT|_\d+\.\d+mm.*|_P\d+\.\d+mm|_\d+Metric)",
    re.IGNORECASE,
)

_KICAD_VALUE_SUFFIX = re.compile(
    r'[_\-](SO\d*|DIP\d*|SOIC\d*|TSSOP\d*|QFN\d*|LQFP\d*|SSOP\d*|'
    r'SOP\d*|SMD|SMT|THT|[A-Z]\d*W?|[A-Z]{1,3})$',
    re.IGNORECASE,
)

_MPN_RE = re.compile(
    r'^[A-Z]{1,6}\d[\w\-\.]{2,}$',
    re.IGNORECASE,
)

_PASSIVE_VAL_RE = re.compile(
    r'^[\d\.]+\s*[kKmMuUnNpP]?\s*[ΩFHzVAW%Ω]',
    re.IGNORECASE,
)

_RES_SHORT_RE = re.compile(
    r'^[\d\.]+\s*[kKmMrR]$',
    re.IGNORECASE,
)

_SKIP_PREFIXES = (
    "tp_",
    "testpoint",
    "pwr_",
    "pwr$",
    "gnd",
    "vcc",
    "vdd",
    "flag",
    "net",
    "earth",
    "conn_",
    "logo",
    "fiducial",
    "mountinghole",
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean_kicad_value(value: str) -> str:
    """
    Strip KiCad package suffixes from the value field.
    """

    cleaned = _KICAD_VALUE_SUFFIX.sub("", value).strip()

    return cleaned if len(cleaned) >= 3 else value


def looks_like_mpn(s: str) -> bool:
    """
    Return True if the string resembles a manufacturer part number.
    """

    s = s.strip()

    if len(s) < 4:
        return False

    if _PASSIVE_VAL_RE.match(s):
        return False

    if _RES_SHORT_RE.match(s):
        return False

    return bool(_MPN_RE.match(s))


def _clean_pkg(fp: str) -> str:
    """
    Extract useful package names from KiCad footprints.

    Examples:
        Resistor_SMD:R_0603_1608Metric
            → 0603

        Capacitor_SMD:C_0805_2012Metric
            → 0805

        Package_SO:SOIC-8_3.9x4.9mm_P1.27mm
            → SOIC-8

        LED_SMD:LED_0603_1608Metric
            → 0603

        Diode_SMD:D_SMA
            → SMA
    """

    if not fp or ":" not in fp:
        return ""

    pkg = fp.split(":")[-1]

    # ── Passive sizes ─────────────────────────────────────

    m = re.search(r'_(\d{4})_(\d+Metric)', pkg, re.I)
    if m:
        return m.group(1)

    m = re.search(r'LED_(\d{4})', pkg, re.I)
    if m:
        return m.group(1)

    # ── IC / diode packages ───────────────────────────────

    m = re.search(
        r'(SOT-\d+|SOIC-\d+|TSSOP-\d+|QFN-\d+|'
        r'VSSOP-\d+|HTSSOP-\d+|SSOP-\d+|DIP-\d+|'
        r'TO-\d+|SMA|SMB|SMC)',
        pkg,
        re.I,
    )

    if m:
        return m.group(1).upper()

    return ""


def _normalise_ohm(value: str) -> str:
    """
    Replace unicode Ω with 'Ohm'
    """

    return value.replace("Ω", " Ohm").strip()


# ── Main API ──────────────────────────────────────────────────────────────────

def build_query(row: pd.Series) -> str:
    """
    Return the best search query string for one BOM row.
    """

    # ── 1. Existing MPN wins ──────────────────────────────

    mpn = str(row.get("mpn", "") or "").strip()

    if mpn and mpn.lower() not in ("nan", "none"):
        return mpn

    value = str(row.get("value", "") or "").strip()
    desc = str(row.get("description", "") or "").strip()
    fp = str(row.get("footprint", "") or "").strip()

    v_low = value.lower()

    # ── Skip junk rows ────────────────────────────────────

    if any(v_low.startswith(p) for p in _SKIP_PREFIXES):
        return ""

    pkg = _clean_pkg(fp)

    # ── 2. Value looks like MPN ───────────────────────────

    cleaned_value = _clean_kicad_value(value)

    if looks_like_mpn(cleaned_value):
        return f"{cleaned_value} {pkg}".strip()

    # ── 3. MPN token inside description ──────────────────

    if desc and desc.lower() not in ("nan", "none"):

        for token in desc.split():

            token = token.strip(",;()[]{}")

            if looks_like_mpn(token):
                return f"{token} {pkg}".strip()

        # ── 4. Description fallback ───────────────────────

        return f"{desc} {pkg}".strip() if pkg else desc

    # ── 5. Passive fallback ───────────────────────────────

    if value and value.lower() not in ("nan", "none"):

        value_norm = _normalise_ohm(value)

        fp_low = fp.lower()

        if "resistor" in fp_low:
            return f"{value_norm} resistor {pkg}".strip()

        if "capacitor" in fp_low:
            return f"{value_norm} capacitor {pkg}".strip()

        if "led" in fp_low:
            return f"{value_norm} LED {pkg}".strip()

        if "fuse" in fp_low:
            return f"{value_norm} fuse {pkg}".strip()

        if "diode" in fp_low:
            return f"{value_norm} diode {pkg}".strip()

        return f"{value_norm} {pkg}".strip()

    # ── 6. Skip unusable rows ─────────────────────────────

    return ""