"""Tests der Verdichtung und des Vergleichs - echtes DuckDB, echte Dateien, kein Netz."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from collector import store
from collector.collect import aggregate_items, diff_sales, load_snapshot

T0 = dt.datetime(2026, 11, 14, 10, 0, 0)
T1 = dt.datetime(2026, 11, 14, 11, 0, 0)

SNAPSHOT_A = {
    "id": 114,
    "name": "Auktionshaus der Horde",
    "auctions": [
        {"id": 1, "item": {"id": 100}, "buyout": 500, "quantity": 1, "time_left": "LONG"},
        {"id": 2, "item": {"id": 100}, "buyout": 700, "quantity": 1, "time_left": "SHORT"},
        {"id": 3, "item": {"id": 200}, "bid": 300, "buyout": 0, "quantity": 1, "time_left": "VERY_LONG"},
    ],
}
COMMODITIES_A = {
    "auctions": [
        {"id": 10, "item": {"id": 300}, "unit_price": 95, "quantity": 20, "time_left": "MEDIUM"},
        {"id": 11, "item": {"id": 300}, "unit_price": 90, "quantity": 5, "time_left": "LONG"},
    ]
}
SNAPSHOT_B = {
    "id": 114,
    "auctions": [
        {"id": 3, "item": {"id": 200}, "bid": 300, "buyout": 0, "quantity": 1, "time_left": "VERY_LONG"},
        {"id": 4, "item": {"id": 100}, "buyout": 600, "quantity": 1, "time_left": "VERY_LONG"},
    ],
}
COMMODITIES_B = {
    "auctions": [
        {"id": 11, "item": {"id": 300}, "unit_price": 90, "quantity": 5, "time_left": "LONG"},
    ]
}


def write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def con():
    connection = store.connect()
    yield connection
    connection.close()


def test_load_snapshot_merges_auctions_and_commodities(con, tmp_path: Path) -> None:
    rows = load_snapshot(
        con, write(tmp_path / "a.json", SNAPSHOT_A), write(tmp_path / "c.json", COMMODITIES_A)
    )

    assert rows == 5
    kinds = dict(con.execute("SELECT kind, count(*) FROM snap GROUP BY kind").fetchall())
    assert kinds == {"auction": 3, "commodity": 2}

    # Der Stueckpreis kommt bei Auktionen aus buyout, bei Stapelware aus unit_price.
    assert con.execute("SELECT unit_price FROM snap WHERE auction_id = 1").fetchone()[0] == 500
    assert con.execute("SELECT unit_price, quantity FROM snap WHERE auction_id = 10").fetchone() == (95, 20)
    # bid steht nur bei den wenigen Auktionen mit Gebot - die Spalte darf nicht fehlen.
    assert con.execute("SELECT bid FROM snap WHERE auction_id = 3").fetchone()[0] == 300
    assert con.execute("SELECT bid FROM snap WHERE auction_id = 1").fetchone()[0] is None


def test_load_snapshot_without_commodities(con, tmp_path: Path) -> None:
    assert load_snapshot(con, write(tmp_path / "a.json", SNAPSHOT_A), None) == 3


def test_aggregate_items(con, tmp_path: Path) -> None:
    load_snapshot(
        con, write(tmp_path / "a.json", SNAPSHOT_A), write(tmp_path / "c.json", COMMODITIES_A)
    )
    assert aggregate_items(con, T0, 114) == 3

    rows = {
        (r[0], r[1]): r[2:]
        for r in con.execute(
            "SELECT item_id, kind, n_listings, quantity, min_price, median_price, "
            "total_value, n_bid FROM items"
        ).fetchall()
    }

    assert rows[(100, "auction")] == (2, 2, 500, 600, 1200, 0)
    # Auktionen ohne Sofortkauf zaehlen mit, liefern aber keinen Preis.
    assert rows[(200, "auction")] == (1, 1, None, None, 0, 1)
    assert rows[(300, "commodity")] == (2, 25, 90, 93, 2350, 0)

    assert con.execute("SELECT DISTINCT snapshot_ts, house FROM items").fetchone() == (T0, 114)


def test_diff_sales_classifies_by_remaining_time(con, tmp_path: Path) -> None:
    load_snapshot(
        con, write(tmp_path / "a.json", SNAPSHOT_A), write(tmp_path / "ca.json", COMMODITIES_A)
    )
    con.execute("CREATE OR REPLACE TEMP TABLE prev AS SELECT * FROM snap")
    load_snapshot(
        con, write(tmp_path / "b.json", SNAPSHOT_B), write(tmp_path / "cb.json", COMMODITIES_B)
    )

    assert diff_sales(con, T1, T0, 114) == 2

    rows = {
        (r[0], r[1]): r[2:]
        for r in con.execute(
            "SELECT item_id, kind, n_sold, qty_sold, value_sold, n_expired, n_unclear, "
            "n_new, qty_new FROM sales"
        ).fetchall()
    }

    # Auktion 1 lief noch mindestens zwei Stunden, kann nach einer Stunde also nicht
    # abgelaufen sein. Auktion 2 stand auf SHORT. Auktion 4 ist neu.
    assert rows[(100, "auction")] == (1, 1, 500, 1, 0, 1, 1)
    # Stapelware 10 stand auf MEDIUM: nach einer Stunde nicht mehr zu entscheiden.
    assert rows[(300, "commodity")] == (0, 0, 0, 0, 1, 0, 0)

    assert con.execute("SELECT DISTINCT gap_hours FROM sales").fetchone()[0] == 1.0


def test_long_counts_as_sold_only_within_two_hours(con, tmp_path: Path) -> None:
    load_snapshot(con, write(tmp_path / "a.json", SNAPSHOT_A), None)
    con.execute("CREATE OR REPLACE TEMP TABLE prev AS SELECT * FROM snap")
    load_snapshot(con, write(tmp_path / "b.json", SNAPSHOT_B), None)

    # Liegen drei Stunden zwischen den Staenden, haette LONG ablaufen koennen.
    diff_sales(con, T0 + dt.timedelta(hours=3), T0, 114)

    row = con.execute(
        "SELECT n_sold, n_unclear FROM sales WHERE item_id = 100 AND kind = 'auction'"
    ).fetchone()
    assert row == (0, 1)


def test_append_parquet_grows_the_day_file(con, tmp_path: Path) -> None:
    load_snapshot(con, write(tmp_path / "a.json", SNAPSHOT_A), None)
    aggregate_items(con, T0, 114)
    path = store.dataset_path(tmp_path / "warehouse", store.ITEMS, T0.date())

    assert store.append_parquet(con, "items", path, "item_id") == 2

    aggregate_items(con, T1, 114)
    assert store.append_parquet(con, "items", path, "item_id") == 4
    assert path.name == "dt=2026-11-14.parquet"

    stamps = con.execute(
        f"SELECT count(DISTINCT snapshot_ts) FROM read_parquet('{store.sql_path(path)}')"
    ).fetchone()[0]
    assert stamps == 2
