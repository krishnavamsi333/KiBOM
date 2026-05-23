"""
enricher.py — Fetch supplier data for every BOM row.

Uses the query_builder to form a search string, checks the local cache,
then routes to the provider cascade (provider_router).
"""

from __future__ import annotations

import logging

import pandas as pd

import cache
from services.query_builder   import build_query
from services.provider_router import lookup as provider_lookup

log = logging.getLogger(__name__)

_EMPTY: dict = {
    "mpn":                   "",
    "manufacturer":          "",
    "description_enriched":  "",
    "mouser_pn":             "",
    "digikey_pn":            "",
    "lcsc_pn":               "",
    "element14_pn":          "",
    "unit_price":            None,
    "stock":                 0,
    "lifecycle":             "",
    "suggested_replacement": "",
    "product_url":           "",
    "source":                "",
}


def _lookup_row(row: pd.Series) -> dict:
    """Look up one BOM row; returns enrichment dict (never None)."""
    query = build_query(row)

    if not query:
        return {**_EMPTY, "source": "skipped"}

    cached = cache.get(query)
    # Only serve cache hits that were real finds — never serve cached "not found"
    # so every run retries parts the API missed last time.
    if cached and cached.get("source") not in ("not found", "skipped", None):
        result = {**_EMPTY, **cached}
        result["source"] = f"{cached['source']} (cached)"
        return result

    result = provider_lookup(query)

    if result is None:
        result = {**_EMPTY, "source": "not found"}

    # Only persist real hits — caching "not found" would block future retries
    if result.get("source") not in ("not found", "skipped"):
        cache.put(query, result)

    return result


def enrich_bom(df: pd.DataFrame) -> pd.DataFrame:
    """Enrich an entire BOM DataFrame in place and return it."""
    enriched_cols = [k for k in _EMPTY if k != "source"]
    col_data: dict[str, list] = {c: [] for c in enriched_cols}
    sources: list[str] = []

    # Snapshot original BOM MPNs BEFORE the loop overwrites df["mpn"]
    bom_mpn_original = df["mpn"].tolist() if "mpn" in df.columns else [""] * len(df)

    total = len(df)
    for i, (_, row) in enumerate(df.iterrows(), 1):
        ref = str(row.get("reference", f"row {i}"))
        val = str(row.get("value",     ""))[:30]
        print(f"  [{i:>2}/{total}] {ref:<12} {val:<30}", end=" ", flush=True)

        data = _lookup_row(row)
        mpn_display = data.get("mpn") or "—"
        print(f"→ {mpn_display}  ({data.get('source', '?')})")

        for col in enriched_cols:
            col_data[col].append(data.get(col, _EMPTY[col]))
        sources.append(data["source"])

    for col, vals in col_data.items():
        df[col] = vals
    df["enrich_source"] = sources

    # Prefer original BOM MPN over the enriched one when it is a real value
    df["mpn"] = [
        orig if str(orig).strip() not in ("", "nan", "None")
        else enriched
        for orig, enriched in zip(bom_mpn_original, col_data["mpn"])
    ]

    return df