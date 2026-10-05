"""
timetable.py — real train departures out of Chongqing, used to suggest which
train to catch for a train+fly itinerary.

Source: data/train_timetable.csv, one row per train (pulled from 12306 via
DeepSeek). connections.py still holds the rough per-route summary that the
routing engine uses; this module adds the actual train numbers and times.

China Railway revises the national timetable ~4x/year, so refresh the CSV
after each revision and update TIMETABLE_AS_OF. Rows with no times (trains
suspended in a revision) are skipped.

Always verify on 12306 / Trip.com before booking — tickets go on sale 15 days
before departure.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date as Date, datetime, timedelta
from functools import lru_cache
from pathlib import Path


# ---------- Configuration ----------

TIMETABLE_FILE = Path(__file__).parent / "data" / "train_timetable.csv"
TIMETABLE_AS_OF = "2026-10-15"   # date the CSV was pulled (after the 2026-10-11 revision)

# Minutes needed between the train arriving and the flight departing: getting
# from the station to the airport, plus check-in/security (most onward flights
# from these hubs are international). Rough — edit to taste.
DEFAULT_CONNECTION_MIN = 180
CONNECTION_MIN = {
    "HKG-WK": 180,   # West Kowloon -> HKG airport ~40min
    "CAN": 210,      # Guangzhou South -> Baiyun ~60-75min
    "PEK": 210,      # Beijing West -> PEK/PKX ~60-75min
    "PVG": 210,      # Hongqiao -> Pudong ~60-75min
}

# Don't suggest trains that would leave you waiting longer than this. Long
# enough to include "train the evening before, hotel, morning flight".
MAX_WAIT_MIN = 18 * 60


# ---------- Data ----------

@dataclass(frozen=True)
class Train:
    dest_code: str           # matches TrainConnection.destination (CTU, HKG-WK, ...)
    train_no: str
    from_station: str
    depart: str              # "HH:MM", China time
    to_station: str
    arrive: str              # "HH:MM", China time
    next_day: int            # days after departure that it arrives (0, 1)
    duration_min: int
    fare_cny: float | None
    notes: str = ""

    @property
    def is_sleeper(self) -> bool:
        return "sleeper" in self.notes.lower()


def _station_short(name: str) -> str:
    """'Chongqing West (重庆西)' -> 'Chongqing West'."""
    return name.split(" (")[0]


def _parse_fare(raw: str) -> float | None:
    raw = raw.strip().lstrip("¥").strip()
    return float(raw) if raw else None


@lru_cache(maxsize=1)
def load_trains(path: Path = TIMETABLE_FILE) -> tuple[Train, ...]:
    """All running trains in the timetable. Cached — the file is read once."""
    if not path.exists():
        return ()
    trains = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not row["depart"] or not row["arrive"]:
                continue   # suspended in a timetable revision
            trains.append(Train(
                dest_code=row["dest_code"],
                train_no=row["train_no"],
                from_station=row["from_station"],
                depart=row["depart"],
                to_station=row["to_station"],
                arrive=row["arrive"],
                next_day=int(row["next_day"] or 0),
                duration_min=int(row["duration_min"]),
                fare_cny=_parse_fare(row["second_class_cny"]),
                notes=row.get("notes", ""),
            ))
    return tuple(trains)


# ---------- Suggestions ----------

@dataclass(frozen=True)
class TrainOption:
    train: Train
    departs: datetime
    arrives: datetime

    def describe(self, flight_day: Date | None = None) -> str:
        """One-line summary. Flags the departure day when it isn't `flight_day`."""
        t = self.train
        flight_day = flight_day or self.arrives.date()
        day = "" if self.departs.date() == flight_day else f" (leaves {self.departs:%a %d %b})"
        fare = f", ¥{t.fare_cny:g}" if t.fare_cny is not None else ""
        sleeper = ", sleeper" if t.is_sleeper else ""
        return (f"{t.train_no} {t.depart} {_station_short(t.from_station)} → "
                f"{t.arrive} {_station_short(t.to_station)}{day}{fare}{sleeper}")


def suggest_trains(
    dest_code: str,
    flight_departs: datetime,
    limit: int = 3,
    trains: tuple[Train, ...] | None = None,
) -> list[TrainOption]:
    """Trains to `dest_code` that arrive in time for a flight leaving at `flight_departs`.

    Arrival must leave at least CONNECTION_MIN[dest_code] before the flight, and
    no more than MAX_WAIT_MIN of waiting. Ordered latest-departure first (the
    least total time spent getting to the flight), then by fare. Pure function
    given `trains`.
    """
    if trains is None:
        trains = load_trains()
    flight_departs = flight_departs.replace(tzinfo=None)
    deadline = flight_departs - timedelta(minutes=CONNECTION_MIN.get(dest_code, DEFAULT_CONNECTION_MIN))
    earliest = deadline - timedelta(minutes=MAX_WAIT_MIN)

    options = []
    for t in trains:
        if t.dest_code != dest_code:
            continue
        dh, dm = map(int, t.depart.split(":"))
        # A train arriving on the flight day may have left up to 2 days earlier.
        for days_before in range(0, 3):
            dep_day: Date = flight_departs.date() - timedelta(days=days_before)
            departs = datetime(dep_day.year, dep_day.month, dep_day.day, dh, dm)
            arrives = departs + timedelta(minutes=t.duration_min)
            if earliest <= arrives <= deadline:
                options.append(TrainOption(t, departs, arrives))

    options.sort(key=lambda o: (-o.departs.timestamp(), o.train.fare_cny or 0))
    return options[:limit]
