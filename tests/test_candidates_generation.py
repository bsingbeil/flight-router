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
