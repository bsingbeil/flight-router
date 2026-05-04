"""
pricer.py — turns route candidates into priced, ranked itineraries.

For each Itinerary from candidates.py:
  1. Look up live prices for every FLIGHT leg via fli (Google Flights)
  2. Use known train fares for any TRAIN legs (already stored in connections.py)
  3. Sum totals (CNY), estimate total travel time including transfers
  4. Rank: cheapest, fastest, best balance

Concurrency: flight pricing is I/O-bound, so we use a thread pool to
parallelize fli calls. A simple in-memory cache prevents duplicate API
calls when the same leg appears in multiple candidate routings.

NOTE: default is LIVE pricing via the fli library. Flip USE_MOCK = True
below to run against the synthetic mock pricer (useful for offline
development, unit tests, or working around fli rate limits / parser bugs).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from candidates import FLIGHT, TRAIN, Itinerary, Leg
import currency


# ---------- Configuration ----------

USE_MOCK = False         # default: live fli pricing. Flip to True for offline dev/test.
MAX_CONCURRENT_QUERIES = 6   # don't hammer Google Flights

# Transfer time penalty between flight legs (minutes).
SAME_AIRPORT_TRANSFER_MIN = 90
DIFFERENT_AIRPORT_TRANSFER_MIN = 240   # e.g. PEK -> PKX, or HKG-WK -> HKG


# ---------- Data classes ----------

@dataclass
class PricedLeg:
    """A leg with pricing data attached. Cost is in the configured display currency."""
    leg: Leg
    cost: Optional[float] = None
    duration_min: Optional[int] = None
    airline: Optional[str] = None
    error: Optional[str] = None

    @property
    def is_priced(self) -> bool:
        return self.cost is not None and self.error is None


@dataclass
class PricedItinerary:
    """An itinerary with all legs priced, plus computed totals."""
    itinerary: Itinerary
    priced_legs: list[PricedLeg] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """True if every leg was successfully priced."""
        return all(pl.is_priced for pl in self.priced_legs)

    @property
    def total_cost(self) -> Optional[float]:
        """Total cost in the display currency (CAD by default)."""
        if not self.is_complete:
            return None
        return sum(pl.cost for pl in self.priced_legs)

    @property
    def total_duration_min(self) -> Optional[int]:
        """Travel time including transfers."""
        if not self.is_complete:
            return None
        total = sum(pl.duration_min for pl in self.priced_legs)
        # Add transfer time between consecutive legs.
        for i in range(len(self.priced_legs) - 1):
            curr = self.priced_legs[i].leg
            nxt = self.priced_legs[i + 1].leg
            if curr.destination == nxt.origin:
                total += SAME_AIRPORT_TRANSFER_MIN
            else:
                total += DIFFERENT_AIRPORT_TRANSFER_MIN
        return total

    @property
    def total_duration_human(self) -> str:
        d = self.total_duration_min
        if d is None:
            return "?"
        return f"{d // 60}h{d % 60:02d}m"


# ---------- The fli call (REAL) ----------

def _real_fli_search(origin: str, destination: str, date: str) -> Optional[dict]:
    """Real call to fli library. Returns None if no flights found.

    Returns:
        {"price": float, "currency": str, "duration_min": int, "airline": str}

    `currency` is whatever Google Flights returns (often the IP-geolocated
    currency, e.g. JPY, USD, CNY). Pricer downstream converts to display.
    """
    # Imports kept inside the function so the module loads even without fli installed.
    from fli.search import SearchFlights
    from fli.models import (
        FlightSearchFilters, FlightSegment, Airport, PassengerInfo,
        SeatType, MaxStops, SortBy,
    )

    filters = FlightSearchFilters(
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[
            FlightSegment(
                departure_airport=[[Airport[origin], 0]],
                arrival_airport=[[Airport[destination], 0]],
                travel_date=date,
            )
        ],
        seat_type=SeatType.ECONOMY,
        stops=MaxStops.NON_STOP,        # FIX: was MaxStops.NONE which doesn't exist
        sort_by=SortBy.CHEAPEST,
    )
    results = SearchFlights().search(filters)
    if not results:
        return None

    # Result may be a FlightResult or a tuple of FlightResults — normalize.
    best = results[0]
    if isinstance(best, tuple):
        best = best[0]

    # Defensive: fli's price parser is known to return 0.0 for intra-China
    # and some China-exit legs where the CNY price encoding doesn't match
    # its decoder. Treat zero prices as "no valid result" so the leg gets
    # marked unpriceable and the itinerary gets excluded from rankings.
    # Better to show fewer options correctly than many options wrongly.
    if not best.price or float(best.price) <= 0.0:
        return None

    # Airline lives on the first leg, not the top-level result.
    airline_name = "Unknown"
    if best.legs:
        first_airline = best.legs[0].airline
        airline_name = getattr(first_airline, "value", str(first_airline)) or "Unknown"

    if best.currency is None:
        print(f"[pricer] WARN: fli returned no currency for {origin}->{destination}; "
              f"assuming USD. Price={best.price}. If totals look ~7-150x off, this is the cause.")

    return {
        "price": float(best.price),
        "currency": best.currency or "USD",
        "duration_min": int(best.duration),
        "airline": airline_name,
    }


# ---------- The fli call (MOCK for development) ----------

# Rough great-circle-ish distances in km between common nodes (fabricated, just
# enough to make mock prices vary realistically). Falls back to a default.
_MOCK_DISTANCE_KM = {
    ("CKG", "CTU"): 270, ("CKG", "PEK"): 1460, ("CKG", "PVG"): 1450,
    ("CKG", "CAN"): 980, ("CKG", "HKG"): 1100, ("CKG", "BKK"): 1750,
    ("CKG", "DAD"): 1900, ("CKG", "SIN"): 3200, ("CKG", "DOH"): 5800,
    ("CKG", "YVR"): 9700, ("CKG", "YYZ"): 11200, ("CKG", "LHR"): 8400,
    ("CKG", "VIE"): 7700, ("CKG", "MUC"): 7600,
    ("HKG", "BKK"): 1700, ("HKG", "VIE"): 9000, ("HKG", "DAD"): 920,
    ("DAD", "HAN"): 600, ("DAD", "SGN"): 600, ("DAD", "BKK"): 980,
    ("HAN", "CKG"): 880, ("SGN", "CKG"): 1900, ("HAN", "SZX"): 950,
    ("DOH", "VIE"): 4000, ("DXB", "VIE"): 4250, ("ICN", "VIE"): 8200,
}


def _mock_fli_search(origin: str, destination: str, date: str) -> Optional[dict]:
    """Synthesize plausible flight data so the rest of the pipeline can be tested."""
    key = (origin, destination)
    rev_key = (destination, origin)
    distance = _MOCK_DISTANCE_KM.get(key) or _MOCK_DISTANCE_KM.get(rev_key)
    if distance is None:
        # Default guess so we always return *something* for testing.
        distance = 2500

    # ~$0.10 USD/km baseline + random-ish variation by route hash.
    h = abs(hash((origin, destination, date))) % 100
    price_usd = distance * 0.10 * (0.85 + h / 333)   # ±15% variation
    # 800 km/h cruise + 30min taxi/turn time.
    duration_min = int(distance / 800 * 60 + 30)
    return {
        "price": round(price_usd, 2),
        "currency": "USD",
        "duration_min": duration_min,
        "airline": f"MOCK-{(h % 7) + 1}",
    }


# Pick implementation based on USE_MOCK flag.
_fli_search: Callable[[str, str, str], Optional[dict]] = (
    _mock_fli_search if USE_MOCK else _real_fli_search
)


# ---------- Pricer ----------

def _price_flight_leg(leg: Leg, date: str, cache: dict, cache_lock: threading.Lock) -> PricedLeg:
    """Price a single flight leg, using cache to avoid duplicate API calls.

    The cache_lock serializes dict reads/writes across worker threads. The
    fli call itself runs OUTSIDE the lock so concurrency is preserved for
    distinct keys. A small race window remains where two threads can make
    duplicate calls for the same key (both miss the cache before either
    writes), but neither result will corrupt the cache.
    """
    cache_key = (leg.origin, leg.destination, date)

    with cache_lock:
        if cache_key in cache:
            return PricedLeg(leg=leg, **cache[cache_key])

    # Cache miss — call fli outside the lock
    try:
        result = _fli_search(leg.origin, leg.destination, date)
    except Exception as e:
        priced = PricedLeg(leg=leg, error=f"fli call failed: {e}")
        with cache_lock:
            cache[cache_key] = {"error": priced.error}
        return priced

    if result is None:
        priced = PricedLeg(leg=leg, error="No flights found")
        with cache_lock:
            cache[cache_key] = {"error": priced.error}
        return priced

    cost = currency.convert_to_display(result["price"], result["currency"])
    payload = {
        "cost": cost,
        "duration_min": result["duration_min"],
        "airline": result.get("airline"),
    }
    with cache_lock:
        cache[cache_key] = payload
    return PricedLeg(leg=leg, **payload)


def _price_train_leg(leg: Leg) -> PricedLeg:
    """Train legs already carry CNY cost from connections.py — convert to display currency."""
    cost_display = (
        currency.cny_to_display(float(leg.cost_cny))
        if leg.cost_cny is not None else None
    )
    return PricedLeg(
        leg=leg,
        cost=cost_display,
        duration_min=leg.duration_min,
        airline="HSR",
    )


def price_itinerary(itin: Itinerary, date: str, cache: dict, cache_lock: threading.Lock) -> PricedItinerary:
    """Price every leg of one itinerary."""
    priced_legs = []
    for leg in itin.legs:
        if leg.mode == TRAIN:
            priced_legs.append(_price_train_leg(leg))
        else:
            priced_legs.append(_price_flight_leg(leg, date, cache, cache_lock))
    return PricedItinerary(itinerary=itin, priced_legs=priced_legs)


def price_candidates(
    candidates: list[Itinerary],
    date: str,
    max_workers: int = MAX_CONCURRENT_QUERIES,
) -> list[PricedItinerary]:
    """Price a list of candidate itineraries concurrently."""
    # Ensure FX rates are loaded before spawning workers. If a CLI wrapper
    # already called start_background_refresh() earlier, this just joins
    # the thread; otherwise it kicks off the load now.
    currency.start_background_refresh()
    currency.get_rates()

    cache: dict = {}
    cache_lock = threading.Lock()
    priced: list[PricedItinerary] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(price_itinerary, c, date, cache, cache_lock): c
            for c in candidates
        }
        for future in as_completed(futures):
            priced.append(future.result())

    return priced


# ---------- Ranking ----------

def rank_by_cost(priced: list[PricedItinerary]) -> list[PricedItinerary]:
    return sorted(
        [p for p in priced if p.is_complete],
        key=lambda p: p.total_cost,
    )


def rank_by_duration(priced: list[PricedItinerary]) -> list[PricedItinerary]:
    return sorted(
        [p for p in priced if p.is_complete],
        key=lambda p: p.total_duration_min,
    )


# ---------- Pretty-printing ----------

def format_results(priced: list[PricedItinerary], top_n: int = 10) -> str:
    """Format ranked itineraries with a 'savings/hr vs fastest' comparison column.

    The savings/hr value answers: 'how much do I save per extra hour of
    travel time, by choosing this option over the fastest one?'

    A positive number = cheaper but slower (the trade-off you'd typically
    take if the rate is high enough to be worth your time).
    A negative number = both more expensive AND slower than the fastest.
    Strictly worse — usually skip.
    """
    complete = [p for p in priced if p.is_complete]
    if not complete:
        return "(no complete pricings)"

    fastest = min(complete, key=lambda p: p.total_duration_min)
    sym = currency.display_symbol()

    header = f"{'#':>3}  {'Cost':>8}  {'Time':>7}  {'savings/hr':>12}  Routing"
    lines = [header, "-" * 90]

    for i, p in enumerate(priced[:top_n], 1):
        cost_str = currency.format_amount(p.total_cost)
        dur_str = p.total_duration_human

        if p is fastest:
            comp_str = "(fastest)"
        else:
            extra_hr = (p.total_duration_min - fastest.total_duration_min) / 60
            cost_diff = fastest.total_cost - p.total_cost   # +ve = this is cheaper
            if extra_hr <= 0:
                comp_str = "—"
            else:
                rate = cost_diff / extra_hr
                sign = "" if rate >= 0 else "-"
                comp_str = f"{sign}{sym}{abs(rate):,.0f}/hr"

        lines.append(f"{i:>3}.  {cost_str:>8}  {dur_str:>7}  {comp_str:>12}  {p.itinerary.describe()}")

    failed = [p for p in priced if not p.is_complete]
    if failed:
        lines.append(f"\n  ({len(failed)} candidates failed pricing — likely no service on one or more legs)")
    return "\n".join(lines)


# ---------- Demo ----------

if __name__ == "__main__":
    from candidates import generate_candidates

    # Kick off FX refresh as early as possible — overlaps with the rest of setup.
    currency.start_background_refresh()

    print(f"Mode: {'MOCK pricing' if USE_MOCK else 'LIVE fli pricing'}")
    print()

    # Brendan's actual painful trip example, replayed.
    origin, destination, date = "DAD", "CKG", "2026-06-15"
    print(f"Searching {origin} -> {destination} on {date}")
    print("=" * 90)

    cands = generate_candidates(origin, destination, max_stops=1, include_train=False)
    priced = price_candidates(cands, date)

    print("\n--- Sorted by cost ---")
    print(format_results(rank_by_cost(priced), top_n=8))
    print("\n--- Sorted by time ---")
    print(format_results(rank_by_duration(priced), top_n=8))

    # Same for CKG -> BKK with train option enabled.
    print()
    origin, destination = "CKG", "BKK"
    print(f"Searching {origin} -> {destination} on {date}  (with train option)")
    print("=" * 90)
    cands = generate_candidates(origin, destination, max_stops=1, include_train=True)
    priced = price_candidates(cands, date)
    print("\n--- Sorted by cost ---")
    print(format_results(rank_by_cost(priced), top_n=10))

    print(f"\n[FX source: {currency.get_source()}]")
