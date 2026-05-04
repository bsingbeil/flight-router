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
