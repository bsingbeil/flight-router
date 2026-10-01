"""Tests for browser_pricer: label parsing, cache, and the pricer zero-price fallback.

No browser or network is used — _fetch_result_labels is monkeypatched. The
labels below are real Google Flights result labels (Zurich -> London, captured
in browser-use/jev-ultrafast's recorded run), plus edited variants.
"""
import pytest

import browser_pricer
import pricer

DATE = "2026-09-20"   # a Sunday

EASYJET = ("From 216 US dollars.This price does not include overhead bin access. Nonstop flight "
           "with easyJet. Leaves Zurich Airport at 4:45 PM on Sunday, September 20 and arrives at "
           "London Gatwick Airport at 5:35 PM on Sunday, September 20. Total duration 1 hr 50 min. "
           "  Select flight")
BA_CITY = ("From 265 US dollars. Nonstop flight with British Airways. Operated by BA Cityflyer. "
           "Leaves Zurich Airport at 8:25 PM on Sunday, September 20 and arrives at London City "
           "Airport at 9:00 PM on Sunday, September 20. Total duration 1 hr 35 min.   Select flight")
BA_LHR = ("From 271 US dollars. Nonstop flight with British Airways. Leaves Zurich Airport at "
          "1:20 PM on Sunday, September 20 and arrives at Heathrow Airport at 2:20 PM on Sunday, "
          "September 20. Total duration 2 hr.   Select flight")
ONE_STOP_CHEAP = ("From 99 US dollars. 1 stop flight with Lufthansa. Leaves Zurich Airport at "
                  "6:00 AM on Sunday, September 20 and arrives at Heathrow Airport at 11:00 AM on "
                  "Sunday, September 20. Total duration 5 hr.   Select flight")


@pytest.fixture(autouse=True)
def _tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_pricer, "CACHE_FILE", tmp_path / "cache.json")


# ---------- parsing ----------

def test_parse_real_label():
    assert browser_pricer.parse_result_label(EASYJET, DATE) == {
        "price": 216.0, "currency": "USD", "duration_min": 110, "airline": "easyJet",
        "departs": "2026-09-20T16:45",
    }


def test_parse_hours_only_duration():
    assert browser_pricer.parse_result_label(BA_LHR, DATE)["duration_min"] == 120


def test_parse_minutes_only_duration_and_comma_price():
    label = BA_LHR.replace("271 US dollars", "1,234 Canadian dollars").replace("2 hr.", "45 min.")
    r = browser_pricer.parse_result_label(label, DATE)
    assert r["price"] == 1234.0 and r["currency"] == "CAD" and r["duration_min"] == 45


def test_rejects_non_nonstop():
    assert browser_pricer.parse_result_label(ONE_STOP_CHEAP, DATE) is None


def test_rejects_wrong_date():
    assert browser_pricer.parse_result_label(EASYJET, "2026-09-21") is None


def test_rejects_unknown_currency():
    label = EASYJET.replace("US dollars", "Martian credits")
    assert browser_pricer.parse_result_label(label, DATE) is None


def test_rejects_zero_price():
    assert browser_pricer.parse_result_label(EASYJET.replace("216", "0"), DATE) is None


def test_pick_cheapest_nonstop_ignores_cheaper_one_stop():
    r = browser_pricer.pick_cheapest([BA_LHR, ONE_STOP_CHEAP, EASYJET, BA_CITY], DATE)
    assert r["price"] == 216.0 and r["airline"] == "easyJet"


def test_pick_cheapest_empty():
    assert browser_pricer.pick_cheapest([], DATE) is None


def test_build_search_url():
    url = browser_pricer.build_search_url("CKG", "HKG", "2026-11-15")
    assert url.startswith("https://www.google.com/travel/flights?q=")
    assert "CKG" in url and "HKG" in url and "2026-11-15" in url and "curr=CAD" in url


# ---------- search + cache ----------

def test_search_caches_results(monkeypatch):
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return [BA_LHR, EASYJET]

    monkeypatch.setattr(browser_pricer, "_fetch_result_labels", fake_fetch)
    first = browser_pricer.search("ZRH", "LHR", DATE)
    second = browser_pricer.search("ZRH", "LHR", DATE)
    assert first == second and first["price"] == 216.0
    assert len(calls) == 1   # second call served from disk cache


def test_search_caches_no_flights(monkeypatch):
    calls = []
    monkeypatch.setattr(browser_pricer, "_fetch_result_labels", lambda url: calls.append(url) or [])
    assert browser_pricer.search("ZRH", "LHR", DATE) is None
    assert browser_pricer.search("ZRH", "LHR", DATE) is None
    assert len(calls) == 1


def test_search_without_playwright_returns_none(monkeypatch):
    def no_playwright(url):
        raise ImportError("No module named 'playwright'")

    monkeypatch.setattr(browser_pricer, "_fetch_result_labels", no_playwright)
    assert browser_pricer.search("ZRH", "LHR", DATE) is None


# ---------- pricer integration ----------

class _FakeResult:
    def __init__(self, price):
        self.price = price
        self.currency = "CNY"
        self.duration = 150
        self.legs = []


def _fake_fli(monkeypatch, price):
    fli_search = pytest.importorskip("fli.search")

    class FakeSearchFlights:
        def search(self, filters):
            return [_FakeResult(price)]

    monkeypatch.setattr(fli_search, "SearchFlights", FakeSearchFlights)


def test_zero_price_uses_browser_fallback(monkeypatch):
    _fake_fli(monkeypatch, 0.0)
    monkeypatch.setattr(pricer, "USE_BROWSER_FALLBACK", True)
    monkeypatch.setattr(browser_pricer, "search", lambda o, d, dt: {
        "price": 1500.0, "currency": "CNY", "duration_min": 150, "airline": "Cathay Pacific",
    })
    assert pricer._real_fli_search("HKG", "CKG", "2026-11-15")["price"] == 1500.0


def test_zero_price_without_fallback_returns_none(monkeypatch):
    _fake_fli(monkeypatch, 0.0)
    monkeypatch.setattr(pricer, "USE_BROWSER_FALLBACK", False)
    monkeypatch.setattr(browser_pricer, "search", lambda *a: pytest.fail("should not be called"))
    assert pricer._real_fli_search("HKG", "CKG", "2026-11-15") is None


def test_nonzero_price_skips_browser(monkeypatch):
    _fake_fli(monkeypatch, 1200.0)
    monkeypatch.setattr(pricer, "USE_BROWSER_FALLBACK", True)
    monkeypatch.setattr(browser_pricer, "search", lambda *a: pytest.fail("should not be called"))
    assert pricer._real_fli_search("HKG", "CKG", "2026-11-15")["price"] == 1200.0
