"""
cli.py — terminal entry point.

Usage:
    python cli.py CKG VIE 2026-09-15
    python cli.py CKG VIE 2026-09-15 --max-stops 2 --sort duration --top 5
    python cli.py DAD CKG 2026-09-15 --no-train
"""

from __future__ import annotations

import argparse
import sys

import currency
import pricer
from candidates import generate_candidates


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="flight-router",
        description="Generate, price, and rank candidate routings between airports.",
    )
    p.add_argument("origin", help="3-letter airport code (e.g. CKG)")
    p.add_argument("destination", help="3-letter airport code (e.g. VIE)")
    p.add_argument("date", help="YYYY-MM-DD departure date")
    p.add_argument("--max-stops", type=int, default=1,
                   help="Maximum number of intermediate stops (default 1)")
    p.add_argument("--train", dest="train", action="store_true", default=True,
                   help="Include train+fly options (CKG origin only). Default: on.")
    p.add_argument("--no-train", dest="train", action="store_false",
                   help="Disable train+fly options.")
    p.add_argument("--sort", choices=["cost", "duration"], default="cost",
                   help="Sort ranking by cost or duration (default cost)")
    p.add_argument("--top", type=int, default=10,
                   help="Show top N results (default 10)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Kick off FX refresh as early as possible.
    currency.start_background_refresh()

    print(f"Mode: {'MOCK pricing' if pricer.USE_MOCK else 'LIVE fli pricing'}")
    print(f"Searching {args.origin} → {args.destination} on {args.date} "
          f"(max_stops={args.max_stops}, train={args.train})")
    print("=" * 90)

    cands = generate_candidates(
        args.origin, args.destination,
        max_stops=args.max_stops, include_train=args.train,
    )
    print(f"Generated {len(cands)} candidate(s). Pricing...")

    priced = pricer.price_candidates(cands, date=args.date)

    if args.sort == "duration":
        ranked = pricer.rank_by_duration(priced)
    else:
        ranked = pricer.rank_by_cost(priced)

    print()
    print(pricer.format_results(ranked, top_n=args.top, sort_by=args.sort))
    print()
    print(f"[FX source: {currency.get_source()}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
