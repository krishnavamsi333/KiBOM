"""
cache.py — JSON-backed MPN lookup cache with TTL.

Entries automatically expire after CACHE_TTL_DAYS days, so you never
need to manually clear cache/mpn_cache.json between runs.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

CACHE_FILE    = os.path.join(os.path.dirname(__file__), "cache", "mpn_cache.json")
CACHE_TTL_DAYS = 7                          # change to 0 to disable TTL
_TTL_SECONDS   = CACHE_TTL_DAYS * 86_400


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def _is_expired(entry: Any) -> bool:
    """Return True if entry is too old (or uses old format without timestamp)."""
    if _TTL_SECONDS <= 0:
        return False
    if not isinstance(entry, dict) or "_cached_at" not in entry:
        return True          # old-format entry — treat as expired
    return (time.time() - entry["_cached_at"]) > _TTL_SECONDS


# ── Public API ────────────────────────────────────────────────────────────────

def get(key: str) -> dict | None:
    """Return cached result for *key*, or None if missing / expired."""
    store = _load()
    entry = store.get(key)
    if entry is None:
        return None
    if _is_expired(entry):
        # Drop stale entry lazily
        del store[key]
        _save(store)
        return None
    # Strip internal metadata before returning
    return {k: v for k, v in entry.items() if k != "_cached_at"}


def put(key: str, value: dict) -> None:
    """Store *value* under *key* with a current timestamp."""
    store = _load()
    store[key] = {**value, "_cached_at": time.time()}
    _save(store)


def purge_expired() -> int:
    """Remove all expired entries. Returns count of removed entries."""
    store   = _load()
    before  = len(store)
    store   = {k: v for k, v in store.items() if not _is_expired(v)}
    _save(store)
    return before - len(store)


def clear_all() -> None:
    """Wipe the entire cache (useful for --fresh flag)."""
    _save({})


def stats() -> dict:
    """Return cache statistics."""
    store   = _load()
    expired = sum(1 for v in store.values() if _is_expired(v))
    return {
        "total":   len(store),
        "valid":   len(store) - expired,
        "expired": expired,
    }