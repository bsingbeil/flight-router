"""
browser_pricer.py — backup flight pricer that reads Google Flights in a real browser.

Why this exists: fli's price parser returns price=0.0 for many intra-China and
China-exit legs (see CLAUDE.md "fli zero-price gotcha"). A real browser renders
the price as text, so when fli reports zero, pricer.py asks this module instead.

How it works (no AI involved):
  1. Build a Google Flights results URL for the leg (one-way, economy, CAD).
  2. Open it in headless Chromium via Playwright.
  3. Read the accessibility labels on each result row. Google writes them like:
       "From 271 US dollars. Nonstop flight with British Airways. Leaves Zurich
        Airport at 1:20 PM on Sunday, September 20 and arrives at Heathrow
        Airport at 2:20 PM on Sunday, September 20. Total duration 2 hr.
        Select flight"
  4. Pick the cheapest NONSTOP row on the requested date (matching the
     MaxStops.NON_STOP filter pricer._real_fli_search uses).

Results are cached on disk (CACHE_TTL_HOURS) because each lookup opens a browser
and takes several seconds.

Setup (one time):  pip install playwright && playwright install chromium
Manual probe:      python browser_pricer.py CKG HKG 2026-11-15
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import date as Date
from pathlib import Path
from typing import Optional
from urllib.parse import quote


# ---------- Configuration ----------

CACHE_TTL_HOURS = 6
CACHE_FILE = Path(__file__).parent / ".browser_price_cache.json"
PAGE_TIMEOUT_MS = 45_000      # initial page load
RESULTS_TIMEOUT_MS = 20_000   # waiting for result rows to appear
REQUEST_CURRENCY = "CAD"      # asked for via ?curr=; parser still reads whatever comes back

# Spelled-out currency names Google uses in result labels -> ISO codes.
# Anything not listed here is rejected rather than guessed (a wrong currency
# makes a price silently ~100x off).
CURRENCY_NAMES = {
    "canadian dollars": "CAD",
    "us dollars": "USD",
    "chinese yuan": "CNY",
    "euros": "EUR",
    "british pounds": "GBP",
    "japanese yen": "JPY",
    "australian dollars": "AUD",
    "hong kong dollars": "HKD",
    "singapore dollars": "SGD",
    "thai baht": "THB",
    "south korean won": "KRW",
}

# Only one browser at a time: pricer.py runs 6 worker threads, and parallel
# headless browsers are heavy and more likely to trip Google's rate limiting.
_browser_lock = threading.Lock()
_cache_lock = threading.Lock()


# ---------- Pure helpers (no I/O — unit tested) ----------

def build_search_url(origin: str, destination: str, date: str) -> str:
    """Google Flights results URL for a one-way economy search on `date` (YYYY-MM-DD)."""
    query = f"Flights from {origin} to {destination} on {date} one way"
    return (
        "https://www.google.com/travel/flights"
        f"?q={quote(query)}&curr={REQUEST_CURRENCY}&hl=en&gl=CA"
    )


_PRICE_RE = re.compile(r"From ([\d,]+(?:\.\d+)?) ([A-Za-z .]+?)\.")
_AIRLINE_RE = re.compile(r"flight with (.+?)\.")
_DURATION_RE = re.compile(r"Total duration (?:(\d+) hr)?\s*(?:(\d+) min)?")
# Google puts a narrow no-break space (U+202F) before AM/PM on some pages.
_DEPART_RE = re.compile(r"Leaves .+? at (\d{1,2}):(\d{2})[\s\u202f]*([AP]M) on")


def _date_phrase(date: str) -> str:
    """'2026-09-20' -> 'Sunday, September 20' (the wording Google uses for departures)."""
    d = Date.fromisoformat(date)
    return f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}"


def parse_result_label(label: str, date: str) -> Optional[dict]:
    """Parse one result-row label. Returns None if it isn't a usable nonstop result."""
    if "Nonstop flight" not in label:
        return None
    # Departure must be on the requested date (Google sometimes shows nearby days).
    if f"on {_date_phrase(date)} and arrives" not in label:
        return None

    price_m = _PRICE_RE.search(label)
    if not price_m:
        return None
    price = float(price_m.group(1).replace(",", ""))
    ccy = CURRENCY_NAMES.get(price_m.group(2).strip().lower())
    if price <= 0 or ccy is None:
        return None

    dur_m = _DURATION_RE.search(label)
    if not dur_m or not (dur_m.group(1) or dur_m.group(2)):
        return None
    duration_min = int(dur_m.group(1) or 0) * 60 + int(dur_m.group(2) or 0)

    departs = None
    dep_m = _DEPART_RE.search(label)
    if dep_m:
        hour = int(dep_m.group(1)) % 12 + (12 if dep_m.group(3) == "PM" else 0)
        departs = f"{date}T{hour:02d}:{dep_m.group(2)}"

    airline_m = _AIRLINE_RE.search(label)
    return {
        "price": price,
        "currency": ccy,
        "duration_min": duration_min,
        "airline": airline_m.group(1).strip() if airline_m else "Unknown",
        "departs": departs,
    }


def pick_cheapest(labels: list[str], date: str) -> Optional[dict]:
    """Cheapest usable nonstop result among a page's labels, or None.

    Prices in different currencies aren't compared directly — in practice a
    page is single-currency, so we keep only the currency of the first match.
    """
    parsed = [r for r in (parse_result_label(l, date) for l in labels) if r]
    if not parsed:
        return None
    ccy = parsed[0]["currency"]
    return min((r for r in parsed if r["currency"] == ccy), key=lambda r: r["price"])


# ---------- Disk cache ----------

def _cache_key(origin: str, destination: str, date: str) -> str:
    return f"{origin}-{destination}-{date}"


def _read_cache() -> dict:
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _cache_get(key: str) -> tuple[bool, Optional[dict]]:
    """(hit, result). A cached 'no flights' is a hit with result None."""
    with _cache_lock:
        entry = _read_cache().get(key)
    if not entry or time.time() - entry.get("ts", 0) > CACHE_TTL_HOURS * 3600:
        return False, None
    return True, entry.get("result")


def _cache_put(key: str, result: Optional[dict]) -> None:
    with _cache_lock:
        data = _read_cache()
        data[key] = {"ts": time.time(), "result": result}
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump(data, f, indent=1)
        except OSError:
            pass   # cache is an optimisation; never fail a search over it


# ---------- Browser ----------

def _fetch_result_labels(url: str) -> list[str]:
    """Open `url` in headless Chromium and return the labels of all result rows."""
    # Imported here so the rest of the project works without Playwright installed.
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(locale="en-CA")
            page.goto(url, timeout=PAGE_TIMEOUT_MS)
            try:
                page.wait_for_selector("[aria-label*='Select flight']", timeout=RESULTS_TIMEOUT_MS)
            except PWTimeout:
                return []   # no results, consent wall, or blocked — caller treats as "no flights"
            return page.eval_on_selector_all(
                "[aria-label*='Select flight']",
                "els => els.map(e => e.getAttribute('aria-label'))",
            )
        finally:
            browser.close()


def search(origin: str, destination: str, date: str) -> Optional[dict]:
    """Price one leg via the browser. Same return shape as pricer._real_fli_search.

    Returns {"price", "currency", "duration_min", "airline"} or None.
    Raises on browser/network failure so pricer can report the error.
    """
    key = _cache_key(origin, destination, date)
    hit, cached = _cache_get(key)
    if hit:
        return cached

    try:
        with _browser_lock:
            labels = _fetch_result_labels(build_search_url(origin, destination, date))
    except ImportError:
        print("[browser_pricer] WARN: Playwright not installed — skipping browser fallback. "
              "Run: pip install playwright && playwright install chromium")
        return None
    result = pick_cheapest(labels, date)
    _cache_put(key, result)
    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 4:
        sys.exit("usage: python browser_pricer.py ORIGIN DEST YYYY-MM-DD")
    o, d, dt = sys.argv[1].upper(), sys.argv[2].upper(), sys.argv[3]
    print(build_search_url(o, d, dt))
    print(search(o, d, dt))
