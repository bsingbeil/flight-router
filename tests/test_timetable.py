"""Tests for timetable.py: loading the real CSV and suggesting trains for a flight."""
from datetime import datetime

import pricer
import timetable
from candidates import FLIGHT, TRAIN, Itinerary, Leg
from timetable import Train


def _train(no, depart, arrive, duration, next_day=0, dest="HKG-WK", fare=788.0, notes=""):
    return Train(dest, no, "Chongqing West (重庆西)", depart, "Somewhere (某站)", arrive,
                 next_day, duration, fare, notes)


# ---------- the real data file ----------

def test_real_timetable_loads_and_skips_suspended():
    trains = timetable.load_trains()
    assert len(trains) > 200
    assert all(t.depart and t.arrive for t in trains)


def test_real_timetable_durations_match_times():
    for t in timetable.load_trains():
        dh, dm = map(int, t.depart.split(":"))
        ah, am = map(int, t.arrive.split(":"))
        assert (ah * 60 + am) - (dh * 60 + dm) + 1440 * t.next_day == t.duration_min, t


def test_real_timetable_dest_codes_are_train_connections():
    from connections import TRAIN_CONNECTIONS
    known = {c.destination for c in TRAIN_CONNECTIONS}
    assert {t.dest_code for t in timetable.load_trains()} <= known


def test_real_hong_kong_train():
    g905 = [t for t in timetable.load_trains() if t.train_no == "G905" and t.dest_code == "HKG-WK"]
    assert g905 and g905[0].depart == "08:44" and g905[0].fare_cny == 788.0


# ---------- suggest_trains ----------

def test_suggests_train_that_makes_the_flight():
    trains = (_train("G905", "08:44", "15:57", 433),)
    # HKG-WK needs 180 min: arriving 15:57 makes a 19:00 flight, not an 18:00 one.
    assert len(timetable.suggest_trains("HKG-WK", datetime(2026, 10, 20, 19, 0), trains=trains)) == 1
    assert timetable.suggest_trains("HKG-WK", datetime(2026, 10, 20, 18, 0), trains=trains) == []


def test_morning_flight_suggests_previous_day_train():
    trains = (_train("G905", "08:44", "15:57", 433),)
    [opt] = timetable.suggest_trains("HKG-WK", datetime(2026, 10, 20, 9, 0), trains=trains)
    assert opt.departs == datetime(2026, 10, 19, 8, 44)
    assert "leaves Mon 19 Oct" in opt.describe(datetime(2026, 10, 20).date())


def test_overnight_train_arriving_on_flight_day():
    trains = (_train("Z1", "22:00", "06:00", 480, next_day=1, notes="sleeper train"),)
    [opt] = timetable.suggest_trains("HKG-WK", datetime(2026, 10, 20, 12, 0), trains=trains)
    assert opt.departs == datetime(2026, 10, 19, 22, 0)
    assert opt.arrives == datetime(2026, 10, 20, 6, 0)
    assert "sleeper" in opt.describe()


def test_too_much_waiting_is_excluded():
    trains = (_train("G1", "06:00", "07:00", 60),)
    # Arrives 07:00 on the 20th; flight 05:00 on the 21st -> deadline 02:00, 19h wait.
    assert timetable.suggest_trains("HKG-WK", datetime(2026, 10, 21, 5, 0), trains=trains) == []


def test_ordered_latest_departure_first_and_limited():
    trains = tuple(_train(f"G{h}", f"{h:02d}:00", f"{h + 2:02d}:00", 120) for h in range(6, 12))
    opts = timetable.suggest_trains("HKG-WK", datetime(2026, 10, 20, 17, 0), limit=3, trains=trains)
    assert [o.train.train_no for o in opts] == ["G11", "G10", "G9"]


def test_other_destinations_ignored():
    trains = (_train("G1", "08:00", "10:00", 120, dest="CTU"),)
    assert timetable.suggest_trains("HKG-WK", datetime(2026, 10, 20, 17, 0), trains=trains) == []


# ---------- pricer integration ----------

def _priced(flight_departs):
    train = Leg(mode=TRAIN, origin="CKG-N", destination="HKG-WK", duration_min=433, cost_cny=788)
    flight = Leg(mode=FLIGHT, origin="HKG", destination="VIE")
    return pricer.PricedItinerary(Itinerary([train, flight]), [
        pricer.PricedLeg(train, cost=150, duration_min=433, airline="HSR"),
        pricer.PricedLeg(flight, cost=900, duration_min=720, airline="X", departs=flight_departs),
    ])


def test_train_suggestions_in_results():
    lines = pricer.train_suggestions(_priced("2026-10-20T23:30"))
    assert lines and "flight HKG 23:30" in lines[0] and "G905" in lines[0]


def test_train_suggestions_none_in_time():
    # 13:00 flight: the only HK train arrives 15:57 — too late that day, and an
    # 18h+ wait from the day before.
    lines = pricer.train_suggestions(_priced("2026-10-20T13:00"))
    assert lines and "no direct train fits" in lines[0]


def test_train_suggestions_need_flight_time():
    assert pricer.train_suggestions(_priced(None)) == []
