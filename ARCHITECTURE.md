# Architecture

This is the technical companion to `README.md`. It explains how the modules fit together, what each one is responsible for, what the data flow looks like at each step, and where to make changes when the system grows.

This document is meant to evolve. As features are added, update the relevant section rather than tacking on a changelog at the bottom.

---

## 1. System overview

The system answers one question: *"For a given origin, destination, and date, what are my realistic routing options ranked by cost and time?"*

It does this in five stages, with each stage isolated to one module:

```
   ┌─────────────────────────────────────────────────────────────┐
   │                                                             │
   │   USER INPUT:  origin="CKG", destination="VIE",             │
   │                date="2026-09-15", max_stops=1               │
   │                                                             │
   └────────────────────────────┬────────────────────────────────┘
                                │
                                ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  STAGE 1: nodes.py                                           │
   │  Static reference data — airports, train stations, regions. │
   │  Read-only lookup table; no logic.                           │
   └────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  STAGE 2: connections.py                                     │
   │  Static train data — HSR fares/durations from Chongqing.    │
   │  Read-only; no logic.                                        │
   └────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  STAGE 3: candidates.py                                      │
   │  Routing engine — generates candidate Itinerary objects.    │
   │  Pure function: same input always produces same output.     │
   │  No network, no I/O.                                         │
   └────────────────────────────┬─────────────────────────────────┘
                                │
                                │  list[Itinerary]
                                ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  STAGE 4: pricer.py + currency.py                            │
   │  Pricing engine — calls fli for each leg in parallel,       │
   │  converts to display currency, attaches results.             │
   │  Network-bound. Uses caching at multiple levels.             │
   └────────────────────────────┬─────────────────────────────────┘
                                │
                                │  list[PricedItinerary]
                                ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  STAGE 5: pricer.py (formatting)                             │
   │  Ranking and presentation. Sorts by cost/time, computes     │
   │  savings/hr column, formats human-readable output.           │
   └──────────────────────────────────────────────────────────────┘
```

The strict layering matters. Each module only depends on the ones above it. This means:
- You can test `candidates.py` without any network access.
- Swapping the pricer (e.g., adding Kiwi.com) doesn't touch the routing engine.
- Changing the currency provider doesn't touch anything else.

---

## 2. Module-by-module walkthrough

### 2.1 `nodes.py` — the geography

**Responsibility:** Define every location the system knows about. Pure data, no logic.

**Key types:**
```python
@dataclass
class Node:
    code: str           # IATA airport or rail code (e.g., "CKG", "CKG-N")
    name: str           # display name
    city: str
    country: str
    region: str         # one of 7 region constants
    node_type: str      # "airport" | "rail" | "both"
    is_hub: bool        # use as transit point in routing?
    notes: str | None
```

**Key data:**
- `NODES: dict[str, Node]` — master lookup by code.
- Region constants: `CHINA`, `GREATER_CHINA`, `EAST_ASIA`, `SOUTHEAST_ASIA`, `MIDDLE_EAST`, `EUROPE`, `NORTH_AMERICA`.

**Helpers:**
- `get_node(code)` — lookup with KeyError on miss.
- `get_hubs_in_region(region)` — used by candidate generator for transit selection.
- `get_airports_in_region(region)` — same but excludes rail nodes.

**The `is_hub` flag matters.** Some nodes (DAD, possibly future small airports) are valid origins/destinations but not realistic transit points. Marking them `is_hub=False` keeps them out of intermediate-stop generation.

**The `node_type` field matters too.** Rail nodes (`CKG-N`, `HKG-WK`) can't be flown to or from — they only appear as endpoints of train legs. The candidate generator filters on `node_type == "airport"` when picking transit hubs.

**To add a new airport:** Append a new entry to `NODES`. That's it. The candidate generator picks it up automatically based on its region and `is_hub` flag.

### 2.2 `connections.py` — train data

**Responsibility:** Static HSR connection data from Chongqing North.

**Key type:**
```python
@dataclass
class TrainConnection:
    origin: str             # always "CKG-N" currently
    destination: str        # node code (must exist in NODES)
    duration_min: int
    cost_cny_2nd_class: int # CNY, since that's what the source data is in
    frequency: str          # human-readable, for display only
    notes: str
```

**Why this is its own module instead of mixed in with nodes:**
- Trains have different attributes (duration, fare) that flights don't have at this stage.
- The connection set may grow (HSR from other Chinese cities, ferries to Hainan, etc.) and a separate module keeps that growth contained.
- Making rail explicitly separate from "the airports list" reflects that they're different transport modes with different pricing semantics.

**Helpers:**
- `get_train_connections_from(origin)` — used by the candidate generator to enumerate train+fly options.
- `get_train_connection(origin, destination)` — direct lookup if needed.

**To add a new train connection:** Append to `TRAIN_CONNECTIONS` list.

### 2.3 `candidates.py` — the routing engine

**Responsibility:** Given `(origin, destination)`, generate every plausible `Itinerary` to consider.

**Key types:**
```python
@dataclass
class Leg:
    mode: str               # "FLIGHT" | "TRAIN"
    origin: str             # node code
    destination: str        # node code
    duration_min: int | None    # populated for trains; flights filled in by pricer
    cost_cny: int | None        # same
    notes: str

@dataclass
class Itinerary:
    legs: list[Leg]
    # Computed properties: origin, destination, num_stops, hub_codes,
    # has_train_leg, describe()
```

**Main entry point:**
```python
generate_candidates(
    origin_code: str,
    destination_code: str,
    max_stops: int = 1,
    include_train: bool = True,
) -> list[Itinerary]
```

**Algorithm:**
1. Always include the direct flight as candidate #1.
2. Determine *valid transit regions* via the `TRANSIT_REGIONS` lookup (e.g., for CHINA→EUROPE, valid regions are CHINA, GREATER_CHINA, EAST_ASIA, MIDDLE_EAST, EUROPE).
3. Filter `NODES` to airports in those regions, excluding origin and destination — this is the *transit hub set*.
4. For each transit hub, generate a 1-stop itinerary `(origin → hub → destination)`.
5. If `max_stops >= 2`, generate 2-stop itineraries through hub pairs in *different* regions (avoids same-region backtracking).
6. If `origin == "CKG"` and `include_train=True`, for each train connection from CKG-N:
   - Determine the airport to fly out of (using `RAIL_TO_AIRPORT` mapping for rail nodes like HKG-WK → HKG).
   - Generate train + direct flight from that airport.
   - For longhaul destinations (EUROPE, NORTH_AMERICA), also generate train + 1-stop flight options.

**Critical invariant:** The candidate generator is a pure function. Same inputs always produce the same outputs. No I/O, no network, no hidden state. This makes it trivially testable and lets you enumerate routings without burning API calls.

**The `TRANSIT_REGIONS` table is the single most important piece of business logic in the system.** It's what keeps a CKG→VIE search from suggesting routings via Bangkok or Manila. The keys are `frozenset` of region pairs (so `{CHINA, EUROPE}` and `{EUROPE, CHINA}` map to the same entry). When adding new regions or routing patterns, update this table.

**The `RAIL_TO_AIRPORT` mapping bridges rail and air.** When a train arrives at HKG-WK, the next leg has to fly out of HKG (the airport, ~30 min away). The mapping makes this transfer explicit, and the `Itinerary.describe()` method renders it as `(transfer to HKG)`.

### 2.4 `currency.py` — FX rates

**Responsibility:** Provide live FX rates for converting flight prices (USD from fli) and train fares (CNY from connections) into the display currency (CAD by default).

**Three-tier caching:**
1. **In-memory cache** (`_rates_cache`) — populated once, used for the rest of the session.
2. **Disk cache** (`.fx_cache.json`) — survives across runs; valid for `CACHE_TTL_HOURS = 24`.
3. **Bootstrap fallback** (`BOOTSTRAP_RATES`) — last-resort hardcoded values used only when there's no cache file *and* no network. After the first successful run on any machine, this is never consulted again.

**Public API:**
```python
start_background_refresh()   # call early; non-blocking
get_rates() -> dict          # returns rates dict, blocks briefly if needed
usd_to_display(amount)       # USD -> CAD (or whatever DISPLAY_CURRENCY is)
cny_to_display(amount)       # CNY -> CAD
format_amount(value)         # "C$1,234"
get_source()                 # "live" | "disk" | "stale-disk" | "bootstrap"
```

**The background refresh pattern:**

```
program start
     │
     ▼
start_background_refresh()
     │
     ├── disk cache fresh?  ──────► load into memory, return  (fast path, no network)
     │
     └── stale or missing  ──────► spawn daemon thread:
                                     ├── HTTP GET frankfurter.app
                                     ├── write .fx_cache.json
                                     └── populate _rates_cache
                                   (returns immediately to main thread)

(meanwhile: user enters trip, candidates generate, etc.)

get_rates() called later
     │
     ├── _rates_cache populated?  ──► return it
     │
     ├── thread still running?    ──► join with timeout, return
     │
     └── no thread, no cache      ──► sync fetch, then fall through tiers
```

**Why this matters:** The FX call takes ~1 second. Doing it synchronously at startup adds 1 second of dead time. Doing it in the background overlaps it with whatever else is happening (user input, candidate generation), so by the time pricing starts, the rates are already loaded.

**Provider abstraction:** All HTTP logic is contained in `_fetch_rates_from_api()`. To swap providers (e.g., to exchangerate.host or open.er-api.com), edit only that function. The cache, conversion helpers, and module API stay identical.

### 2.5 `pricer.py` — pricing and presentation

**Responsibility:** Take candidate itineraries, fetch real prices for each flight leg, attach them to the itineraries, rank, and format output.

**Key types:**
```python
@dataclass
class PricedLeg:
    leg: Leg
    cost: float | None         # in display currency (CAD)
    duration_min: int | None
    airline: str | None
    error: str | None

@dataclass
class PricedItinerary:
    itinerary: Itinerary
    priced_legs: list[PricedLeg]
    # Computed: total_cost, total_duration_min (incl. transfers),
    # total_duration_human, is_complete
```

**The pricing pipeline:**

```python
def price_candidates(candidates, date, max_workers=6) -> list[PricedItinerary]:
    currency.start_background_refresh()  # idempotent
    currency.get_rates()                  # ensure loaded before threads spawn

    cache = {}  # leg-level cache: {(origin, dest, date): result_payload}

    with ThreadPoolExecutor(max_workers) as pool:
        futures = {pool.submit(price_itinerary, c, date, cache): c
                   for c in candidates}
        for future in as_completed(futures):
            priced.append(future.result())
    return priced
```

**Two levels of caching:**
1. **In-process leg cache** (`cache` dict in `price_candidates`) — within one search, identical legs across different itineraries are only priced once. For a CKG→VIE search with 15 candidates, this typically reduces ~30 leg lookups to ~12 unique calls.
2. **FX rate cache** (handled in `currency.py`) — across all calls in a 24-hour window.

**Mock vs real pricing:**
```python
USE_MOCK = True          # at top of pricer.py
_fli_search = _mock_fli_search if USE_MOCK else _real_fli_search
```

The mock generates synthetic prices using a fabricated distance table. Useful for:
- Testing pipeline changes without burning real API quota.
- Reproducible test data (same query → same result).
- Working offline.

The real pricer (`_real_fli_search`) is the integration point with the [`fli`](https://github.com/punitarani/fli) library. It's marked with a `*** VERIFY ***` comment because the fli API may have shifted since this was written — the import paths, filter class names, and result attribute names all need to be confirmed against current fli docs.

**Transfer time penalties:**

When summing leg durations, `total_duration_min` adds:
- `SAME_AIRPORT_TRANSFER_MIN = 90` minutes when consecutive legs share an airport (e.g., arrive HKG, depart HKG).
- `DIFFERENT_AIRPORT_TRANSFER_MIN = 240` minutes when they don't (e.g., arrive HKG-WK by train, depart HKG by air).

These are deliberate generous estimates — better to overestimate transfer time than have the system suggest a 30-minute international connection.

**Ranking and output:**

Two sort modes (no "balanced" mode — kept simple):
- `rank_by_cost(priced)` — cheapest first.
- `rank_by_duration(priced)` — fastest first.

The `format_results()` function adds a third dimension at presentation time: a **savings/hr** column comparing each option to the fastest. For each option:
- If it's the fastest: print `(fastest)`.
- Otherwise: compute `(fastest_cost - this_cost) / extra_hours_of_travel`.
  - Positive = cheaper but slower (the trade-off you'd take if your time is worth less than that rate).
  - Negative = more expensive AND slower than fastest. Strictly worse.

This lets the user evaluate cost/time tradeoffs without the system imposing a fixed "hour is worth X" rule.

---

## 3. Data flow walkthrough: a real query

Tracing what happens when the user asks for `CKG → BKK on 2026-09-15`:

**1. User input** is passed to `generate_candidates("CKG", "BKK", max_stops=1, include_train=True)`.

**2. `candidates.py`** looks up CKG and BKK in `NODES`. Both have `region` set (CHINA, SOUTHEAST_ASIA). It looks up `frozenset({"CHINA", "SOUTHEAST_ASIA"})` in `TRANSIT_REGIONS` and gets `{CHINA, GREATER_CHINA, SOUTHEAST_ASIA}`. It filters `NODES` to airport-type hub nodes in those regions, minus CKG and BKK. Result: ~10 transit hubs (CTU, PEK, PVG, CAN, SZX, KMG, HKG, TPE, SGN, HAN, etc.).

**3.** It builds:
   - 1 direct flight itinerary
   - 10 one-stop itineraries (CKG → hub → BKK for each hub)
   - Train connections from CKG-N (8 of them), each generating a "train + fly from hub airport to BKK" option

   Total: ~19 candidate `Itinerary` objects, each a list of `Leg`s.

**4.** Caller invokes `price_candidates(candidates, "2026-09-15")`.

**5. `pricer.py`** calls `currency.start_background_refresh()` (loads disk cache or kicks off network fetch), then `currency.get_rates()` (waits for it if needed). Now FX rates are guaranteed loaded.

**6.** It spawns up to 6 worker threads, each handling one `Itinerary`. For each itinerary:
   - For each `Leg`:
     - If `mode == TRAIN`: convert `cost_cny` to CAD via `currency.cny_to_display()`. No network call.
     - If `mode == FLIGHT`: check the leg-level cache. If miss, call `_fli_search(origin, dest, date)`. Convert USD result to CAD. Store in cache.
   - Wrap each `Leg` in a `PricedLeg`. Wrap the whole itinerary in a `PricedItinerary`.

**7.** All futures complete. Results are returned as `list[PricedItinerary]`.

**8.** Caller chooses a sort:
   - `rank_by_cost(priced)` → sorted ascending by `total_cost`.
   - `rank_by_duration(priced)` → sorted ascending by `total_duration_min`.

**9. `format_results()`** produces the human-readable table with the savings/hr column.

**Total network calls** for a 19-candidate search: 1 FX call (skipped if cached) + ~12-15 fli calls (deduplicated by leg cache).

---

## 4. Where to make changes

| To do this... | ...edit this. |
|---|---|
| Add an airport | `nodes.py` → append to `NODES` |
| Add a train route | `connections.py` → append to `TRAIN_CONNECTIONS` |
| Allow new region pair as transit | `candidates.py` → add to `TRANSIT_REGIONS` |
| Add rail-to-airport bridge | `candidates.py` → add to `RAIL_TO_AIRPORT` |
| Change display currency | `currency.py` → set `DISPLAY_CURRENCY` |
| Change FX provider | `currency.py` → edit `_fetch_rates_from_api()` only |
| Switch mock ↔ real pricing | `pricer.py` → set `USE_MOCK` |
| Update fli library integration | `pricer.py` → edit `_real_fli_search()` only |
| Adjust transfer time assumptions | `pricer.py` → `SAME_/DIFFERENT_AIRPORT_TRANSFER_MIN` |
| Change concurrency level | `pricer.py` → `MAX_CONCURRENT_QUERIES` |
| Tweak the output format | `pricer.py` → `format_results()` |

---

## 5. Future architecture: planned features

This section describes how planned features would slot into the existing architecture. Update as features ship.

### 5.1 Date flexibility (planned)

**Goal:** Search a range of dates and find the cheapest combinations, instead of being locked to one date.

**API design:**
```python
# Single date (current):
generate_candidates("CKG", "VIE", max_stops=1)
price_candidates(cands, date="2026-09-15")

# Date range (planned):
price_candidates(cands, date_range=("2026-09-12", "2026-09-18"))
# Returns: list[PricedItinerary] where each carries the actual date used

# Round-trip with both windows flexible (planned):
search_round_trip(
    "CKG", "VIE",
    outbound_window=("2026-09-12", "2026-09-18"),
    return_window=("2026-09-22", "2026-09-28"),
)
```

**Implementation strategy:**

The `fli` library has a `search_dates` function specifically for this — it returns the cheapest date for a given origin/destination over a window, with one API call per window (much cheaper than 7 calls for 7 dates).

Add to `pricer.py`:
```python
def _real_fli_search_range(origin, dest, date_from, date_to) -> list[dict]:
    """Returns [{"date": "2026-09-13", "price_usd": 540, ...}, ...]"""
```

The pricing pipeline gains a new mode:
- For each candidate `Itinerary`, instead of calling `_fli_search` once with a single date, call `_fli_search_range` once per leg over the window, then **combinatorially explore date combinations** that are valid (each leg's date >= previous leg's date + 1 day, e.g.).
- For multi-leg itineraries, this gets combinatorially expensive — need a heuristic. One approach: pick the cheapest date for each leg independently, then verify the combination is feasible (departure dates are monotonic). If not, fall back to constrained optimization.

**Simpler MVP:** Just iterate dates in the window, run the existing single-date pricer for each, return the cheapest result per itinerary. More API calls but trivial to implement. Optimize later if quota becomes a problem.

**New data type:**
```python
@dataclass
class DatedItinerary:
    itinerary: Itinerary
    leg_dates: list[str]   # one date per leg
```

**Output change:** Format results to show the *date* of each option, not just origin/destination.

**Scope of changes:**
- `pricer.py` — new `price_candidates_in_range()` function alongside `price_candidates()`.
- No changes to `nodes.py`, `connections.py`, `candidates.py`, `currency.py`.

### 5.2 CLI (planned)

A `cli.py` that accepts arguments and runs the full pipeline:
```bash
python -m flight_router CKG VIE 2026-09-15
python -m flight_router CKG VIE 2026-09-15 --max-stops 2 --train
python -m flight_router CKG VIE --depart 2026-09-12:18 --return 2026-09-22:28
```

Should call `currency.start_background_refresh()` immediately on startup so the FX fetch overlaps with argument parsing.

### 5.3 Kiwi.com / self-transfer pricer (planned)

Adds a second pricer alongside fli for itineraries Google Flights won't combine.

**Architectural pattern:** Define a `Pricer` protocol:
```python
class Pricer(Protocol):
    def price_leg(self, origin, dest, date) -> PricedLeg: ...
```

Then the pricing engine can hold a list of pricers and use whichever returns a result (or compares them).

Currently this is implicit (only fli). Making it explicit before adding a second source keeps things clean.

### 5.4 Layover quality scoring (planned)

A hub's "transit-friendliness" depends on:
- Visa requirements (less relevant given CA + UK passports + China visa).
- Airport quality and ease of transit.
- Whether the layover is long enough to leave the airport.

Could be added as `transit_score: float` on `Node` in `nodes.py`, then incorporated into ranking as an optional bonus/penalty. Out of scope for v1.

### 5.5 Smarter 2-stop filter (planned)

Currently 2-stop generation produces too many candidates (~600 for CHINA→EUROPE). A smart filter would require routings to progress geographically:

```
CKG (CHINA) → DOH (MIDDLE_EAST) → VIE (EUROPE)   ← OK, regions progress
CKG (CHINA) → ICN (EAST_ASIA)   → VIE (EUROPE)   ← OK
CKG (CHINA) → CAN (CHINA)       → VIE (EUROPE)   ← reject, same region
CKG (CHINA) → DOH (MIDDLE_EAST) → ICN (EAST_ASIA) → VIE   ← reject, backtrack
```

Implementation: ordering of regions per route corridor. Add to `TRANSIT_REGIONS` table or as a separate region-distance lookup.

---

## 6. Testing strategy (TBD)

Currently testing is by running the demo blocks in `__main__`. As the system grows, formal tests should target:

- **`candidates.py`** — pure function, easy to unit-test. Snapshot test: "given CKG → VIE max_stops=1, expect this exact list of 18 candidates."
- **`currency.py`** — mock the HTTP call, test cache freshness logic and fallback tiers.
- **`pricer.py`** — use `USE_MOCK = True` for integration tests. Verify: leg cache deduplication, transfer time math, savings/hr calculation correctness.

Out of scope for v1; revisit when the system has 2+ users or the cost of breakage rises.

---

## 7. Open questions and design decisions to revisit

- **Train data accuracy.** Hardcoded fares will drift over time. Should the `notes` field carry a "last verified" date? Should there be an annual review prompt?
- **Currency rounding.** Currently rounds to whole units. For low-cost intra-Asia routes priced in CAD, this is fine. For very expensive trips this could lose precision.
- **Transfer time policy.** 90 min same-airport / 240 min different-airport are guesses. Should be calibrated against real connection minimums per airline alliance.
- **Mock pricer realism.** The synthetic pricing uses a baseline of $0.10/km, which is reasonable on average but doesn't reflect that long-haul is cheaper per km than short-haul. For a more realistic mock, use a curve (e.g., $0.15/km for <1500km, $0.10/km for 1500-5000km, $0.08/km for >5000km).
