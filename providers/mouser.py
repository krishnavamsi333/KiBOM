"""
providers/mouser.py — Mouser Search API lookup.

Strategy for MPN queries:
  1. /search/partnumber  Exact  — fastest, works when full MPN is known
  2. /search/keyword     fetching MAX_RESULTS, then scoring results to pick
     the best IC match and skip eval kits / dev boards / accessories

Result scoring skips parts whose description or MPN contains kit/module/board
keywords, and prefers results whose MPN starts with the same prefix as the query.
"""

from __future__ import annotations

import re
import logging

import requests

from config import MOUSER_API_KEY, MOUSER_BASE_URL, MAX_RESULTS_PER_QUERY, REQUEST_TIMEOUT

log = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
})

# ── Regexes ───────────────────────────────────────────────────────────────────

_MPN_RE         = re.compile(r'^[A-Z]{1,6}\d[\w\-\.]{2,}$', re.IGNORECASE)
_PASSIVE_VAL_RE = re.compile(r'^[\d\.]+\s*[kKmMuUnNpP]?\s*[ΩFHzVAW%]', re.IGNORECASE)
_RES_SHORT_RE   = re.compile(r'^[\d\.]+\s*[kKmMrR]$', re.IGNORECASE)

# Words that indicate a result is NOT the bare IC we want
_KIT_RE = re.compile(
    r'\b(EVM|EVK|EVM-PDK|PDK|eval|evaluation|kit|board|module|shield|'
    r'breakout|demo|devkit|starter|launchpad|nucleo|discovery|arduino)\b',
    re.IGNORECASE,
)


def _looks_like_mpn(s: str) -> bool:
    s = s.strip()
    if len(s) < 4:
        return False
    if _PASSIVE_VAL_RE.match(s) or _RES_SHORT_RE.match(s):
        return False
    return bool(_MPN_RE.match(s))


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        cleaned = re.sub(r"[^\d.\-]", "", str(val).replace(",", "").strip())
        return float(cleaned) if cleaned else None
    except Exception:
        return None


def _parse_stock(p: dict) -> int:
    s = str(p.get("Availability", "0")).replace(",", "").split()[0]
    try:
        return int(s)
    except ValueError:
        return 0


def _normalise(p: dict) -> dict:
    pb    = p.get("PriceBreaks") or []
    price = _safe_float(pb[0].get("Price")) if pb else None

    url = p.get("ProductDetailUrl", "")
    if url and url.startswith("/"):
        url = f"https://www.mouser.in{url}"

    return {
        "mpn":                   p.get("ManufacturerPartNumber", ""),
        "manufacturer":          p.get("Manufacturer", ""),
        "description_enriched":  p.get("Description", ""),
        "mouser_pn":             p.get("MouserPartNumber", ""),
        "digikey_pn":            "",
        "lcsc_pn":               "",
        "element14_pn":          "",
        "unit_price":            price,
        "stock":                 _parse_stock(p),
        "lifecycle":             p.get("LifecycleStatus"),
        "suggested_replacement": p.get("SuggestedReplacement", ""),
        "product_url":           url,
        "source":                "Mouser",
    }


def _is_kit(p: dict) -> bool:
    """Return True if this result looks like an eval kit / dev board, not a bare IC."""
    mpn  = p.get("ManufacturerPartNumber", "")
    desc = p.get("Description", "")
    return bool(_KIT_RE.search(mpn) or _KIT_RE.search(desc))


def _score(p: dict, query_prefix: str) -> int:
    """
    Score a Mouser result. Higher = better match.
      +10  MPN starts with the query prefix (e.g. ADS1115 → ADS1115IDGSR)
      +5   MPN equals query exactly
      -100 Result looks like a kit / eval board
    """
    mpn = p.get("ManufacturerPartNumber", "")
    score = 0
    if mpn.upper().startswith(query_prefix.upper()):
        score += 10
    if mpn.upper() == query_prefix.upper():
        score += 5
    if _is_kit(p):
        score -= 100
    return score


def _best_result(parts: list[dict], query: str) -> dict | None:
    """Pick the best part from a list, filtering out kits."""
    if not parts:
        return None

    prefix = query.split()[0]  # e.g. "ADS1115" from "ADS1115 TSSOP-10"

    # Sort by score descending
    ranked = sorted(parts, key=lambda p: _score(p, prefix), reverse=True)

    log.debug("Mouser ranked results for '%s':", query)
    for p in ranked:
        log.debug("  score=%-4d  kit=%-5s  mpn=%s",
                  _score(p, prefix), _is_kit(p), p.get("ManufacturerPartNumber"))

    best = ranked[0]
    if _is_kit(best):
        log.debug("Mouser: all results appear to be kits for query '%s'", query)
        return None

    return _normalise(best)


# ── API calls ─────────────────────────────────────────────────────────────────

def _exact_search(mpn: str) -> list[dict]:
    """Mouser /search/partnumber with Exact matching — best for full MPNs."""
    try:
        r = _SESSION.post(
            f"{MOUSER_BASE_URL}/search/partnumber?apiKey={MOUSER_API_KEY}",
            json={"SearchByPartRequest": {
                "mouserPartNumber": mpn,
                "partSearchOptions": "Exact",
            }},
            timeout=REQUEST_TIMEOUT,
        )
        if not r.ok:
            log.debug("Mouser exact %s → %s", mpn, r.status_code)
            return []
        body = r.json() or {}
        if body.get("Errors"):
            return []
        return body.get("SearchResults", {}).get("Parts") or []
    except Exception as e:
        log.debug("Mouser exact exception: %s", e)
        return []


def _keyword_search(query: str, records: int = 10) -> list[dict]:
    """Mouser /search/keyword — fetch several results so we can pick the best."""
    try:
        r = _SESSION.post(
            f"{MOUSER_BASE_URL}/search/keyword?apiKey={MOUSER_API_KEY}",
            json={"SearchByKeywordRequest": {
                "keyword":        query,
                "records":        records,
                "startingRecord": 0,
                "searchOptions":  "None",
            }},
            timeout=REQUEST_TIMEOUT,
        )
        if not r.ok:
            log.debug("Mouser keyword %s → %s", query, r.status_code)
            return []
        body = r.json() or {}
        if body.get("Errors"):
            return []
        return body.get("SearchResults", {}).get("Parts") or []
    except Exception as e:
        log.debug("Mouser keyword exception: %s", e)
        return []


# ── Public entry point ────────────────────────────────────────────────────────

def lookup(query: str) -> dict | None:
    """
    Look up a part on Mouser. Returns normalised dict or None.

    For MPN-like queries (e.g. "ADS1115", "TPS4H160BQPWPRQ1"):
      - Try exact search first (catches full MPNs immediately)
      - Then keyword search fetching 10 results, scored to skip eval kits

    For descriptive queries (passive values, descriptions):
      - Keyword only, scored the same way
    """
    if not MOUSER_API_KEY:
        return None

    mpn_token = query.split()[0]

    if _looks_like_mpn(mpn_token):
        # Step 1: exact match (works when full MPN is in the BOM)
        parts = _exact_search(mpn_token)
        if parts:
            result = _best_result(parts, mpn_token)
            if result:
                log.debug("Mouser exact hit: %s", result["mpn"])
                return result

        # Step 2: keyword with more results so we can score and filter
        parts = _keyword_search(mpn_token, records=10)
        result = _best_result(parts, mpn_token)
        if result:
            log.debug("Mouser keyword hit: %s", result["mpn"])
        return result

    else:
        # Passive / descriptive query — keyword only
        parts = _keyword_search(query, records=MAX_RESULTS_PER_QUERY)
        return _best_result(parts, query)