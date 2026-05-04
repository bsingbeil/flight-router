"""
currency.py — live FX rates with a 24hr disk cache and background refresh.

Flow:
  1. start_background_refresh()    Call this early. Non-blocking.
                                   If disk cache is fresh (<24hr), loads it.
                                   Otherwise spawns a thread that fetches
                                   live rates and writes to disk.
  2. get_rates()                   Returns rates dict. Order of preference:
                                   in-memory cache → disk → bg thread (waits
                                   briefly) → sync fetch → bootstrap fallback.

Rates are stored to a hidden file next to this module (.fx_cache.json).
Add it to .gitignore — the timestamps are local, not source code.

Bootstrap fallback rates are only used the very first time the script runs
on a brand-new machine WITH no internet. After that, the disk cache is
authoritative until the next 24hr refresh.

Provider: Frankfurter (api.frankfurter.app) — free, no key, ECB-sourced.
To swap providers, edit _fetch_rates_from_api() only.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------- Configuration ----------

DISPLAY_CURRENCY = "CAD"
CACHE_TTL_HOURS = 24
CACHE_FILE = Path(__file__).parent / ".fx_cache.json"

# Currencies we care about. Frankfurter accepts these as a comma list.
TRACKED_CURRENCIES = ["CAD", "CNY", "EUR", "GBP", "JPY", "AUD", "HKD", "SGD", "THB", "KRW"]

# Last-resort rates for the very first run on a fresh machine with no network.
# Once the disk cache exists, these are never consulted again.
BOOTSTRAP_RATES = {
    "USD_TO_CAD": 1.38,
    "USD_TO_CNY": 7.20,
    "USD_TO_EUR": 0.93,
    "USD_TO_GBP": 0.79,
    "USD_TO_JPY": 152.0,
    "USD_TO_AUD": 1.52,
    "USD_TO_HKD": 7.80,
    "USD_TO_SGD": 1.35,
    "USD_TO_THB": 35.5,
    "USD_TO_KRW": 1370.0,
}

CURRENCY_SYMBOLS = {
    "CAD": "C$", "USD": "US$", "CNY": "¥", "EUR": "€", "GBP": "£",
}


# ---------- Module state ----------

_rates_cache: Optional[dict] = None
_rates_source: str = "uninitialized"   # "live", "disk", "stale-disk", "bootstrap"
_bg_thread: Optional[threading.Thread] = None
_bg_lock = threading.Lock()


# ---------- Disk cache I/O ----------

def _read_disk_cache() -> Optional[dict]:
    """Load {fetched_at, rates} from disk, or None if file missing/corrupt."""
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def _write_disk_cache(rates: dict) -> None:
    """Save rates with a UTC timestamp."""
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "rates": rates,
    }
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        print(f"[currency] failed to write cache: {e}")


def _is_fresh(disk_data: dict) -> bool:
    """True if the cache timestamp is within CACHE_TTL_HOURS."""
    try:
        fetched = datetime.fromisoformat(disk_data["fetched_at"])
        age_hours = (datetime.now(timezone.utc) - fetched).total_seconds() / 3600
        return age_hours < CACHE_TTL_HOURS
    except Exception:
        return False


# ---------- Network fetch ----------

def _fetch_rates_from_api() -> Optional[dict]:
    """One HTTP call to Frankfurter, returns USD-anchored rates dict."""
    to_param = ",".join(TRACKED_CURRENCIES)
    url = f"https://api.frankfurter.app/latest?from=USD&to={to_param}"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        api_rates = data.get("rates", {})
    except Exception:
        return None

    rates = {}
    for ccy in TRACKED_CURRENCIES:
        key = f"USD_TO_{ccy}"
        rates[key] = float(api_rates.get(ccy, BOOTSTRAP_RATES.get(key, 1.0)))
    # Convenience cross-rate used by train fare conversion.
    rates["CNY_TO_CAD"] = rates["USD_TO_CAD"] / rates["USD_TO_CNY"]
    return rates


# ---------- Background refresh worker ----------

def _refresh_worker() -> None:
    """Worker: fetch fresh rates, write to disk, populate in-memory cache."""
    global _rates_cache, _rates_source
    fresh = _fetch_rates_from_api()
    if fresh is None:
        # Don't overwrite anything — get_rates() will fall back appropriately.
        return
    _write_disk_cache(fresh)
    _rates_cache = fresh
    _rates_source = "live"
    print(f"[currency] FX refreshed (live): "
          f"1 USD = {fresh['USD_TO_CAD']:.3f} CAD, {fresh['USD_TO_CNY']:.3f} CNY")


def start_background_refresh() -> None:
    """Kick off a non-blocking FX refresh. Safe to call multiple times.

    If the disk cache is fresh, this just loads it into memory and returns.
    If stale or missing, spawns a daemon thread to fetch new rates while
    the rest of the program continues (e.g. user enters trip details).
    """
    global _bg_thread, _rates_cache, _rates_source

    disk = _read_disk_cache()
    if disk is not None and _is_fresh(disk):
        # Cache fresh — load into memory immediately, no network call.
        _rates_cache = disk["rates"]
        _rates_source = "disk"
        return

    # Stale or missing — fire off background fetch.
    with _bg_lock:
        if _bg_thread is not None and _bg_thread.is_alive():
            return  # already in progress
        _bg_thread = threading.Thread(target=_refresh_worker, daemon=True)
        _bg_thread.start()


# ---------- Main entry ----------

def get_rates() -> dict:
    """Return the rates dict, blocking briefly if a background fetch is running."""
    global _rates_cache, _rates_source

    if _rates_cache is not None:
        return _rates_cache

    # Try disk first (handles case where start_background_refresh wasn't called)
    disk = _read_disk_cache()
    if disk is not None and _is_fresh(disk):
        _rates_cache = disk["rates"]
        _rates_source = "disk"
        return _rates_cache

    # Wait for background thread if running
    if _bg_thread is not None and _bg_thread.is_alive():
        _bg_thread.join(timeout=8)
        if _rates_cache is not None:
            return _rates_cache

    # Synchronous fetch
    fresh = _fetch_rates_from_api()
    if fresh is not None:
        _write_disk_cache(fresh)
        _rates_cache = fresh
        _rates_source = "live"
        print(f"[currency] FX loaded (live): "
              f"1 USD = {fresh['USD_TO_CAD']:.3f} CAD, {fresh['USD_TO_CNY']:.3f} CNY")
        return _rates_cache

    # Stale disk is better than nothing
    if disk is not None:
        _rates_cache = disk["rates"]
        _rates_source = "stale-disk"
        print("[currency] FX API unreachable — using stale cached rates.")
        return _rates_cache

    # Last resort
    rates = dict(BOOTSTRAP_RATES)
    rates["CNY_TO_CAD"] = rates["USD_TO_CAD"] / rates["USD_TO_CNY"]
    _rates_cache = rates
    _rates_source = "bootstrap"
    print("[currency] No network and no cache — using bootstrap rates.")
    return _rates_cache


def get_source() -> str:
    """'live', 'disk', 'stale-disk', or 'bootstrap'. Useful for debugging."""
    return _rates_source


# ---------- Conversion helpers ----------

def usd_to_display(amount_usd: float) -> float:
    rates = get_rates()
    if DISPLAY_CURRENCY == "USD":
        return amount_usd
    key = f"USD_TO_{DISPLAY_CURRENCY}"
    if key not in rates:
        raise ValueError(f"No rate for {DISPLAY_CURRENCY}")
    return amount_usd * rates[key]


def cny_to_display(amount_cny: float) -> float:
    rates = get_rates()
    if DISPLAY_CURRENCY == "CNY":
        return amount_cny
    if DISPLAY_CURRENCY == "CAD":
        return amount_cny * rates["CNY_TO_CAD"]
    if DISPLAY_CURRENCY == "USD":
        return amount_cny / rates["USD_TO_CNY"]
    # General path: CNY -> USD -> target
    usd = amount_cny / rates["USD_TO_CNY"]
    return usd * rates[f"USD_TO_{DISPLAY_CURRENCY}"]


def convert_to_display(amount: float, from_currency: str) -> float:
    """Convert amount from any tracked currency to the display currency.

    Path: from_ccy → USD → display_ccy. The 'USD_TO_<ccy>' rates in get_rates()
    are USD-anchored, so we divide to go ccy→USD and multiply to go USD→ccy.
    Falls back to passing the amount through if the currency is unrecognised.
    """
    if from_currency == DISPLAY_CURRENCY:
        return amount
    rates = get_rates()

    # Step 1: convert from_currency → USD
    if from_currency == "USD":
        usd = amount
    else:
        rate_key = f"USD_TO_{from_currency}"
        if rate_key not in rates:
            # Unknown currency — assume USD as best guess (safer than crashing).
            print(f"[currency] WARN: unknown source currency {from_currency!r}, "
                  f"treating as USD")
            usd = amount
        else:
            usd = amount / rates[rate_key]

    # Step 2: convert USD → display
    if DISPLAY_CURRENCY == "USD":
        return usd
    return usd * rates[f"USD_TO_{DISPLAY_CURRENCY}"]


def display_symbol() -> str:
    return CURRENCY_SYMBOLS.get(DISPLAY_CURRENCY, DISPLAY_CURRENCY + " ")


def format_amount(amount: float) -> str:
    return f"{display_symbol()}{amount:,.0f}"
