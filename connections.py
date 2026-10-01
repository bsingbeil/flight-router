"""
connections.py — high-speed rail connections useful for first-leg routing.

One entry per destination, from whichever Chongqing station (North or West)
has the fastest regular (non-sleeper) train. Duration and fare are that
train's, from data/train_timetable.csv (12306 timetable as of 2026-10-15).
timetable.py has every individual train; this file is the per-route summary
the routing engine uses. Re-derive these numbers when the timetable is
refreshed — tests/test_timetable.py checks they still match.

Train fares are stored in CNY since that's the source-of-truth currency;
pricer.py converts to display currency at runtime. Always verify on Trip.com
or 12306 before booking.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Chongqing stations trains can start from (must exist in NODES).
CHONGQING_STATIONS = ("CKG-N", "CKG-W")


@dataclass
class TrainConnection:
    origin: str               # node code (must exist in NODES)
    destination: str          # node code (must exist in NODES)
    duration_min: int
    cost_cny_2nd_class: float # CNY, source-of-truth
    frequency: str            # human-readable, for display only
    notes: str = ""


TRAIN_CONNECTIONS: list[TrainConnection] = [
    TrainConnection(
        origin="CKG-W", destination="CTU",
        duration_min=64, cost_cny_2nd_class=149,
        frequency="59 daily from CKG-W 06:00–21:52 (+50 from CKG-N)",
        notes="Fastest: G8608. Very frequent from both stations; arrives Chengdu East.",
    ),
    TrainConnection(
        origin="CKG-W", destination="XIY",
        duration_min=301, cost_cny_2nd_class=384,
        frequency="15 daily from CKG-W 06:41–17:59 (+6 from CKG-N)",
        notes="Fastest: D968. Cheapest are D-trains from CKG-N (~¥294). Arrives Xi'an North.",
    ),
    TrainConnection(
        origin="CKG-W", destination="CAN",
        duration_min=346, cost_cny_2nd_class=508,
        frequency="13 daily from CKG-W 06:51–21:37, incl. 2 overnight D-trains",
        notes="Fastest: G2965. Arrives Guangzhou South.",
    ),
    TrainConnection(
        origin="CKG-W", destination="SZX",
        duration_min=388, cost_cny_2nd_class=582.5,
        frequency="5 daily from CKG-W 06:51–21:37, incl. 1 overnight D-train",
        notes="Fastest: G2965. Arrives Shenzhen North. None from CKG-N.",
    ),
    TrainConnection(
        origin="CKG-W", destination="HKG-WK",
        duration_min=433, cost_cny_2nd_class=788,
        frequency="1 daily: G905 08:44 → 15:57",
        notes="Only direct train. Arrives West Kowloon; ~30–40min to HKG airport. "
              "Otherwise train to SZX and cross the border.",
    ),
    TrainConnection(
        origin="CKG-W", destination="KMG",
        duration_min=291, cost_cny_2nd_class=342,
        frequency="14 daily from CKG-W 06:41–17:42 (+4 from CKG-N)",
        notes="Fastest: G2881. Arrives Kunming South.",
    ),
    TrainConnection(
        origin="CKG-N", destination="PEK",
        duration_min=430, cost_cny_2nd_class=834,
        frequency="6 daily from CKG-N 07:21–16:28, incl. 3 overnight D-trains",
        notes="Fastest: G330. Overnight D-trains (~18h) are ~¥340. Arrives Beijing West.",
    ),
    TrainConnection(
        origin="CKG-W", destination="PVG",
        duration_min=541, cost_cny_2nd_class=870,
        frequency="5 daily from CKG-W 07:53–09:22 (+14 from CKG-N, incl. overnight)",
        notes="Fastest: G243. Arrives Shanghai Hongqiao — ~60–75min to PVG; SHA is next door.",
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
