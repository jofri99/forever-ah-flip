"""Tests der Verdichtung und des Vergleichs - echtes DuckDB, echte Dateien, kein Netz."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from collector import store
from collector.blizzard import ApiResponse
from collector.collect import aggregate_items, diff_sales, load_snapshot, run, summary
from collector.config import Settings

T0 = dt.datetime(2026, 11, 14, 10, 0, 0)
T1 = dt.datetime(2026, 11, 14, 11, 0, 0)


class FakeClient:
    """Spielt die API nach: liefert vorbereitete Staende und beantwortet
    If-Modified-Since wie Blizzard mit 304."""

    def __init__(self) -> None:
        self.stamp: dt.datetime | None = None
        self.auction_payload: dict = {}
        self.commodity_payload: dict = {}
        self.seen_if_modified_since: list[str | None] = []
        self.downloads = 0

    def serve(self, stamp: dt.datetime, auctions: dict, commodities: dict) -> None:
        self.stamp, self.auction_payload, self.commodity_payload = stamp, auctions, commodities

    def _respond(self, payload: dict, stream_to: Path | None) -> ApiResponse:
        raw = json.dumps(payload).encode("utf-8")
        if stream_to is not None:
            stream_to.parent.mkdir(parents=True, exist_ok=True)
            stream_to.write_bytes(raw)
        self.downloads += 1
        return ApiResponse(
            status=200,
            url="fake",
            headers={"last-modified": store.http_date(self.stamp)},
            size=len(raw),
            path=stream_to,
        )

    def auctions(self, ruleset, house, stream_to=None, if_modified_since=None) -> ApiResponse:
        self.seen_if_modified_since.append(if_modified_since)
        if if_modified_since == store.http_date(self.stamp):
            return ApiResponse(status=304, url="fake")
        return self._respond(self.auction_payload, stream_to)

    def commodities(self, ruleset, house, stream_to=None, if_modified_since=None) -> ApiResponse:
        return self._respond(self.commodity_payload, stream_to)

    def close(self) -> None:
        pass

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


def test_snapshot_path_and_latest_snapshot(tmp_path: Path) -> None:
    assert store.latest_snapshot(tmp_path, 114) is None

    first = store.snapshot_path(tmp_path, store.ITEMS, 114, T0)
    assert first.relative_to(tmp_path).as_posix() == "items/house=114/dt=2026-11-14/100000.parquet"

    for stamp in (T0, T1, dt.datetime(2026, 11, 13, 23, 19, 11)):
        path = store.snapshot_path(tmp_path, store.ITEMS, 114, stamp)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    # Ein anderes Haus darf nicht mitzaehlen.
    other = store.snapshot_path(tmp_path, store.ITEMS, 113, dt.datetime(2026, 12, 1, 0, 0, 0))
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_bytes(b"")

    assert store.latest_snapshot(tmp_path, 114) == T1


def test_http_date_matches_what_the_api_sends() -> None:
    assert store.http_date(dt.datetime(2026, 11, 14, 19, 19, 11)) == "Sat, 14 Nov 2026 19:19:11 GMT"


def test_run_end_to_end_over_two_snapshots(settings: Settings) -> None:
    client = FakeClient()
    warehouse = settings.warehouse_dir
    state = settings.state_dir / "house114.parquet"

    # Erster Stand: nichts zum Vergleichen, also keine Verkaeufe.
    client.serve(T0, SNAPSHOT_A, COMMODITIES_A)
    first = run(settings, client=client)

    assert not first["skipped"]
    assert (first["auctions"], first["commodities"], first["items"]) == (3, 2, 3)
    assert "previous_ts" not in first
    assert store.snapshot_path(warehouse, store.ITEMS, 114, T0).exists()
    assert not store.snapshot_path(warehouse, store.SALES, 114, T0).exists()
    assert store.snapshot_path(warehouse, store.RUNS, 114, T0).exists()
    assert state.exists()
    assert client.seen_if_modified_since == [None]

    # Zweiter Lauf ohne neue Daten: 304, kein Download, keine neue Datei.
    downloads = client.downloads
    again = run(settings, client=client)

    assert again["skipped"] and again["reason"] == "unveraendert"
    assert client.seen_if_modified_since[-1] == "Sat, 14 Nov 2026 10:00:00 GMT"
    assert client.downloads == downloads
    assert len(list(warehouse.rglob("*.parquet"))) == 2

    # Neuer Stand eine Stunde spaeter: jetzt entstehen Verkaeufe.
    client.serve(T1, SNAPSHOT_B, COMMODITIES_B)
    second = run(settings, client=client)

    assert not second["skipped"]
    assert second["previous_ts"] == T0
    assert second["gap_hours"] == 1.0
    assert (second["sold"], second["expired"], second["unclear"], second["new"]) == (1, 1, 1, 1)
    assert second["value_sold"] == 500
    assert store.snapshot_path(warehouse, store.SALES, 114, T1).exists()
    assert "1 verkauft" in summary(second)

    # Der Vergleichsstand ist jetzt der neue.
    con = store.connect()
    try:
        assert store.read_parquet(con, state, "prev") == 3
        assert con.execute("SELECT max(snapshot_ts) FROM prev").fetchone()[0] == T1
        # Das Warehouse laesst sich als Ganzes lesen, Haus und Tag kommen aus dem Pfad.
        glob = store.sql_path(warehouse / "items" / "*" / "*" / "*.parquet")
        stamps = con.execute(
            f"SELECT count(DISTINCT snapshot_ts), count(*) FROM read_parquet('{glob}')"
        ).fetchone()
        assert stamps == (2, 6)
    finally:
        con.close()

    # Nichts Rohes bleibt liegen.
    assert not (settings.raw_dir / "current").exists()


def test_run_skips_a_snapshot_that_is_already_stored(settings: Settings) -> None:
    client = FakeClient()
    client.serve(T0, SNAPSHOT_A, COMMODITIES_A)
    run(settings, client=client)

    # --force umgeht If-Modified-Since, der Stand ist aber derselbe.
    forced = run(settings, client=client, force=True)
    assert not forced["skipped"]

    # Ohne force und ohne 304 - etwa wenn der Server den Header ignoriert.
    client.auctions = lambda ruleset, house, stream_to=None, if_modified_since=None: client._respond(  # type: ignore[method-assign]
        client.auction_payload, stream_to
    )
    repeated = run(settings, client=client)
    assert repeated["skipped"] and repeated["reason"] == "schon verarbeitet"


def test_pointer_roundtrip_and_precedence(tmp_path: Path) -> None:
    assert store.read_pointer(tmp_path, 114) is None

    path = store.write_pointer(tmp_path, 114, T0)
    assert path.relative_to(tmp_path).as_posix() == "latest/house=114.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "house": 114,
        "snapshot_ts": "2026-11-14T10:00:00",
        "items": "items/house=114/dt=2026-11-14/100000.parquet",
    }
    assert store.latest_snapshot(tmp_path, 114) == T0

    # Liegt eine juengere Datei auf der Platte als der Zeiger sagt, gewinnt die Datei.
    newer = store.snapshot_path(tmp_path, store.ITEMS, 114, T1)
    newer.parent.mkdir(parents=True, exist_ok=True)
    newer.write_bytes(b"")
    assert store.latest_snapshot(tmp_path, 114) == T1

    # Ein kaputter Zeiger ist kein Absturz, sondern einfach kein Zeiger.
    path.write_text("kein json", encoding="utf-8")
    assert store.read_pointer(tmp_path, 114) is None


def test_run_works_when_only_the_pointer_is_checked_out(settings: Settings) -> None:
    """Wie in Actions: vom Branch data liegt nur latest/ auf der Platte."""
    import shutil

    client = FakeClient()
    warehouse = settings.warehouse_dir

    client.serve(T0, SNAPSHOT_A, COMMODITIES_A)
    run(settings, client=client)
    assert store.read_pointer(warehouse, 114) == T0

    # Ausschnitt-Checkout nachstellen: alle Daten weg, nur der Zeiger bleibt.
    for dataset in (store.ITEMS, store.SALES, store.RUNS):
        shutil.rmtree(warehouse / dataset, ignore_errors=True)

    # Unveraendert: der Zeiger liefert das Datum fuer If-Modified-Since.
    again = run(settings, client=client)
    assert again["skipped"] and again["reason"] == "unveraendert"
    assert client.seen_if_modified_since[-1] == "Sat, 14 Nov 2026 10:00:00 GMT"

    # Ignoriert der Server den Header, darf derselbe Stand trotzdem nicht doppelt entstehen.
    honest_auctions = client.auctions
    client.auctions = lambda ruleset, house, stream_to=None, if_modified_since=None: client._respond(  # type: ignore[method-assign]
        client.auction_payload, stream_to
    )
    repeated = run(settings, client=client)
    assert repeated["skipped"] and repeated["reason"] == "schon verarbeitet"
    assert not (warehouse / store.ITEMS).exists()
    client.auctions = honest_auctions  # type: ignore[method-assign]

    # Ein neuer Stand wird geschrieben, mit Verkaeufen, und der Zeiger rueckt vor.
    client.serve(T1, SNAPSHOT_B, COMMODITIES_B)
    second = run(settings, client=client)
    assert not second["skipped"]
    assert second["sold"] == 1
    assert store.snapshot_path(warehouse, store.ITEMS, 114, T1).exists()
    assert store.snapshot_path(warehouse, store.SALES, 114, T1).exists()
    assert store.read_pointer(warehouse, 114) == T1
