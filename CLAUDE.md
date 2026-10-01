# CLAUDE.md

Project brief — auto-loaded by Claude Code when working in this repo.

## What this is

`flight-router` is a personal flight search tool. It generates candidate routings between two airports (direct, 1-stop, 2-stop, train+fly from Chongqing), prices each leg via Google Flights through the [`fli`](https://github.com/punitarani/fli) library, and presents ranked options with cost/time tradeoffs.

The point is to automate the manual work of comparing multi-hop options that Google Flights doesn't surface together. Typical query: "I'm in CKG, need to get to VIE in late September — what are my options?"

## Status

**v1 complete with caveats.** Five-module pipeline runs end-to-end against the live `fli` (Google Flights) library. CLI available as `python cli.py CKG VIE 2026-09-15`. Test suite is 61 tests covering candidate generation, connections data, types, currency conversion, end-to-end mock pricing, CLI argument parsing, and the browser fallback pricer.

**Caveat — fli library has a price-parsing bug** for many intra-China and China-exit legs (SGN→CKG, HAN→CKG, HKG→CKG when on CNY-priced carriers). Fli returns `price=0.0` for these, which we now defensively treat as "no valid result" so the leg is marked unpriceable and the itinerary is excluded from rankings. This is the right safety choice — better to surface fewer options correctly than many options wrongly — but it means routings through certain Vietnamese and Chinese hubs disappear from results entirely. The user's primary use case (CKG → EUROPE via Middle East / East Asia hubs) is unaffected.

**Caveat — fli returns prices in arbitrary currencies** depending on Google Flights' geolocation guess (commonly JPY for Asian queries, sometimes USD or CNY). The pricer normalises via `currency.convert_to_display(amount, from_ccy)`, anchored on USD via Frankfurter rates with disk caching.

## Modules

```
nodes.py         airports + train stations as routing nodes
connections.py   HSR connections from CKG-N
candidates.py    routing engine (pure function, no I/O)
pricer.py        calls fli per leg, ranks results
browser_pricer.py  Playwright fallback when fli returns price=0
currency.py      24hr FX cache with background refresh
```

Read `ARCHITECTURE.md` for the full layered explanation. Read `README.md` for usage.

## Immediate next steps

1. **Build a GUI.** Terminal-only is not the destination — the tool is meant to be used regularly, and the CLI is a stopgap. Likely shape: a small local web UI (Flask/FastAPI + a single HTML page) so the search form, results table, and the savings/hr explanation are all rendered properly. The existing `cli.py` becomes one of two front-ends to the same pipeline; the core (`generate_candidates → price_candidates → format_results`) stays unchanged.
2. Patch fli's price parser upstream (or fork) so the intra-China zero-price bug doesn't drop options. (Workaround in place: `browser_pricer.py`. Not yet verified against live Google Flights — run `python browser_pricer.py HKG CKG <date>` from a normal network to confirm.) The price block lives in a protobuf field that fli's `_parse_price_info` doesn't currently decode for CNY-denominated results.
3. Add date-range search using `fli.search_dates` — see ARCHITECTURE.md §5.1 for the design. Major win for flexible travel.
4. Consider Kiwi.com integration (ARCHITECTURE.md §5.3) for self-transfer routings — would also work around the fli zero-price issue by providing a second price source.
5. Rate-limiting: rapid-fire queries against fli return HTTP 429s. The pricer concurrency is set to 6 workers, which seems to be near the threshold. Add backoff/retry if results consistently show "no complete pricings."

## Conventions

- **Display currency is CAD.** Train fares are stored in CNY in `connections.py` (source-of-truth) and converted at display time.
- **Strict module layering.** `pricer.py` imports from `candidates.py` imports from `nodes.py` + `connections.py`. Don't introduce upward dependencies.
- **Mock first, then live.** `pricer.py` has `USE_MOCK = True` by default. Always test changes against the mock before touching live API.
- **Pure-function discipline in `candidates.py`.** Same input → same output, no network, no hidden state. Don't break this.
- **Cache aggressively.** Leg-level cache during a search, FX cache for 24hr, disk persistence between runs. Adding a new external call? Add a cache.

## Watch out for

- **fli zero-price gotcha.** fli's `_parse_price_info` returns `price=0.0` for many intra-China and China-exit legs (SGN→CKG, HAN→CKG, HKG→CKG when CNY-priced). When fli reports zero, `pricer._real_fli_search` hands the leg to `browser_pricer.search`, which reads the rendered Google Flights page (cheapest nonstop on that date). If that also finds nothing (or Playwright isn't installed, or `USE_BROWSER_FALLBACK = False`), the leg surfaces as "no flights found" rather than as a silent C$0 contribution. The browser parser depends on Google's result-row `aria-label` wording ("From 271 US dollars. Nonstop flight with … Total duration 2 hr. Select flight") — if fallback prices stop appearing, check that wording first.
- **fli rate limiting.** Repeated rapid queries against fli return HTTP 429. With `MAX_CONCURRENT_QUERIES = 6` in pricer.py and ~20-30 candidates per search, you can hit limits during heavy testing. Wait a few minutes between probe runs.
- **fli currency drift.** fli returns prices in whatever currency Google Flights serves (often JPY due to IP geolocation). The pricer uses `currency.convert_to_display(price, native_ccy)` to normalise. If a price looks ~150x off, the source currency wasn't recognised — check `currency.TRACKED_CURRENCIES`.
- **2-stop candidate explosion.** `max_stops=2` produces ~600 candidates for CHINA→EUROPE pairs. Default to `max_stops=1` and only escalate when needed.
- **Train data is hardcoded.** Always verify on Trip.com or 12306 before booking a train leg the system suggests.

## What this isn't (yet)

Not a route DB, not a flight aggregator, not a booking system. It plans candidate routings and shows comparative prices. Booking happens manually after you decide.
