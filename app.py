"""
app.py — KiBOM v0.5 entry point

Usage:
  python app.py <bom.csv>               full run
  python app.py <bom.csv> --no-enrich   QA only, skip API calls
  python app.py <bom.csv> --debug       verbose API logging
  python app.py --test-apis             test which providers are working
  python app.py --clear-cache           wipe the MPN cache
"""

import os
import sys
import time
import logging

from parser   import load_bom
from enricher import enrich_bom
from checker  import analyze_bom
from exporter import export_excel
import cache


# ── --test-apis ───────────────────────────────────────────────────────────────

def test_apis() -> None:
    import requests
    from config import (
        NEXAR_CLIENT_ID, NEXAR_CLIENT_SECRET,
        DIGIKEY_CLIENT_ID, DIGIKEY_CLIENT_SECRET,
        MOUSER_API_KEY, ELEMENT14_API_KEY, ELEMENT14_STORE,
    )

    def ok(r):   return f"✓ OK  ({r.status_code})"
    def fail(r): return f"✗ {r.status_code}  {r.text[:120]}"

    print("\n── API connectivity ─────────────────────────────────────────────────")

    # Nexar
    if NEXAR_CLIENT_ID:
        try:
            tr = requests.post(
                "https://identity.nexar.com/connect/token",
                data={"grant_type": "client_credentials",
                      "client_id": NEXAR_CLIENT_ID,
                      "client_secret": NEXAR_CLIENT_SECRET},
                timeout=10,
            )
            if tr.ok:
                tok = tr.json()["access_token"]
                qr  = requests.post(
                    "https://api.nexar.com/graphql",
                    json={"query": 'query{supSearchMpn(q:"ADS1115",limit:1){results{part{mpn}}}}'},
                    headers={"Authorization": f"Bearer {tok}"},
                    timeout=10,
                )
                n = len(qr.json().get("data", {}).get("supSearchMpn", {}).get("results", []))
                status = f"✓ OK — {n} result(s)"
            else:
                status = fail(tr)
        except Exception as e:
            status = f"✗ {e}"
        print(f"  Nexar / Octopart  : {status}")
    else:
        print("  Nexar / Octopart  : — not configured")

    # DigiKey
    if DIGIKEY_CLIENT_ID:
        try:
            from config import DIGIKEY_CLIENT_SECRET, DIGIKEY_BASE_URL
            tr = requests.post(
                f"{DIGIKEY_BASE_URL}/v1/oauth2/token",
                data={"grant_type": "client_credentials",
                      "client_id": DIGIKEY_CLIENT_ID,
                      "client_secret": DIGIKEY_CLIENT_SECRET},
                timeout=10,
            )
            if tr.ok:
                tok  = tr.json()["access_token"]
                hdrs = {
                    "Authorization": f"Bearer {tok}",
                    "X-DIGIKEY-Client-Id": DIGIKEY_CLIENT_ID,
                    "Content-Type": "application/json",
                    "X-DIGIKEY-Locale-Site": "US",
                    "X-DIGIKEY-Locale-Language": "en",
                    "X-DIGIKEY-Locale-Currency": "USD",
                }
                sr = requests.post(
                    f"{DIGIKEY_BASE_URL}/products/v4/search/keyword",
                    json={"keywords": "ADS1115", "limit": 1, "offset": 0},
                    headers=hdrs, timeout=10,
                )
                if sr.ok:
                    products = sr.json().get("Products") or sr.json().get("products") or []
                    if products:
                        status = f"✓ OK — {len(products)} product(s)"
                    else:
                        status = "⚠ Auth OK but 0 products — check Sandbox vs Production"
                else:
                    status = f"✓ Auth OK, search {fail(sr)}"
            else:
                status = fail(tr)
        except Exception as e:
            status = f"✗ {e}"
        print(f"  DigiKey           : {status}")
    else:
        print("  DigiKey           : — not configured")

    # Mouser
    if MOUSER_API_KEY:
        try:
            r = requests.post(
                f"https://api.mouser.com/api/v1/search/keyword?apiKey={MOUSER_API_KEY}",
                json={"SearchByKeywordRequest": {
                    "keyword": "ADS1115", "records": 1,
                    "startingRecord": 0, "searchOptions": "None"}},
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            if r.ok:
                body   = r.json() or {}
                errors = body.get("Errors") or []
                if errors:
                    msg    = errors[0].get("Message", "unknown error")
                    status = f"✗ {msg}"
                else:
                    n = len((body.get("SearchResults") or {}).get("Parts") or [])
                    status = f"✓ OK — {n} part(s)"
            else:
                status = fail(r)
        except Exception as e:
            status = f"✗ {e}"
        print(f"  Mouser            : {status}")
    else:
        print("  Mouser            : — not configured")

    # Element14
    if ELEMENT14_API_KEY:
        try:
            r = requests.get(
                "https://api.element14.com/catalog/products",
                params={"term": "any:resistor", "storeInfo.id": ELEMENT14_STORE,
                        "resultsSettings.offset": 0, "resultsSettings.numberOfResults": 1,
                        "resultsSettings.responseGroup": "small",
                        "callinfo.apiKey": ELEMENT14_API_KEY},
                timeout=10,
            )
            print(f"  Element14         : {ok(r) if r.ok else fail(r)}")
        except Exception as e:
            print(f"  Element14         : ✗ {e}")
    else:
        print("  Element14         : — not configured")

    print("─────────────────────────────────────────────────────────────────────\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=================================")
    print("KiBOM v0.5")
    print("Smart BOM QA + MPN Enrichment")
    print("=================================\n")

    args = sys.argv[1:]

    if "--debug" in args:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
        args = [a for a in args if a != "--debug"]
    else:
        logging.basicConfig(level=logging.WARNING)

    if "--test-apis" in args:
        test_apis()
        return

    if "--clear-cache" in args:
        cache.clear_all()
        print("Cache cleared.")
        args = [a for a in args if a != "--clear-cache"]
        if not args:
            return

    if not args:
        print("Usage: python app.py <bom.csv> [--no-enrich] [--debug]")
        print("       python app.py --test-apis")
        print("       python app.py --clear-cache")
        return

    bom_path    = args[0]
    skip_enrich = "--no-enrich" in args

    # Derive project name from CSV filename
    project_name = os.path.splitext(os.path.basename(bom_path))[0].replace("_", " ")

    df = load_bom(bom_path)
    print(f"Loaded {len(df)} components from {bom_path}\n")

    if not skip_enrich:
        c = cache.stats()
        print(f"Cache: {c['valid']} valid  |  {c['expired']} expired  |  {c['total']} total")
        print("Enriching BOM …\n")
        t0  = time.time()
        df  = enrich_bom(df)
        elapsed = time.time() - t0

        sources = list(df.get("enrich_source", []))
        found   = sum(1 for s in sources if s and s not in ("not found", "skipped"))
        skipped = sum(1 for s in sources if s == "skipped")
        missing = sum(1 for s in sources if s == "not found")
        cached  = sum(1 for s in sources if "(cached)" in str(s))

        print(f"\nEnrichment done in {elapsed:.1f}s")
        print(f"  ✓ Found   : {found}  ({cached} from cache)")
        print(f"  ✗ Missing : {missing}")
        print(f"  — Skipped : {skipped}  (test points / power flags)")

        if missing:
            print("\n  Tips:")
            print("    • Run --test-apis to verify which providers are reachable")
            print("    • Run with --debug to see raw API responses")
            print("    • Set NEXAR credentials in .env for broadest coverage")
    else:
        print("Skipping enrichment (--no-enrich)\n")

    checked_df  = analyze_bom(df)
    issue_count = int(checked_df["issues"].astype(bool).sum())
    print(f"\nQA: {issue_count} row(s) flagged")

    output_path = "reports/bom_enriched.xlsx"
    print(f"\nExporting → {output_path}")
    export_excel(checked_df, output_path, project_name=project_name)
    print("\nDone.")


if __name__ == "__main__":
    main()