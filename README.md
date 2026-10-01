# flight-router

A personal flight search tool that automates the painful manual work of comparing multi-hop routings across hubs. Generates candidate itineraries (including HSR + flight combinations from Chongqing), prices each leg via Google Flights, and presents ranked options with cost-vs-time tradeoffs.

Built around the [`fli`](https://github.com/punitarani/fli) library, which talks directly to the Google Flights API.

## Why this exists

Searching multi-stop routes manually is exhausting. A typical Da Nang → Chongqing trip might involve checking the direct flight, then DAD→HAN→CKG, DAD→HKG→CKG, DAD→SZX→CKG, DAD→SGN→CKG — entering each one separately into Google Flights, comparing, going back, trying again with different dates. Hours of repetitive clicking.

This tool does the same searches automatically. You give it `(origin, destination, date)`; it generates every realistic routing through your relevant hubs, prices them in parallel, and shows you a sorted comparison.

## How it works

```
              ┌──────────────┐
   user ────► │ candidates   │  ── generate possible routings
              └──────┬───────┘     (direct, 1-stop, 2-stop, train+fly)
                     │
                     ▼
              ┌──────────────┐
              │   pricer     │  ── call fli for each flight leg
              └──────┬───────┘     (parallel, with dedup cache)
                     │
                     ▼
              ┌──────────────┐
              │   currency   │  ── convert to CAD using cached FX
              └──────┬───────┘
                     │
                     ▼
              ranked output: cost, time, savings/hr
```

## Project structure

```
flight-router/
├── nodes.py         airports + train stations as routing nodes
├── connections.py   HSR connections from Chongqing
├── candidates.py    routing engine — generates candidate itineraries
├── pricer.py        calls fli for each leg, ranks results
├── browser_pricer.py  backup pricer: reads Google Flights in a headless browser when fli reports C$0
├── currency.py      live FX rates with 24hr disk cache
└── cli.py           terminal entry point (python cli.py CKG VIE 2026-09-15)
```

### `nodes.py`

A curated list of ~35 airports plus a few train stations, organized by region. Each `Node` has a code (IATA or rail code), city, country, region, type (`airport` / `rail` / `both`), and an `is_hub` flag controlling whether it's used as a transit point.

Coverage is intentional, not exhaustive:
- **China**: CKG (home), CTU, PEK, PKX, PVG, SHA, CAN, SZX, KMG, XIY, XMN
- **Greater China**: HKG, TPE, plus HKG-WK rail station and CKG-N rail station
- **East Asia**: ICN, NRT, HND
- **Southeast Asia**: BKK, SIN, KUL, MNL, SGN, HAN, DAD
- **Middle East**: DOH, DXB, AUH, IST
- **Europe**: LHR, CDG, FRA, AMS, MUC, VIE
- **North America**: YVR, YYZ, YEG, SEA, SFO, LAX, ORD

Add more nodes as travel needs grow.

### `connections.py`

Models high-speed rail connections from Chongqing North (CKG-N) to other Chinese cities and Hong Kong. Each `TrainConnection` has duration, rough 2nd-class fare in CNY, and frequency notes.

Train data is hardcoded because:
1. The numbers are stable enough for *comparison* — you'll book real tickets on Trip.com or 12306 anyway.
2. There's no public free API for Chinese rail.
3. A handful of connections is enough; expanding the model would be premature.

### `candidates.py`

The routing engine. Given an origin/destination pair, it generates:

1. **Direct flight** — always.
2. **1-stop flights** — through every hub in a *geographically valid transit region* for that origin/destination pair (e.g., for CKG→VIE, valid transit regions are East Asia, Middle East, Europe — not Southeast Asia).
3. **2-stop flights** — optional (`max_stops=2`), filtered to avoid same-region backtracking.
4. **Train + flight** — when origin is CKG, every viable HSR-then-fly option, with rail-to-airport transfers automatically flagged (e.g., HKG-WK → HKG).

The `TRANSIT_REGIONS` lookup table encodes geographic sanity rules. Without it, every search would return nonsense like "CKG → LHR via BKK and DOH and YYZ."

### `pricer.py`

Takes candidate itineraries and prices them. Key features:

- **Parallel pricing** via `ThreadPoolExecutor` (default 6 workers). Flight pricing is I/O-bound on Google's servers — threads help a lot.
- **Leg-level cache** — when 24 candidates share legs (e.g., every "via HKG" routing has the same HKG→destination flight), each unique leg is only priced once.
- **Mock mode** — `USE_MOCK = True` runs against a synthetic pricer based on great-circle distance. Lets the whole pipeline be tested before wiring in fli. Set to `False` for live data.
- **Browser fallback** — when fli reports a zero price (its CNY parsing bug), `browser_pricer.py` opens the Google Flights results page in headless Chromium and reads the cheapest nonstop price from the page. Results are disk-cached for 6 hours in `.browser_price_cache.json`. Turn off with `USE_BROWSER_FALLBACK = False`.
- **Train legs** are priced from the static fares in `connections.py`, converted to display currency at runtime.
- **Rankings**: `rank_by_cost()` and `rank_by_duration()`. The output table shows cost, time, and a "savings/hr vs fastest" comparison column to let you see the cost/time tradeoff explicitly.

### `currency.py`

Handles live FX rates with three guarantees:

1. **One network call per 24 hours.** Rates are cached to `.fx_cache.json` next to the module.
2. **Non-blocking refresh.** `start_background_refresh()` spawns a daemon thread that fetches rates in parallel with whatever else the program is doing (e.g., user entering trip details, candidate generation).
3. **Graceful degradation.** Disk cache → stale disk → hardcoded bootstrap. Always returns *something*, even fully offline.

Provider: [Frankfurter](https://www.frankfurter.app/) (free, no key, ECB-sourced). Swap providers by editing `_fetch_rates_from_api()` only.

Display currency is set by `DISPLAY_CURRENCY = "CAD"` at the top of the module. Change to `"USD"`, `"CNY"`, `"EUR"`, or `"GBP"` to switch.

## Reading the output

```
  #      Cost     Time    savings/hr   Routing
  1.    C$225    4h21m      C$22/hr    DAD → HAN → CKG
  2.    C$258    2h52m    (fastest)    DAD → CKG
  3.    C$260    5h01m       -C$1/hr   DAD → HKG → CKG
  4.    C$354    5h37m      -C$35/hr   DAD → SGN → CKG
```

The **savings/hr** column compares each option to the fastest one:

- **Positive** = cheaper but slower. The number is what each extra hour of travel "earns" you in savings. If your time is worth less than that rate, take the slower option.
- **`(fastest)`** = the time anchor.
- **Negative** = both more expensive AND slower than the fastest. Strictly worse — skip.

Sort views: cost-ascending and duration-ascending. Pick whichever matches what you're optimizing for.

## Setup

Requires Python 3.10+.

```bash
cd flight-router
pip install -r requirements.txt
playwright install chromium   # one-time browser download for the fallback pricer
```

Playwright is optional: without it, legs fli can't price are simply reported as "no flights found", same as before. Check the fallback on its own with `python browser_pricer.py HKG CKG 2026-11-15`.

Add a `.gitignore` with:
```
.fx_cache.json
__pycache__/
*.pyc
```

To switch from mock to live pricing, open `pricer.py` and set:
```python
USE_MOCK = False
```

The `_real_fli_search()` function in `pricer.py` is a best-guess implementation based on the fli library's interface. **Verify it against [the current fli docs](https://github.com/punitarani/fli) before trusting it** — the import paths, filter class names, and result attributes may have changed since this was written.

## Usage

Run the demo:
```bash
python pricer.py
```

Or call from your own code:
```python
from candidates import generate_candidates
from pricer import price_candidates, rank_by_cost, format_results
import currency

currency.start_background_refresh()  # kick off FX fetch early

cands = generate_candidates("CKG", "VIE", max_stops=1, include_train=True)
priced = price_candidates(cands, date="2026-09-15")
print(format_results(rank_by_cost(priced), top_n=10))
```

## Design choices worth knowing

**Why curated hubs instead of a full route database?**
A hand-picked list of ~35 hubs covers 95%+ of realistic routings for the actual travel patterns this tool serves (Asia-internal, Asia↔Canada, occasional EU). A real route DB (OpenFlights, Aviationstack, Cirium) would add complexity and either staleness or cost without meaningful improvement in coverage.

**Why no 2-stop flights by default?**
Two-stop generation produces `n_hubs × (n_hubs - 1)` combinations, which for 30 hubs is ~870 candidates. Pricing all of them is slow and most are nonsense. 1-stop coverage is sufficient for the vast majority of trips. Pass `max_stops=2` only when you genuinely need it.

**Why train only from CKG?**
Mode-mixing on the first leg only is the realistic case — you wouldn't take a train mid-trip internationally. And HSR is only competitive with flying when starting from a city like Chongqing where the rail network reaches multiple international hubs faster than driving to a domestic flight would.

**Why mock mode?**
Lets the whole pipeline be developed and tested without live API dependency. The `fli` library's interface can shift; the rest of the code shouldn't.

## Limitations and known gaps

- **No self-transfer detection.** Itineraries Google Flights won't combine (e.g., separately ticketed VietJet + China domestic). For those, supplement with [Kiwi.com](https://tequila.kiwi.com/) — could be added as a second pricer in the future.
- **Chinese carrier fares.** Trip.com / Ctrip sometimes shows fares Google misses, especially in CNY for domestic carriers. Worth a manual sanity check on legs involving Spring, 9 Air, Loong Air, Ruili.
- **Train data is approximate.** Always verify on Trip.com or 12306 before booking.
- **No date flexibility.** This searches one date at a time. The fli library supports flexible-date search via `search_dates`; not yet wired in here.
- **No layover quality info.** A 2-hour layover and a 14-hour layover are treated the same in ranking. Future: penalty/bonus based on transfer duration.

## Future additions

- **GUI** — a small local web UI (Flask/FastAPI + one HTML page) so searches and results don't live in the terminal. The CLI stays as a second front-end to the same pipeline; nothing in the core changes.
- **Date-range search** — accept a window (e.g., "depart Sep 12–18, return Sep 22–28") and use `fli.search_dates` to find the cheapest date pairings before pricing routings. Major win for flexible travel.
- Kiwi.com integration for self-transfer routings
- Transit-friendliness scoring per hub (visa, airport quality, layover utility)
- Smarter 2-stop filter (require progressively-closer regions to destination)
- Reasonable-routing filter using great-circle distance
