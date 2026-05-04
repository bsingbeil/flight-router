"""Contract tests for connections.py."""
import pytest

from connections import (
    TrainConnection, TRAIN_CONNECTIONS,
    get_train_connections_from, get_train_connection,
)
from nodes import NODES


def test_traintconnection_is_dataclass():
    tc = TrainConnection(
        origin="CKG-N", destination="CTU",
        duration_min=75, cost_cny_2nd_class=153,
        frequency="every 30min", notes="ok",
    )
    assert tc.origin == "CKG-N"
    assert tc.cost_cny_2nd_class == 153


def test_train_connections_is_a_list_of_train_connection():
    assert isinstance(TRAIN_CONNECTIONS, list)
    assert len(TRAIN_CONNECTIONS) >= 1
    assert all(isinstance(t, TrainConnection) for t in TRAIN_CONNECTIONS)


def test_every_endpoint_exists_in_nodes():
    """Every origin and destination must be a known node."""
    for tc in TRAIN_CONNECTIONS:
        assert tc.origin in NODES, f"unknown origin: {tc.origin}"
        assert tc.destination in NODES, f"unknown destination: {tc.destination}"


def test_get_train_connections_from():
    conns = get_train_connections_from("CKG-N")
    assert all(c.origin == "CKG-N" for c in conns)
    assert len(conns) >= 1


def test_get_train_connections_from_unknown_origin():
    assert get_train_connections_from("ZZZ") == []


def test_get_train_connection_specific():
    """If a CKG-N → CTU connection exists, lookup must find it."""
    direct = next(
        (c for c in TRAIN_CONNECTIONS
         if c.origin == "CKG-N" and c.destination == "CTU"),
        None,
    )
    if direct is not None:
        found = get_train_connection("CKG-N", "CTU")
        assert found is direct


def test_get_train_connection_missing_returns_none():
    assert get_train_connection("CKG-N", "ZZZ") is None
