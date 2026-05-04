"""End-to-end smoke test that forces the mock pricer regardless of pricer.USE_MOCK."""
import pytest

import pricer
from candidates import generate_candidates


@pytest.fixture(autouse=True)
def _force_mock_pricer(monkeypatch):
    """Force the mock pricer for all tests in this module, regardless of pricer.USE_MOCK."""
    monkeypatch.setattr(pricer, "USE_MOCK", True)
    monkeypatch.setattr(pricer, "_fli_search", pricer._mock_fli_search)


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
