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
