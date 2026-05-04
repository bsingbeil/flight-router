"""Test the CLI argument parser and dispatch — without hitting the live API."""
import pytest

import pricer
from cli import build_parser, main


def test_parser_required_args():
    parser = build_parser()
    args = parser.parse_args(["CKG", "VIE", "2026-09-15"])
    assert args.origin == "CKG"
    assert args.destination == "VIE"
    assert args.date == "2026-09-15"
    assert args.max_stops == 1
    assert args.train is True
    assert args.sort == "cost"


def test_parser_overrides():
    parser = build_parser()
    args = parser.parse_args([
        "CKG", "VIE", "2026-09-15",
        "--max-stops", "2",
        "--no-train",
        "--sort", "duration",
        "--top", "5",
    ])
    assert args.max_stops == 2
    assert args.train is False
    assert args.sort == "duration"
    assert args.top == 5


def test_main_runs_against_mock(monkeypatch, capsys):
    """End-to-end CLI run with mock pricing — should print a ranked table."""
    monkeypatch.setattr(pricer, "USE_MOCK", True)
    # Re-bind _fli_search since pricer caches the choice at import time.
    monkeypatch.setattr(pricer, "_fli_search", pricer._mock_fli_search)
    rc = main(["CKG", "BKK", "2026-09-15", "--no-train", "--top", "3"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "CKG" in out and "BKK" in out
    assert "savings/hr" in out
