# CLAUDE.md

Project brief — auto-loaded by Claude Code when working in this repo.

## What this is

`flight-router` is a personal flight search tool. It generates candidate routings between two airports (direct, 1-stop, 2-stop, train+fly from Chongqing), prices each leg via Google Flights through the [`fli`](https://github.com/punitarani/fli) library, and presents ranked options with cost/time tradeoffs.

The point is to automate the manual work of comparing multi-hop options that Google Flights doesn't surface together. Typical query: "I'm in CKG, need to get to VIE in late September — what are my options?"

## Status

**v1 working.** Five-module pipeline is in place and runs end-to-end against a mock pricer. Live `fli` integration is sketched but not yet verified — the `_real_fli_search()` function in `pricer.py` is a best-guess against fli's API and needs to be tested against current docs before flipping `USE_MOCK = False`.

Display currency is CAD with live FX from Frankfurter, cached to disk for 24hr.

## Modules

```
nodes.py         airports + train stations as routing nodes
connections.py   HSR connections from CKG-N
candidates.py    routing engine (pure function, no I/O)
pricer.py        calls fli per leg, ranks results
currency.py      24hr FX cache with background refresh
```

Read `ARCHITECTURE.md` for the full layered explanation. Read `README.md` for usage.

## Immediate next steps

1. Verify and wire up live fli (test `_real_fli_search()` signature against current fli library, flip `USE_MOCK = False`).
2. Build `cli.py` so this is runnable as `python -m flight_router CKG VIE 2026-09-15`.
3. Add date-range search using `fli.search_dates` — see ARCHITECTURE.md §5.1 for the design.

## Conventions

- **Display currency is CAD.** Train fares are stored in CNY in `connections.py` (source-of-truth) and converted at display time.
- **Strict module layering.** `pricer.py` imports from `candidates.py` imports from `nodes.py` + `connections.py`. Don't introduce upward dependencies.
- **Mock first, then live.** `pricer.py` has `USE_MOCK = True` by default. Always test changes against the mock before touching live API.
- **Pure-function discipline in `candidates.py`.** Same input → same output, no network, no hidden state. Don't break this.
- **Cache aggressively.** Leg-level cache during a search, FX cache for 24hr, disk persistence between runs. Adding a new external call? Add a cache.

## Watch out for

- **fli API drift.** It's a reverse-engineered Google Flights wrapper. Imports and types in `_real_fli_search()` may need updating against the current fli release.
- **2-stop candidate explosion.** `max_stops=2` produces ~600 candidates for CHINA→EUROPE pairs. Default to `max_stops=1` and only escalate when needed.
- **Train data is hardcoded.** Always verify on Trip.com or 12306 before booking a train leg the system suggests.

## What this isn't (yet)

Not a route DB, not a flight aggregator, not a booking system. It plans candidate routings and shows comparative prices. Booking happens manually after you decide.
