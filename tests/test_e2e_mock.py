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
