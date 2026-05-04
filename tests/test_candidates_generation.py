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
