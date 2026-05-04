# flight-router v1 — Finish & Wire Up Live fli — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the two missing modules (`connections.py`, `candidates.py`), verify the `fli` library API matches `_real_fli_search()`, flip `USE_MOCK = False`, and confirm the live pipeline returns plausible prices for a real query.

**Architecture:** Strict module layering — `nodes` ▸ `connections` ▸ `candidates` ▸ `pricer + currency`. Three of the five modules already exist and define contracts the new modules must satisfy. The pricer imports `FLIGHT, TRAIN, Itinerary, Leg` from `candidates` and uses `leg.mode`, `leg.origin`, `leg.destination`, `leg.cost_cny`, `leg.duration_min`, `itin.legs`, `itin.describe()`. The fli call in `_real_fli_search()` is a best-guess that needs to be confirmed against the installed `flights==0.8.4` package.

**Tech Stack:** Python 3.10+ (existing venv runs 3.14.3), `flights` package (the fli library on PyPI), `pytest` for tests, stdlib only otherwise.

**Working directory:** `/Users/bsingbeil/Sites/flight-router/`. Activate the existing venv with `source .venv/bin/activate` before running anything.

**Out of scope (defer to a follow-up plan):** date-range search via `fli.search_dates`, Kiwi.com integration, layover scoring, smarter 2-stop filter.

---

## Pre-flight checklist (do once, at the start)

- [ ] **Step P1: Confirm working directory and venv**

```bash
cd /Users/bsingbeil/Sites/flight-router
source .venv/bin/activate
python --version
pip list | grep -iE "flights|pytest"
```

Expected: Python 3.14.3; `flights 0.8.4` present; `pytest` may or may not be present yet.

- [ ] **Step P2: Initialize git if not already a repo**

```bash
git rev-parse --is-inside-work-tree 2>/dev/null || git init
git status
```

Expected: either confirmation of an existing repo, or `Initialized empty Git repository`.

- [ ] **Step P3: Add a `.gitignore` (idempotent — only add missing lines)**

If `.gitignore` doesn't exist, create it with:

```gitignore
.venv/
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.fx_cache.json
*.preview.html
docs/superpowers/plans/.history/
```

- [ ] **Step P4: Confirm pricer's mock pipeline currently fails (because candidates.py is missing)**

```bash
python -c "import pricer" 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'candidates'` — confirms the gap.

- [ ] **Step P5: Initial commit of the existing scaffolding**

```bash
git add .gitignore nodes.py currency.py pricer.py requirements.txt CLAUDE.md README.md ARCHITECTURE.md
git commit -m "chore: initial scaffolding for flight-router v1"
```

(Skip this step if the repo already has commits and these files are tracked. Do NOT `git add .` — the `.preview.html` and `docs/` files may already be present.)

---

## Task 1: Tooling — add pytest, create test scaffolding

**Files:**
- Modify: `requirements.txt`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1.1: Update requirements.txt**

Replace the current single line with:

```
flights==0.8.4
pytest>=8.0
```

- [ ] **Step 1.2: Install pytest**

```bash
pip install pytest>=8.0
pytest --version
```

Expected: `pytest 8.x.x`.

- [ ] **Step 1.3: Create `tests/__init__.py` (empty file)**

```bash
mkdir -p tests
touch tests/__init__.py
```

- [ ] **Step 1.4: Create `tests/conftest.py`**

```python
"""Pytest configuration — ensures the project root is importable."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
```

- [ ] **Step 1.5: Smoke-test pytest discovery**

```bash
pytest --collect-only -q
```

Expected: `no tests collected` (this is fine — directory exists and is discoverable).

- [ ] **Step 1.6: Commit**

```bash
git add requirements.txt tests/__init__.py tests/conftest.py
git commit -m "chore: add pytest and tests scaffolding"
```

---

## Task 2: `connections.py` — TrainConnection dataclass + helpers

**Files:**
- Create: `tests/test_connections.py`
- Create: `connections.py`

- [ ] **Step 2.1: Write the failing test**

`tests/test_connections.py`:

```python
"""Contract tests for connections.py."""
import pytest

from connections import (
    TrainConnection, TRAIN_CONNECTIONS,
    get_train_connections_from, get_train_connection,
)
from nodes import NODES


def test_traintconnection_is_dataclass():
    tc = TrainConnection(
        origin="CKG-N", destination="CTU",
        duration_min=75, cost_cny_2nd_class=153,
        frequency="every 30min", notes="ok",
    )
    assert tc.origin == "CKG-N"
    assert tc.cost_cny_2nd_class == 153


def test_train_connections_is_a_list_of_train_connection():
    assert isinstance(TRAIN_CONNECTIONS, list)
    assert len(TRAIN_CONNECTIONS) >= 1
    assert all(isinstance(t, TrainConnection) for t in TRAIN_CONNECTIONS)


def test_every_endpoint_exists_in_nodes():
    """Every origin and destination must be a known node."""
    for tc in TRAIN_CONNECTIONS:
        assert tc.origin in NODES, f"unknown origin: {tc.origin}"
        assert tc.destination in NODES, f"unknown destination: {tc.destination}"


def test_get_train_connections_from():
    conns = get_train_connections_from("CKG-N")
    assert all(c.origin == "CKG-N" for c in conns)
    assert len(conns) >= 1


def test_get_train_connections_from_unknown_origin():
    assert get_train_connections_from("ZZZ") == []


def test_get_train_connection_specific():
    """If a CKG-N → CTU connection exists, lookup must find it."""
    direct = next(
        (c for c in TRAIN_CONNECTIONS
         if c.origin == "CKG-N" and c.destination == "CTU"),
        None,
    )
    if direct is not None:
        found = get_train_connection("CKG-N", "CTU")
        assert found is direct


def test_get_train_connection_missing_returns_none():
    assert get_train_connection("CKG-N", "ZZZ") is None
```

- [ ] **Step 2.2: Run the tests, verify they fail**

```bash
pytest tests/test_connections.py -v
```

Expected: `ModuleNotFoundError: No module named 'connections'`.

- [ ] **Step 2.3: Implement `connections.py`**

```python
"""
connections.py — high-speed rail connections useful for first-leg routing.

Currently models HSR from Chongqing North (CKG-N). Train fares are stored in
CNY since that's the source-of-truth currency; pricer.py converts to display
currency at runtime.

Numbers are *approximations* sufficient for cost/time *comparison* against
flight options. Always verify on Trip.com or 12306 before booking.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class TrainConnection:
    origin: str               # node code (must exist in NODES)
    destination: str          # node code (must exist in NODES)
    duration_min: int
    cost_cny_2nd_class: int   # CNY, source-of-truth
    frequency: str            # human-readable, for display only
    notes: str = ""


# Hardcoded HSR options out of CKG-N. Approximate 2nd-class hard-seat fares
# and durations. Verify on Trip.com / 12306 before booking.
TRAIN_CONNECTIONS: list[TrainConnection] = [
    TrainConnection(
        origin="CKG-N", destination="CTU",
        duration_min=75, cost_cny_2nd_class=153,
        frequency="every 20–30min, 06:00–22:30",
        notes="Frequent. Easiest CKG → Chengdu transit option.",
    ),
    TrainConnection(
        origin="CKG-N", destination="XIY",
        duration_min=300, cost_cny_2nd_class=340,
        frequency="hourly daytime",
        notes="Useful for connecting to north-China flights via XIY.",
    ),
    TrainConnection(
        origin="CKG-N", destination="CAN",
        duration_min=420, cost_cny_2nd_class=640,
        frequency="several daily",
        notes="Long ride; only worth it for cheap CAN-based long-haul.",
    ),
    TrainConnection(
        origin="CKG-N", destination="SZX",
        duration_min=450, cost_cny_2nd_class=695,
        frequency="several daily",
        notes="Long ride; SZX has decent SE-Asia + domestic options.",
    ),
    TrainConnection(
        origin="CKG-N", destination="HKG-WK",
        duration_min=480, cost_cny_2nd_class=870,
        frequency="1–2 direct daily; otherwise via SZX",
        notes="Train arrives at West Kowloon; ~30–40min to HKG airport.",
    ),
    TrainConnection(
        origin="CKG-N", destination="KMG",
        duration_min=300, cost_cny_2nd_class=330,
        frequency="several daily",
        notes="Useful for KMG-based SE-Asia routes.",
    ),
    TrainConnection(
        origin="CKG-N", destination="PEK",
        duration_min=720, cost_cny_2nd_class=880,
        frequency="overnight + one daytime",
        notes="Long; sleeper options exist.",
    ),
    TrainConnection(
        origin="CKG-N", destination="PVG",
        duration_min=600, cost_cny_2nd_class=830,
        frequency="several daily",
        notes="Long ride; PVG has the widest international network.",
    ),
]


# ---------- Helpers ----------

def get_train_connections_from(origin: str) -> list[TrainConnection]:
    """All TrainConnection entries with the given origin code."""
    return [c for c in TRAIN_CONNECTIONS if c.origin == origin]


def get_train_connection(origin: str, destination: str) -> Optional[TrainConnection]:
    """Direct lookup. None if not found."""
    for c in TRAIN_CONNECTIONS:
        if c.origin == origin and c.destination == destination:
            return c
    return None
```

- [ ] **Step 2.4: Run tests, verify they pass**

```bash
pytest tests/test_connections.py -v
```

Expected: 7 passed.

- [ ] **Step 2.5: Commit**

```bash
git add connections.py tests/test_connections.py
git commit -m "feat: add connections.py with HSR routes from CKG-N"
```

---

## Task 3: `candidates.py` — types and FLIGHT/TRAIN constants

**Files:**
- Create: `tests/test_candidates_types.py`
- Create: `candidates.py`

- [ ] **Step 3.1: Write the failing test**

`tests/test_candidates_types.py`:

```python
"""Tests for the basic types in candidates.py — Leg, Itinerary, mode constants."""
import pytest

from candidates import FLIGHT, TRAIN, Leg, Itinerary


def test_mode_constants_are_strings():
    assert FLIGHT == "FLIGHT"
    assert TRAIN == "TRAIN"


def test_leg_dataclass_basic():
    leg = Leg(mode=FLIGHT, origin="CKG", destination="BKK")
    assert leg.mode == FLIGHT
    assert leg.origin == "CKG"
    assert leg.destination == "BKK"
    assert leg.duration_min is None
    assert leg.cost_cny is None
    assert leg.notes == ""


def test_leg_dataclass_with_train_costs():
    leg = Leg(
        mode=TRAIN, origin="CKG-N", destination="CTU",
        duration_min=75, cost_cny=153, notes="HSR",
    )
    assert leg.duration_min == 75
    assert leg.cost_cny == 153


def test_itinerary_origin_and_destination():
    itin = Itinerary(legs=[
        Leg(mode=FLIGHT, origin="CKG", destination="HKG"),
        Leg(mode=FLIGHT, origin="HKG", destination="VIE"),
    ])
    assert itin.origin == "CKG"
    assert itin.destination == "VIE"


def test_itinerary_num_stops_zero_for_direct():
    itin = Itinerary(legs=[Leg(mode=FLIGHT, origin="CKG", destination="BKK")])
    assert itin.num_stops == 0


def test_itinerary_num_stops_one_for_one_stop():
    itin = Itinerary(legs=[
        Leg(mode=FLIGHT, origin="CKG", destination="HKG"),
        Leg(mode=FLIGHT, origin="HKG", destination="VIE"),
    ])
    assert itin.num_stops == 1


def test_itinerary_hub_codes():
    itin = Itinerary(legs=[
        Leg(mode=FLIGHT, origin="CKG", destination="HKG"),
        Leg(mode=FLIGHT, origin="HKG", destination="VIE"),
    ])
    assert itin.hub_codes == ["HKG"]


def test_itinerary_has_train_leg():
    train_itin = Itinerary(legs=[
        Leg(mode=TRAIN, origin="CKG-N", destination="HKG-WK"),
        Leg(mode=FLIGHT, origin="HKG", destination="VIE"),
    ])
    flight_itin = Itinerary(legs=[Leg(mode=FLIGHT, origin="CKG", destination="VIE")])
    assert train_itin.has_train_leg is True
    assert flight_itin.has_train_leg is False


def test_itinerary_describe_direct():
    itin = Itinerary(legs=[Leg(mode=FLIGHT, origin="CKG", destination="BKK")])
    assert itin.describe() == "CKG → BKK"


def test_itinerary_describe_one_stop():
    itin = Itinerary(legs=[
        Leg(mode=FLIGHT, origin="CKG", destination="HKG"),
        Leg(mode=FLIGHT, origin="HKG", destination="VIE"),
    ])
    assert itin.describe() == "CKG → HKG → VIE"


def test_itinerary_describe_train_with_transfer():
    """Rail-to-air transfers should be flagged in the description."""
    itin = Itinerary(legs=[
        Leg(mode=TRAIN, origin="CKG-N", destination="HKG-WK"),
        Leg(mode=FLIGHT, origin="HKG", destination="VIE"),
    ])
    desc = itin.describe()
    # Format: "CKG-N ⇒ HKG-WK (transfer to HKG) → VIE"
    assert "CKG-N" in desc and "HKG-WK" in desc and "HKG" in desc and "VIE" in desc
    assert "transfer" in desc.lower()
```

- [ ] **Step 3.2: Run tests, verify they fail**

```bash
pytest tests/test_candidates_types.py -v
```

Expected: `ModuleNotFoundError: No module named 'candidates'`.

- [ ] **Step 3.3: Create `candidates.py` with types only (generation comes later)**

```python
"""
candidates.py — routing engine.

Pure function: given (origin, destination, max_stops, include_train), returns
a list of Itinerary candidates. No network, no I/O, no hidden state. Same
input → same output.

Layering: imports from nodes.py and connections.py. Imported by pricer.py.
Never import pricer or currency from here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------- Mode constants ----------

FLIGHT = "FLIGHT"
TRAIN = "TRAIN"


# ---------- Data classes ----------

@dataclass
class Leg:
    mode: str                       # FLIGHT or TRAIN
    origin: str                     # node code
    destination: str                # node code
    duration_min: Optional[int] = None   # populated for trains; flights filled in by pricer
    cost_cny: Optional[int] = None       # same — train fare in CNY (source-of-truth)
    notes: str = ""


@dataclass
class Itinerary:
    legs: list[Leg]

    @property
    def origin(self) -> str:
        return self.legs[0].origin

    @property
    def destination(self) -> str:
        return self.legs[-1].destination

    @property
    def num_stops(self) -> int:
        return max(0, len(self.legs) - 1)

    @property
    def hub_codes(self) -> list[str]:
        """Intermediate transit codes between origin and destination."""
        return [leg.destination for leg in self.legs[:-1]]

    @property
    def has_train_leg(self) -> bool:
        return any(leg.mode == TRAIN for leg in self.legs)

    def describe(self) -> str:
        """Render as 'CKG → HKG → VIE' with rail transfers flagged."""
        parts: list[str] = [self.legs[0].origin]
        for i, leg in enumerate(self.legs):
            arrow = " ⇒ " if leg.mode == TRAIN else " → "
            # If the next leg's origin differs from this leg's destination,
            # render a transfer hint (e.g. HKG-WK → fly out of HKG).
            next_leg = self.legs[i + 1] if i + 1 < len(self.legs) else None
            if next_leg is not None and next_leg.origin != leg.destination:
                parts.append(arrow + f"{leg.destination} (transfer to {next_leg.origin})")
            else:
                parts.append(arrow + leg.destination)
        return "".join(parts)
```

- [ ] **Step 3.4: Run tests, verify they pass**

```bash
pytest tests/test_candidates_types.py -v
```

Expected: 11 passed.

- [ ] **Step 3.5: Commit**

```bash
git add candidates.py tests/test_candidates_types.py
git commit -m "feat: add Leg + Itinerary types in candidates.py"
```

---

## Task 4: `candidates.py` — direct flight generation

**Files:**
- Create: `tests/test_candidates_generation.py`
- Modify: `candidates.py`

- [ ] **Step 4.1: Write the failing test**

`tests/test_candidates_generation.py`:

```python
"""Tests for candidate routing generation."""
import pytest

from candidates import FLIGHT, TRAIN, Leg, Itinerary, generate_candidates


def test_direct_flight_is_always_first_candidate():
    cands = generate_candidates("CKG", "BKK", max_stops=0, include_train=False)
    assert len(cands) >= 1
    direct = cands[0]
    assert direct.num_stops == 0
    assert direct.legs[0].mode == FLIGHT
    assert direct.legs[0].origin == "CKG"
    assert direct.legs[0].destination == "BKK"


def test_direct_only_returns_just_one_candidate():
    cands = generate_candidates("CKG", "BKK", max_stops=0, include_train=False)
    assert len(cands) == 1


def test_direct_works_for_intra_china():
    cands = generate_candidates("CKG", "CTU", max_stops=0, include_train=False)
    assert len(cands) == 1
    assert cands[0].origin == "CKG" and cands[0].destination == "CTU"


def test_unknown_origin_raises():
    with pytest.raises(KeyError):
        generate_candidates("ZZZ", "BKK", max_stops=0, include_train=False)


def test_unknown_destination_raises():
    with pytest.raises(KeyError):
        generate_candidates("CKG", "ZZZ", max_stops=0, include_train=False)
```

- [ ] **Step 4.2: Run tests, verify they fail**

```bash
pytest tests/test_candidates_generation.py -v
```

Expected: `ImportError: cannot import name 'generate_candidates'`.

- [ ] **Step 4.3: Add `generate_candidates` to `candidates.py`**

Append to the bottom of `candidates.py`:

```python
# ---------- Imports for generation (kept at module level — no I/O) ----------
from nodes import NODES, Node


# ---------- Candidate generation ----------

def generate_candidates(
    origin_code: str,
    destination_code: str,
    max_stops: int = 1,
    include_train: bool = True,
) -> list[Itinerary]:
    """Generate every plausible Itinerary for (origin, destination).

    Pure function: same inputs → same outputs. No network, no I/O.

    Stages:
      1. Always include the direct flight as candidate #1.
      2. If max_stops >= 1, generate 1-stop options through valid transit hubs.
      3. If max_stops >= 2, generate 2-stop options (different-region pairs).
      4. If origin == "CKG" and include_train, generate train+fly options.
    """
    # Validate endpoints exist in NODES (raises KeyError on miss).
    origin: Node = NODES[origin_code]
    destination: Node = NODES[destination_code]

    candidates: list[Itinerary] = []

    # Stage 1: direct flight
    candidates.append(Itinerary(legs=[
        Leg(mode=FLIGHT, origin=origin_code, destination=destination_code),
    ]))

    return candidates
```

- [ ] **Step 4.4: Run tests, verify they pass**

```bash
pytest tests/test_candidates_generation.py -v
```

Expected: 5 passed.

- [ ] **Step 4.5: Commit**

```bash
git add candidates.py tests/test_candidates_generation.py
git commit -m "feat: direct-flight candidate generation"
```

---

## Task 5: `candidates.py` — TRANSIT_REGIONS table + 1-stop generation

**Files:**
- Modify: `tests/test_candidates_generation.py`
- Modify: `candidates.py`

- [ ] **Step 5.1: Add failing tests for 1-stop generation**

Append to `tests/test_candidates_generation.py`:

```python
def test_one_stop_generation_includes_direct_plus_via_hubs():
    cands = generate_candidates("CKG", "VIE", max_stops=1, include_train=False)
    # Direct + several 1-stop options through CHINA / GREATER_CHINA / EAST_ASIA / MIDDLE_EAST hubs
    assert len(cands) >= 4
    direct = cands[0]
    assert direct.num_stops == 0
    one_stops = [c for c in cands if c.num_stops == 1]
    assert len(one_stops) >= 3


def test_one_stop_via_hub_has_correct_hub_code():
    cands = generate_candidates("CKG", "VIE", max_stops=1, include_train=False)
    via_doh = next((c for c in cands if c.hub_codes == ["DOH"]), None)
    assert via_doh is not None
    assert via_doh.legs[0].origin == "CKG" and via_doh.legs[0].destination == "DOH"
    assert via_doh.legs[1].origin == "DOH" and via_doh.legs[1].destination == "VIE"


def test_one_stop_excludes_origin_and_destination_as_hubs():
    cands = generate_candidates("CKG", "VIE", max_stops=1, include_train=False)
    one_stops = [c for c in cands if c.num_stops == 1]
    for c in one_stops:
        assert c.hub_codes[0] != "CKG"
        assert c.hub_codes[0] != "VIE"


def test_one_stop_excludes_rail_nodes_as_transit_hubs():
    """Rail-only nodes (CKG-N, HKG-WK) must never appear as flight transit hubs."""
    cands = generate_candidates("CKG", "VIE", max_stops=1, include_train=False)
    one_stops = [c for c in cands if c.num_stops == 1]
    for c in one_stops:
        assert c.hub_codes[0] not in {"CKG-N", "HKG-WK"}


def test_southeast_asia_to_china_does_not_route_through_europe():
    """A CHINA ↔ SEA pair should not include EU or NA hubs as transit."""
    cands = generate_candidates("CKG", "BKK", max_stops=1, include_train=False)
    one_stops = [c for c in cands if c.num_stops == 1]
    eu_codes = {"LHR", "CDG", "FRA", "AMS", "MUC", "VIE"}
    na_codes = {"YVR", "YYZ", "YEG", "SEA", "SFO", "LAX", "ORD"}
    for c in one_stops:
        assert c.hub_codes[0] not in eu_codes
        assert c.hub_codes[0] not in na_codes
```

- [ ] **Step 5.2: Run tests, verify the new ones fail**

```bash
pytest tests/test_candidates_generation.py -v
```

Expected: previous 5 still pass; 5 new fail (e.g., `assert len(cands) >= 4` fails because we only return direct).

- [ ] **Step 5.3: Add TRANSIT_REGIONS and 1-stop generation to `candidates.py`**

Insert below the `from nodes import NODES, Node` line, before `generate_candidates`:

```python
# ---------- Geographic transit rules ----------
#
# TRANSIT_REGIONS[frozenset({region_a, region_b})] returns the set of regions
# that are valid transit zones for that origin/destination pair. Without this
# filter, every search would return nonsense like CKG → LHR via BKK.
#
# For same-region routes, frozenset({"CHINA"}) lookup uses the single-element key.
TRANSIT_REGIONS: dict[frozenset[str], set[str]] = {
    # Within-region (domestic + intra-area)
    frozenset({"CHINA"}):           {"CHINA"},
    frozenset({"GREATER_CHINA"}):   {"CHINA", "GREATER_CHINA"},
    frozenset({"SOUTHEAST_ASIA"}):  {"SOUTHEAST_ASIA"},
    frozenset({"EAST_ASIA"}):       {"EAST_ASIA"},
    frozenset({"EUROPE"}):          {"EUROPE"},
    frozenset({"MIDDLE_EAST"}):     {"MIDDLE_EAST"},
    frozenset({"NORTH_AMERICA"}):   {"NORTH_AMERICA"},

    # Cross-region pairs (lookup is order-independent via frozenset)
    frozenset({"CHINA", "GREATER_CHINA"}):    {"CHINA", "GREATER_CHINA"},
    frozenset({"CHINA", "EAST_ASIA"}):        {"CHINA", "GREATER_CHINA", "EAST_ASIA"},
    frozenset({"CHINA", "SOUTHEAST_ASIA"}):   {"CHINA", "GREATER_CHINA", "SOUTHEAST_ASIA"},
    frozenset({"CHINA", "MIDDLE_EAST"}):      {"CHINA", "GREATER_CHINA", "MIDDLE_EAST"},
    frozenset({"CHINA", "EUROPE"}):           {"CHINA", "GREATER_CHINA", "EAST_ASIA", "MIDDLE_EAST", "EUROPE"},
    frozenset({"CHINA", "NORTH_AMERICA"}):    {"CHINA", "GREATER_CHINA", "EAST_ASIA", "NORTH_AMERICA"},

    frozenset({"GREATER_CHINA", "EAST_ASIA"}):       {"CHINA", "GREATER_CHINA", "EAST_ASIA"},
    frozenset({"GREATER_CHINA", "SOUTHEAST_ASIA"}):  {"GREATER_CHINA", "SOUTHEAST_ASIA"},
    frozenset({"GREATER_CHINA", "MIDDLE_EAST"}):     {"GREATER_CHINA", "MIDDLE_EAST"},
    frozenset({"GREATER_CHINA", "EUROPE"}):          {"GREATER_CHINA", "EAST_ASIA", "MIDDLE_EAST", "EUROPE"},
    frozenset({"GREATER_CHINA", "NORTH_AMERICA"}):   {"GREATER_CHINA", "EAST_ASIA", "NORTH_AMERICA"},

    frozenset({"SOUTHEAST_ASIA", "EAST_ASIA"}):    {"SOUTHEAST_ASIA", "GREATER_CHINA", "EAST_ASIA"},
    frozenset({"SOUTHEAST_ASIA", "MIDDLE_EAST"}):  {"SOUTHEAST_ASIA", "MIDDLE_EAST"},
    frozenset({"SOUTHEAST_ASIA", "EUROPE"}):       {"SOUTHEAST_ASIA", "MIDDLE_EAST", "EUROPE"},
    frozenset({"SOUTHEAST_ASIA", "NORTH_AMERICA"}): {"SOUTHEAST_ASIA", "EAST_ASIA", "NORTH_AMERICA"},

    frozenset({"EAST_ASIA", "MIDDLE_EAST"}):       {"EAST_ASIA", "MIDDLE_EAST"},
    frozenset({"EAST_ASIA", "EUROPE"}):            {"EAST_ASIA", "MIDDLE_EAST", "EUROPE"},
    frozenset({"EAST_ASIA", "NORTH_AMERICA"}):     {"EAST_ASIA", "NORTH_AMERICA"},

    frozenset({"MIDDLE_EAST", "EUROPE"}):          {"MIDDLE_EAST", "EUROPE"},
    frozenset({"MIDDLE_EAST", "NORTH_AMERICA"}):   {"MIDDLE_EAST", "EUROPE", "NORTH_AMERICA"},

    frozenset({"EUROPE", "NORTH_AMERICA"}):        {"EUROPE", "NORTH_AMERICA"},
}


def _valid_transit_regions(origin_region: str, destination_region: str) -> set[str]:
    """Look up the set of valid transit regions for an origin/destination pair."""
    key = frozenset({origin_region, destination_region})
    return TRANSIT_REGIONS.get(key, {origin_region, destination_region})


def _airport_hubs_in_regions(regions: set[str], exclude: set[str]) -> list[Node]:
    """All airport-type hub nodes in any of the given regions, excluding `exclude` codes."""
    return [
        n for n in NODES.values()
        if n.region in regions
        and n.is_hub
        and n.node_type == "airport"
        and n.code not in exclude
    ]
```

Then update `generate_candidates` to add the 1-stop branch (replace the function body, keeping the direct-flight logic):

```python
def generate_candidates(
    origin_code: str,
    destination_code: str,
    max_stops: int = 1,
    include_train: bool = True,
) -> list[Itinerary]:
    """Generate every plausible Itinerary for (origin, destination)."""
    origin: Node = NODES[origin_code]
    destination: Node = NODES[destination_code]

    candidates: list[Itinerary] = []

    # Stage 1: direct flight (always)
    candidates.append(Itinerary(legs=[
        Leg(mode=FLIGHT, origin=origin_code, destination=destination_code),
    ]))

    # Stage 2: 1-stop via valid transit hubs
    if max_stops >= 1:
        regions = _valid_transit_regions(origin.region, destination.region)
        hubs = _airport_hubs_in_regions(regions, exclude={origin_code, destination_code})
        for hub in hubs:
            candidates.append(Itinerary(legs=[
                Leg(mode=FLIGHT, origin=origin_code, destination=hub.code),
                Leg(mode=FLIGHT, origin=hub.code, destination=destination_code),
            ]))

    return candidates
```

- [ ] **Step 5.4: Run tests, verify they pass**

```bash
pytest tests/test_candidates_generation.py -v
```

Expected: all 10 pass.

- [ ] **Step 5.5: Commit**

```bash
git add candidates.py tests/test_candidates_generation.py
git commit -m "feat: 1-stop candidate generation with TRANSIT_REGIONS rules"
```

---

## Task 6: `candidates.py` — RAIL_TO_AIRPORT + train+fly generation

**Files:**
- Modify: `tests/test_candidates_generation.py`
- Modify: `candidates.py`

- [ ] **Step 6.1: Add failing tests for train+fly generation**

Append to `tests/test_candidates_generation.py`:

```python
def test_train_fly_generated_only_for_ckg_origin():
    """include_train should be inert for non-CKG origins."""
    from_dad = generate_candidates("DAD", "BKK", max_stops=0, include_train=True)
    assert all(not c.has_train_leg for c in from_dad)


def test_train_fly_includes_train_then_flight():
    cands = generate_candidates("CKG", "BKK", max_stops=0, include_train=True)
    train_options = [c for c in cands if c.has_train_leg]
    assert len(train_options) >= 1
    for c in train_options:
        # First leg must be TRAIN starting at CKG-N
        assert c.legs[0].mode == TRAIN
        assert c.legs[0].origin == "CKG-N"
        # Subsequent legs must be FLIGHT
        for leg in c.legs[1:]:
            assert leg.mode == FLIGHT


def test_train_fly_train_leg_carries_cny_cost_and_duration():
    cands = generate_candidates("CKG", "BKK", max_stops=0, include_train=True)
    train_options = [c for c in cands if c.has_train_leg]
    assert any(c.legs[0].cost_cny is not None for c in train_options)
    assert any(c.legs[0].duration_min is not None for c in train_options)


def test_rail_to_airport_transfer_for_hkg_wk():
    """Train arriving at HKG-WK should be followed by a flight from HKG."""
    cands = generate_candidates("CKG", "VIE", max_stops=0, include_train=True)
    via_hkg = [
        c for c in cands
        if c.has_train_leg and c.legs[0].destination == "HKG-WK"
    ]
    assert len(via_hkg) >= 1
    for c in via_hkg:
        assert c.legs[1].origin == "HKG"   # transfer applied
        assert c.legs[1].destination == "VIE"


def test_train_options_excluded_when_include_train_false():
    cands_with = generate_candidates("CKG", "BKK", max_stops=0, include_train=True)
    cands_without = generate_candidates("CKG", "BKK", max_stops=0, include_train=False)
    train_count_with = sum(c.has_train_leg for c in cands_with)
    train_count_without = sum(c.has_train_leg for c in cands_without)
    assert train_count_with > 0
    assert train_count_without == 0
```

- [ ] **Step 6.2: Run tests, verify the new ones fail**

```bash
pytest tests/test_candidates_generation.py -v
```

Expected: previous tests pass; 5 new fail.

- [ ] **Step 6.3: Add RAIL_TO_AIRPORT and train+fly logic to `candidates.py`**

Add these imports at the top of the generation section, near `from nodes import NODES, Node`:

```python
from connections import TrainConnection, get_train_connections_from
```

Add the `RAIL_TO_AIRPORT` mapping near `TRANSIT_REGIONS`:

```python
# Rail nodes that aren't co-located with an airport must transfer to a nearby
# airport before the next flight leg. Maps rail-arrival code → flight-departure code.
RAIL_TO_AIRPORT: dict[str, str] = {
    "HKG-WK": "HKG",   # West Kowloon HSR → HKG airport (~30–40min)
    # CKG-N → CKG is implicit (CKG-N is only ever an *origin* for trains)
}
```

Update `generate_candidates` to add the train+fly branch (insert before the final `return candidates`):

```python
    # Stage 3: train + fly (CKG-only currently)
    if include_train and origin_code == "CKG":
        for tc in get_train_connections_from("CKG-N"):
            train_arrival = tc.destination
            airport_to_fly_from = RAIL_TO_AIRPORT.get(train_arrival, train_arrival)

            # Skip if the train terminus *is* the destination (no flight needed)
            if airport_to_fly_from == destination_code:
                continue

            # Skip if airport-to-fly-from isn't a valid flight node
            if airport_to_fly_from not in NODES:
                continue
            if NODES[airport_to_fly_from].node_type not in {"airport", "both"}:
                continue

            train_leg = Leg(
                mode=TRAIN,
                origin="CKG-N",
                destination=train_arrival,
                duration_min=tc.duration_min,
                cost_cny=tc.cost_cny_2nd_class,
                notes=tc.notes,
            )

            # Direct flight from rail-airport to destination
            candidates.append(Itinerary(legs=[
                train_leg,
                Leg(mode=FLIGHT, origin=airport_to_fly_from, destination=destination_code),
            ]))
```

- [ ] **Step 6.4: Run tests, verify they pass**

```bash
pytest tests/test_candidates_generation.py -v
```

Expected: all 15 pass.

- [ ] **Step 6.5: Add a failing test for train + 1-stop longhaul**

Append to `tests/test_candidates_generation.py`:

```python
def test_train_plus_one_stop_for_longhaul_europe():
    """For CKG → EUROPE, the system should also generate train+fly+via-hub options."""
    cands = generate_candidates("CKG", "VIE", max_stops=1, include_train=True)
    train_one_stops = [
        c for c in cands
        if c.has_train_leg and len(c.legs) == 3
    ]
    assert len(train_one_stops) >= 1
    for c in train_one_stops:
        assert c.legs[0].mode == TRAIN
        assert c.legs[1].mode == FLIGHT
        assert c.legs[2].mode == FLIGHT
        # Final leg ends at VIE
        assert c.legs[-1].destination == "VIE"


def test_train_plus_one_stop_not_generated_for_short_haul():
    """CKG → BKK (SE Asia) should NOT trigger the longhaul train+1-stop branch."""
    cands = generate_candidates("CKG", "BKK", max_stops=1, include_train=True)
    train_three_leg = [
        c for c in cands
        if c.has_train_leg and len(c.legs) == 3
    ]
    assert len(train_three_leg) == 0
```

- [ ] **Step 6.6: Run, verify the new tests fail**

```bash
pytest tests/test_candidates_generation.py -v
```

Expected: 2 new fail.

- [ ] **Step 6.7: Extend the train+fly branch in `candidates.py`**

Inside `generate_candidates`, in the "Stage 3: train + fly" section, after appending the direct train+fly itinerary, add:

```python
            # Longhaul extension: train + 1-stop flight for EUROPE / NORTH_AMERICA destinations
            LONGHAUL_REGIONS = {"EUROPE", "NORTH_AMERICA"}
            if destination.region in LONGHAUL_REGIONS:
                # Reuse the same transit-region rules used for pure-flight 1-stops,
                # but anchored on the airport we're flying out of after the train.
                rail_origin_region = NODES[airport_to_fly_from].region
                t_regions = _valid_transit_regions(rail_origin_region, destination.region)
                t_hubs = _airport_hubs_in_regions(
                    t_regions,
                    exclude={airport_to_fly_from, destination_code, origin_code},
                )
                for hub in t_hubs:
                    candidates.append(Itinerary(legs=[
                        train_leg,
                        Leg(mode=FLIGHT, origin=airport_to_fly_from, destination=hub.code),
                        Leg(mode=FLIGHT, origin=hub.code, destination=destination_code),
                    ]))
```

- [ ] **Step 6.8: Run tests, verify they pass**

```bash
pytest tests/test_candidates_generation.py -v
```

Expected: all 17 pass.

- [ ] **Step 6.9: Commit**

```bash
git add candidates.py tests/test_candidates_generation.py
git commit -m "feat: train+fly candidate generation with rail-to-airport transfers and longhaul extension"
```

---

## Task 7: `candidates.py` — 2-stop generation (no same-region backtracking)

**Files:**
- Modify: `tests/test_candidates_generation.py`
- Modify: `candidates.py`

- [ ] **Step 7.1: Add failing tests for 2-stop generation**

Append to `tests/test_candidates_generation.py`:

```python
def test_max_stops_zero_returns_only_direct_and_train():
    """No 1-stop candidates when max_stops=0."""
    cands = generate_candidates("CKG", "VIE", max_stops=0, include_train=False)
    assert len(cands) == 1
    assert cands[0].num_stops == 0


def test_max_stops_two_generates_two_stop_options():
    cands = generate_candidates("CKG", "VIE", max_stops=2, include_train=False)
    two_stops = [c for c in cands if c.num_stops == 2]
    assert len(two_stops) >= 1


def test_two_stop_does_not_repeat_a_region():
    """Both intermediate hubs must be in different regions."""
    from nodes import NODES
    cands = generate_candidates("CKG", "VIE", max_stops=2, include_train=False)
    two_stops = [c for c in cands if c.num_stops == 2]
    for c in two_stops:
        hub_a = NODES[c.hub_codes[0]]
        hub_b = NODES[c.hub_codes[1]]
        assert hub_a.region != hub_b.region


def test_two_stop_excludes_origin_and_destination_as_hubs():
    cands = generate_candidates("CKG", "VIE", max_stops=2, include_train=False)
    two_stops = [c for c in cands if c.num_stops == 2]
    for c in two_stops:
        assert "CKG" not in c.hub_codes
        assert "VIE" not in c.hub_codes
```

- [ ] **Step 7.2: Run tests, verify the new ones fail**

```bash
pytest tests/test_candidates_generation.py -v
```

Expected: 4 new fail (2-stop count is 0).

- [ ] **Step 7.3: Add 2-stop generation to `candidates.py`**

Insert into `generate_candidates`, between the 1-stop section and the train+fly section:

```python
    # Stage 2b: 2-stop via different-region hub pairs (avoids backtracking)
    if max_stops >= 2:
        regions = _valid_transit_regions(origin.region, destination.region)
        hubs = _airport_hubs_in_regions(regions, exclude={origin_code, destination_code})
        for hub_a in hubs:
            for hub_b in hubs:
                if hub_a.code == hub_b.code:
                    continue
                if hub_a.region == hub_b.region:
                    continue   # no same-region backtracking
                candidates.append(Itinerary(legs=[
                    Leg(mode=FLIGHT, origin=origin_code, destination=hub_a.code),
                    Leg(mode=FLIGHT, origin=hub_a.code, destination=hub_b.code),
                    Leg(mode=FLIGHT, origin=hub_b.code, destination=destination_code),
                ]))
```

- [ ] **Step 7.4: Run tests, verify they pass**

```bash
pytest tests/test_candidates_generation.py -v
```

Expected: all 19 pass.

- [ ] **Step 7.5: Commit**

```bash
git add candidates.py tests/test_candidates_generation.py
git commit -m "feat: 2-stop candidate generation (no same-region backtracking)"
```

---

## Task 8: End-to-end mock pipeline validation

**Files:**
- Create: `tests/test_e2e_mock.py`

- [ ] **Step 8.1: Write the end-to-end mock test**

`tests/test_e2e_mock.py`:

```python
"""End-to-end smoke test against the mock pricer (USE_MOCK = True)."""
import pricer
from candidates import generate_candidates


def test_pricer_module_uses_mock_by_default():
    assert pricer.USE_MOCK is True


def test_e2e_ckg_to_bkk_with_train():
    cands = generate_candidates("CKG", "BKK", max_stops=1, include_train=True)
    assert len(cands) >= 5

    priced = pricer.price_candidates(cands, date="2026-09-15")
    assert len(priced) == len(cands)

    complete = [p for p in priced if p.is_complete]
    assert len(complete) >= 1

    ranked_by_cost = pricer.rank_by_cost(priced)
    assert ranked_by_cost == sorted(ranked_by_cost, key=lambda p: p.total_cost)

    formatted = pricer.format_results(ranked_by_cost, top_n=8)
    assert "CKG" in formatted and "BKK" in formatted
    assert "savings/hr" in formatted


def test_e2e_dad_to_ckg_no_train():
    cands = generate_candidates("DAD", "CKG", max_stops=1, include_train=False)
    priced = pricer.price_candidates(cands, date="2026-09-15")
    assert all(not p.itinerary.has_train_leg for p in priced)
```

- [ ] **Step 8.2: Run tests, verify they pass**

```bash
pytest tests/test_e2e_mock.py -v
```

Expected: 3 passed.

- [ ] **Step 8.3: Run pricer.py demo block manually**

```bash
python pricer.py
```

Expected: prints "Mode: MOCK pricing", followed by two ranked tables (DAD→CKG and CKG→BKK), and `[FX source: live]` or `disk` at the bottom. No exceptions.

- [ ] **Step 8.4: Commit**

```bash
git add tests/test_e2e_mock.py
git commit -m "test: end-to-end mock pipeline integration tests"
```

---

## Task 9: Verify the live `fli` library API

**Goal:** Confirm whether `_real_fli_search()` in `pricer.py` matches the actual API of `flights==0.8.4`. This is exploratory — no source changes yet.

**Files:**
- Create (temporarily): `scripts/probe_fli.py`

- [ ] **Step 9.1: Create a probe script**

```bash
mkdir -p scripts
```

`scripts/probe_fli.py`:

```python
"""Probe the installed fli library's surface so we know what _real_fli_search needs."""
import importlib
import inspect

print("=== fli package version ===")
try:
    import fli  # noqa: F401
    print("fli imports OK")
except Exception as e:
    print(f"fli import FAILED: {e}")

print()
print("=== Modules expected by _real_fli_search ===")
for mod_name in ["fli.search", "fli.models"]:
    try:
        mod = importlib.import_module(mod_name)
        print(f"\n[{mod_name}] ✓")
        names = [n for n in dir(mod) if not n.startswith("_")]
        print("  exports:", ", ".join(sorted(names)))
    except Exception as e:
        print(f"\n[{mod_name}] ✗ {e}")

print()
print("=== Classes _real_fli_search relies on ===")
for path in [
    "fli.search.SearchFlights",
    "fli.models.FlightSearchFilters",
    "fli.models.FlightSegment",
    "fli.models.Airport",
    "fli.models.PassengerInfo",
    "fli.models.SeatType",
    "fli.models.MaxStops",
    "fli.models.SortBy",
]:
    mod_name, _, cls_name = path.rpartition(".")
    try:
        mod = importlib.import_module(mod_name)
        obj = getattr(mod, cls_name)
        print(f"  ✓ {path}  ({type(obj).__name__})")
    except Exception as e:
        print(f"  ✗ {path}  — {e}")

print()
print("=== Inspect SearchFlights.search signature ===")
try:
    from fli.search import SearchFlights
    sig = inspect.signature(SearchFlights.search)
    print("  SearchFlights.search", sig)
except Exception as e:
    print(f"  could not inspect: {e}")

print()
print("=== Inspect Airport (is it an Enum? a class?) ===")
try:
    from fli.models import Airport
    print(f"  type: {type(Airport).__name__}")
    sample = next(iter(Airport.__members__)) if hasattr(Airport, "__members__") else None
    if sample:
        print(f"  sample member: Airport.{sample}")
    else:
        print("  not enum-like — needs different access pattern")
except Exception as e:
    print(f"  could not inspect: {e}")
```

- [ ] **Step 9.2: Run the probe**

```bash
python scripts/probe_fli.py 2>&1 | tee /tmp/fli_probe.txt
```

Read the output carefully. Note three things:

1. Which classes are missing or moved (✗ lines).
2. The actual signature of `SearchFlights.search` — does it take filters, kwargs, both?
3. Whether `Airport` is an Enum (`Airport["CKG"]`) or a class (`Airport.CKG` / `Airport(code="CKG")`).

- [ ] **Step 9.3: Try a minimal real call to confirm result shape**

If the imports look correct, append a probe call to `scripts/probe_fli.py` (or run inline):

```bash
python -c "
from fli.search import SearchFlights
from fli.models import (
    FlightSearchFilters, FlightSegment, Airport,
    PassengerInfo, SeatType, MaxStops, SortBy,
)
filters = FlightSearchFilters(
    passenger_info=PassengerInfo(adults=1),
    flight_segments=[
        FlightSegment(
            departure_airport=[[Airport['CKG'], 0]],
            arrival_airport=[[Airport['BKK'], 0]],
            travel_date='2026-09-15',
        )
    ],
    seat_type=SeatType.ECONOMY,
    stops=MaxStops.NONE,
    sort_by=SortBy.CHEAPEST,
)
results = SearchFlights().search(filters)
print('result count:', len(results) if results else 0)
if results:
    r = results[0]
    print('result type:', type(r).__name__)
    print('result attrs:', sorted(a for a in dir(r) if not a.startswith('_'))[:20])
    print('price:', getattr(r, 'price', None))
    print('duration:', getattr(r, 'duration', None))
    print('airline:', getattr(r, 'airline', None))
"
```

If this raises a `TypeError`, an `AttributeError`, or returns objects that don't have `.price` / `.duration` / `.airline` — record exactly what changed. The next task fixes it.

If this returns a plausible price (Google Flights would show ~$150–300 USD for CKG→BKK 4–5 months out), the call signature is good; **skip Task 10's code changes** and just confirm in Task 10 that the existing function works.

- [ ] **Step 9.4: Save probe results to plan history (optional but useful)**

```bash
mkdir -p docs/superpowers/plans/.history
cp /tmp/fli_probe.txt docs/superpowers/plans/.history/fli-probe-$(date +%Y%m%d).txt
```

- [ ] **Step 9.5: No commit yet** — Task 10 either confirms or modifies based on findings.

---

## Task 10: Apply fli integration fixes (if Task 9 found drift)

**Files:**
- Modify: `pricer.py:101-139` (the `_real_fli_search` function)

This task has two paths depending on what Task 9 turned up.

### Path A — fli API matches the existing `_real_fli_search()`

- [ ] **Step 10A.1: No source change needed.** Confirm by running:

```bash
python -c "
from pricer import _real_fli_search
r = _real_fli_search('CKG', 'BKK', '2026-09-15')
print(r)
assert r is None or ('price_usd' in r and 'duration_min' in r and 'airline' in r)
print('OK')
"
```

Expected: a dict with `price_usd`, `duration_min`, `airline` (or `None` if no flights). If this succeeds, skip to Task 11.

### Path B — fli API has drifted

- [ ] **Step 10B.1: Edit `_real_fli_search()` based on probe findings**

The exact edits depend on what changed. Common drifts and their fixes:

- **`Airport` access pattern changed** — if `Airport["CKG"]` no longer works but `Airport.from_code("CKG")` does, change the two `Airport[origin]` / `Airport[destination]` lines accordingly.
- **`departure_airport` / `arrival_airport` shape changed** — fli sometimes accepts a flat `Airport` rather than `[[Airport, 0]]`. Match what the probe found.
- **`travel_date` field renamed** — could be `date`, `departure_date`, etc.
- **Result attribute names changed** — `.price` → `.total_price`, `.duration` → `.total_duration_minutes`, `.airline` → `.carriers[0].name`. Update the result extraction at the bottom of the function.

For each change, keep the function's external contract the same:

```python
# Returns either None or {"price_usd": float, "duration_min": int, "airline": str}
```

- [ ] **Step 10B.2: Re-run the integration probe**

```bash
python -c "
from pricer import _real_fli_search
r = _real_fli_search('CKG', 'BKK', '2026-09-15')
print(r)
assert r is None or ('price_usd' in r and 'duration_min' in r and 'airline' in r)
print('OK')
"
```

Expected: same as Path A.

- [ ] **Step 10B.3: Commit the fix**

```bash
git add pricer.py
git commit -m "fix: align _real_fli_search with current fli library API"
```

---

## Task 11: Live sanity check (flip USE_MOCK = False)

**Files:**
- Modify: `pricer.py:33`

- [ ] **Step 11.1: Flip the flag**

In `pricer.py`, change line 33:

```python
USE_MOCK = True
```

to:

```python
USE_MOCK = False
```

- [ ] **Step 11.2: Run a single direct-flight live query**

```bash
python -c "
import pricer
from candidates import generate_candidates
cands = generate_candidates('CKG', 'BKK', max_stops=0, include_train=False)
priced = pricer.price_candidates(cands, date='2026-09-15')
print(pricer.format_results(pricer.rank_by_cost(priced), top_n=5))
"
```

Expected: a single direct CKG → BKK row with a real price (likely C$200–500 for that date) and a real duration (~3-4 hours / `~3h00m`–`4h00m`). The price should not be the synthetic $0.10/km mock value.

- [ ] **Step 11.3: Manually compare with Google Flights**

Open https://www.google.com/travel/flights in a browser. Search CKG → BKK on 2026-09-15. Confirm:

- The cheapest direct flight price is within ~20% of what the script returned.
- The duration matches roughly.

If prices are off by >20% or durations are wrong, do not commit yet — investigate (could be FX rate issue, wrong fli filter, or fli returning a different result ordering than `SortBy.CHEAPEST`).

- [ ] **Step 11.4: Run the full demo against live fli**

```bash
python pricer.py
```

Expected: "Mode: LIVE fli pricing"; both DAD→CKG and CKG→BKK ranked tables populated with real prices. Some candidates may fail (e.g., no direct service on a leg) — that's fine and gets reported in the output.

- [ ] **Step 11.5: Commit**

```bash
git add pricer.py
git commit -m "feat: enable live fli pricing (USE_MOCK = False)"
```

---

## Task 12: `cli.py` — runnable as `python cli.py CKG VIE 2026-09-15`

**Files:**
- Create: `cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 12.1: Write the failing test**

`tests/test_cli.py`:

```python
"""Test the CLI argument parser and dispatch — without hitting the live API."""
import pytest

import pricer
from cli import build_parser, main


def test_parser_required_args():
    parser = build_parser()
    args = parser.parse_args(["CKG", "VIE", "2026-09-15"])
    assert args.origin == "CKG"
    assert args.destination == "VIE"
    assert args.date == "2026-09-15"
    assert args.max_stops == 1
    assert args.train is True
    assert args.sort == "cost"


def test_parser_overrides():
    parser = build_parser()
    args = parser.parse_args([
        "CKG", "VIE", "2026-09-15",
        "--max-stops", "2",
        "--no-train",
        "--sort", "duration",
        "--top", "5",
    ])
    assert args.max_stops == 2
    assert args.train is False
    assert args.sort == "duration"
    assert args.top == 5


def test_main_runs_against_mock(monkeypatch, capsys):
    """End-to-end CLI run with mock pricing — should print a ranked table."""
    monkeypatch.setattr(pricer, "USE_MOCK", True)
    # Re-bind _fli_search since pricer caches the choice at import time.
    monkeypatch.setattr(pricer, "_fli_search", pricer._mock_fli_search)
    rc = main(["CKG", "BKK", "2026-09-15", "--no-train", "--top", "3"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "CKG" in out and "BKK" in out
    assert "savings/hr" in out
```

- [ ] **Step 12.2: Run, verify failure**

```bash
pytest tests/test_cli.py -v
```

Expected: `ModuleNotFoundError: No module named 'cli'`.

- [ ] **Step 12.3: Implement `cli.py`**

```python
"""
cli.py — terminal entry point.

Usage:
    python cli.py CKG VIE 2026-09-15
    python cli.py CKG VIE 2026-09-15 --max-stops 2 --sort duration --top 5
    python cli.py DAD CKG 2026-09-15 --no-train
"""

from __future__ import annotations

import argparse
import sys

import currency
import pricer
from candidates import generate_candidates


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="flight-router",
        description="Generate, price, and rank candidate routings between airports.",
    )
    p.add_argument("origin", help="3-letter airport code (e.g. CKG)")
    p.add_argument("destination", help="3-letter airport code (e.g. VIE)")
    p.add_argument("date", help="YYYY-MM-DD departure date")
    p.add_argument("--max-stops", type=int, default=1,
                   help="Maximum number of intermediate stops (default 1)")
    p.add_argument("--train", dest="train", action="store_true", default=True,
                   help="Include train+fly options (CKG origin only). Default: on.")
    p.add_argument("--no-train", dest="train", action="store_false",
                   help="Disable train+fly options.")
    p.add_argument("--sort", choices=["cost", "duration"], default="cost",
                   help="Sort ranking by cost or duration (default cost)")
    p.add_argument("--top", type=int, default=10,
                   help="Show top N results (default 10)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Kick off FX refresh as early as possible.
    currency.start_background_refresh()

    print(f"Mode: {'MOCK pricing' if pricer.USE_MOCK else 'LIVE fli pricing'}")
    print(f"Searching {args.origin} → {args.destination} on {args.date} "
          f"(max_stops={args.max_stops}, train={args.train})")
    print("=" * 90)

    cands = generate_candidates(
        args.origin, args.destination,
        max_stops=args.max_stops, include_train=args.train,
    )
    print(f"Generated {len(cands)} candidate(s). Pricing...")

    priced = pricer.price_candidates(cands, date=args.date)

    if args.sort == "duration":
        ranked = pricer.rank_by_duration(priced)
    else:
        ranked = pricer.rank_by_cost(priced)

    print()
    print(pricer.format_results(ranked, top_n=args.top))
    print()
    print(f"[FX source: {currency.get_source()}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 12.4: Run tests, verify they pass**

```bash
pytest tests/test_cli.py -v
```

Expected: 3 passed.

- [ ] **Step 12.5: Smoke-test the CLI (live)**

```bash
python cli.py CKG BKK 2026-09-15 --max-stops 1 --top 5
```

Expected: ranked table printed, exit code 0.

- [ ] **Step 12.6: Commit**

```bash
git add cli.py tests/test_cli.py
git commit -m "feat: add cli.py for terminal usage"
```

---

## Task 13: Documentation pass

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 13.1: Update CLAUDE.md status section**

Open `CLAUDE.md`. Find:

```markdown
## Status

**v1 working.** Five-module pipeline is in place and runs end-to-end against a mock pricer. Live `fli` integration is sketched but not yet verified — the `_real_fli_search()` function in `pricer.py` is a best-guess against fli's API and needs to be tested against current docs before flipping `USE_MOCK = False`.
```

Replace with:

```markdown
## Status

**v1 complete.** Five-module pipeline runs end-to-end against the live `fli` library. CLI available as `python cli.py CKG VIE 2026-09-15`. Test suite covers candidates generation, connections data, types, and end-to-end mock pricing.
```

Also update the **Immediate next steps** section. Remove the items now done:

```markdown
## Immediate next steps

1. Add date-range search using `fli.search_dates` — see ARCHITECTURE.md §5.1 for the design.
2. Consider Kiwi.com integration for self-transfer routings (architecture sketched in ARCHITECTURE.md §5.3).
```

- [ ] **Step 13.2: Run the full test suite once more**

```bash
pytest -v
```

Expected: every test passes.

- [ ] **Step 13.3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: mark v1 complete in CLAUDE.md"
```

---

## Final verification checklist

- [ ] `pytest -v` — all tests pass
- [ ] `python pricer.py` — runs end-to-end against live fli, prints ranked tables
- [ ] `python cli.py CKG BKK 2026-09-15` — works from terminal
- [ ] `python cli.py CKG VIE 2026-09-15 --max-stops 1` — handles longhaul + 1-stop
- [ ] `python cli.py DAD CKG 2026-09-15 --no-train` — works for non-CKG origins
- [ ] `git log --oneline` — shows clean, atomic commits per task
- [ ] No upward dependencies introduced (verify: `grep -E "^from (pricer|currency)" candidates.py connections.py nodes.py` returns nothing)
