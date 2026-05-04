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
