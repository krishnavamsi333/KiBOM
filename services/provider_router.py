"""
services/provider_router.py — Route a query through available providers.

Cascade order (first confident hit wins):
  1. Mouser   — always tried if MOUSER_API_KEY is set
  2. (add Nexar, DigiKey, Element14, LCSC here when credentials are ready)

A "confident hit" means the result contains a non-empty mpn.
"""

from __future__ import annotations

import logging

from providers.mouser import lookup as mouser_lookup

log = logging.getLogger(__name__)


def lookup(query: str) -> dict | None:
    """Try each provider in cascade order. Return first confident result, or None."""

    # ── 1. Mouser ────────────────────────────────────────────────────────────
    try:
        result = mouser_lookup(query)
        if result and result.get("mpn"):
            return result
    except Exception as e:
        log.debug("Mouser provider failed: %s", e)

    # ── 2. (Nexar, DigiKey, Element14, LCSC placeholders) ────────────────────
    # Uncomment and import when credentials are configured:
    #
    # from providers.nexar import lookup as nexar_lookup
    # try:
    #     result = nexar_lookup(query)
    #     if result and result.get("mpn"):
    #         return result
    # except Exception as e:
    #     log.debug("Nexar provider failed: %s", e)

    return None