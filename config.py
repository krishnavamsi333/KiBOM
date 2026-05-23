"""
config.py — KiBOM settings
All credentials come from environment variables or a .env file.
Copy .env.example → .env and fill in your keys.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# ── Nexar / Octopart ──────────────────────────────────────────────────────────
NEXAR_CLIENT_ID     = os.getenv("NEXAR_CLIENT_ID",     "")
NEXAR_CLIENT_SECRET = os.getenv("NEXAR_CLIENT_SECRET", "")

# ── DigiKey v4 ────────────────────────────────────────────────────────────────
# Must be Production credentials (not Sandbox) for real data.
# developer.digikey.com → your app → switch to Production
DIGIKEY_CLIENT_ID     = os.getenv("DIGIKEY_CLIENT_ID",     "")
DIGIKEY_CLIENT_SECRET = os.getenv("DIGIKEY_CLIENT_SECRET", "")
DIGIKEY_BASE_URL      = os.getenv("DIGIKEY_BASE_URL",      "https://api.digikey.com")

# ── Mouser ────────────────────────────────────────────────────────────────────
MOUSER_API_KEY  = os.getenv("MOUSER_API_KEY",  "")
MOUSER_BASE_URL = "https://api.mouser.com/api/v1"

# ── Element14 / Newark / Farnell ──────────────────────────────────────────────
ELEMENT14_API_KEY = os.getenv("ELEMENT14_API_KEY", "")
ELEMENT14_STORE   = os.getenv("ELEMENT14_STORE",   "in.element14.com")  # India

# ── LCSC (unofficial) ─────────────────────────────────────────────────────────
LCSC_ENABLED = os.getenv("LCSC_ENABLED", "true").lower() in ("1", "true", "yes")

# ── Cache ─────────────────────────────────────────────────────────────────────
CACHE_FILE    = "cache/mpn_cache.json"
CACHE_ENABLED = True

# ── Request / enrichment ──────────────────────────────────────────────────────
MAX_RESULTS_PER_QUERY = 3
REQUEST_TIMEOUT       = 12

# ── INR pricing ───────────────────────────────────────────────────────────────
INR_RATE = 96.27   # 1 USD → INR  (update periodically)
GST_RATE = 0.18    # import duty / GST added on top


def warn_missing() -> None:
    """Print warnings for unconfigured providers at startup."""
    missing = []
    if not MOUSER_API_KEY:
        missing.append("MOUSER_API_KEY")
    if not DIGIKEY_CLIENT_ID:
        missing.append("DIGIKEY_CLIENT_ID / DIGIKEY_CLIENT_SECRET")
    if not NEXAR_CLIENT_ID:
        missing.append("NEXAR_CLIENT_ID / NEXAR_CLIENT_SECRET (optional but best coverage)")
    if not ELEMENT14_API_KEY:
        missing.append("ELEMENT14_API_KEY (optional)")
    for m in missing:
        print(f"  ⚠  {m} not set — provider skipped")