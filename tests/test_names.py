"""Tests fuer die Stammdaten - gefaelschte API, echte Parquet-Dateien."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path

import pytest

from collector import names, publish, store
from collector.blizzard import ApiResponse
from collector.config import Settings

NOW = dt.datetime(2026, 11, 17, 12, 0, 0)

CATALOG = {
    2589: {
        "id": 2589,
        "name": "Leinenstoff",
        "quality": {"type": "COMMON", "name": "Gewöhnlich"},
        "sell_price": 13,
        "purchase_price": 55,
        "purchase_quantity": 1,
        "inventory_type": {"type": "NON_EQUIP", "name": "Nicht anlegbar"},
        "is_equippable": False,
        "max_count": 0,
        "preview_item": {"name": "Leinenstoff", "sell_price": {"value": 13}},
        "_links": {"self": {"href": "https://example.invalid/item/2589"}},
        "item_class": {"id": 7, "name": "Handwerkswaren"},
        "item_subclass": {"id": 5, "name": "Stoff"},
        "level": 5,
        "required_level": 0,
        "is_stackable": True,
    },
    12359: {"id": 12359, "name": "Thoriumbarren", "quality": {"type": "COMMON"}, "sell_price": 600},
}


class FakeItems:
    """Kennt zwei Items, antwortet sonst mit 404 - und auf Wunsch mit einem Serverfehler."""

    def __init__(self) -> None:
        self.asked: list[int] = []
        self.broken: set[int] = set()

    def get(self, path: str, namespace: str = "dynamic", **_: object) -> ApiResponse:
        assert namespace == "static"
        item_id = int(path.rsplit("/", 1)[1])
        if "/media/" in path:
            if item_id == 2589:
                return ApiResponse(status=200, url=path, data={"assets": [{"key": "icon", "value": "https://example.invalid/132889.jpg"}]})
            return ApiResponse(status=404, url=path)
        self.asked.append(item_id)
        if item_id in self.broken:
            return ApiResponse(status=503, url=path)
        if item_id in CATALOG:
            return ApiResponse(status=200, url=path, data=CATALOG[item_id])
        return ApiResponse(status=404, url=path)

    def close(self) -> None:
        pass


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    config = Settings.from_env(
        {"BLIZZARD_CLIENT_ID": "x", "BLIZZARD_CLIENT_SECRET": "x", "AH_DATA_DIR": str(tmp_path / "data")}
    )
    # Der Markt: vier Items, zwei davon kennt die API.
    con = store.connect()
    try:
        con.execute(
            "CREATE TEMP TABLE t AS SELECT TIMESTAMP '2026-11-17 11:18:56' AS snapshot_ts, "
            "114 AS house, unnest([7, 2589, 12359, 99999]) AS item_id, 'auction' AS kind"
        )
        store.write_parquet(
            con, "t", store.snapshot_path(config.warehouse_dir, store.ITEMS, 114, dt.datetime(2026, 11, 17, 11, 18, 56))
        )
    finally:
        con.close()
    return config


def known_rows(settings: Settings) -> dict[int, tuple]:
    con = store.connect()
    try:
        names.load_known(con, settings.warehouse_dir, settings.locale)
        return {
            row[0]: row[1:]
            for row in con.execute(
                "SELECT item_id, status, name, quality, sell_price, item_class FROM known"
            ).fetchall()
        }
    finally:
        con.close()


def test_first_run_checks_every_item_and_records_misses(settings: Settings) -> None:
    client = FakeItems()
    result = names.run(settings, client=client, now=NOW)

    assert client.asked == [7, 2589, 12359, 99999]
    assert (result["found"], result["missing"], result["failed"]) == (2, 2, 0)
    assert result["file"].name == "dt=2026-11-17.parquet"

    rows = known_rows(settings)
    assert rows[2589] == (200, "Leinenstoff", "COMMON", 13, "Handwerkswaren")
    assert rows[12359][:2] == (200, "Thoriumbarren")
    # Auch die Fehlanzeige wird festgehalten - sonst fragt jeder Lauf erneut.
    assert rows[7] == (404, None, None, None, None)


def test_everything_the_api_returns_is_kept(settings: Settings) -> None:
    names.run(settings, client=FakeItems(), now=NOW)

    con = store.connect()
    try:
        names.load_known(con, settings.warehouse_dir)
        row = con.execute(
            "SELECT purchase_price, purchase_quantity, inventory_type, is_equippable, max_count, icon, raw "
            "FROM known WHERE item_id = 2589"
        ).fetchone()
        # Ein Feld, das keine eigene Spalte hat, laesst sich aus der ganzen Antwort ziehen.
        nested = con.execute(
            "SELECT raw->>'$.preview_item.sell_price.value' FROM known WHERE item_id = 2589"
        ).fetchone()[0]
        no_icon = con.execute("SELECT icon FROM known WHERE item_id = 12359").fetchone()[0]
    finally:
        con.close()

    assert row[:6] == (55, 1, "NON_EQUIP", False, 0, "https://example.invalid/132889.jpg")
    raw = json.loads(row[6])
    assert raw["name"] == "Leinenstoff" and raw["item_subclass"]["name"] == "Stoff"
    # Der Verweis auf sich selbst ist Ballast und bleibt draussen.
    assert "_links" not in raw
    assert nested == "13"
    # Fehlt das Icon, ist das kein Grund, das Item zu verwerfen.
    assert no_icon is None


def test_older_files_without_newer_columns_still_load(settings: Settings) -> None:
    # So sah die Ablage aus, bevor die ganze Antwort mitgespeichert wurde.
    con = store.connect()
    try:
        con.execute(
            "CREATE TEMP TABLE old AS SELECT 2589 AS item_id, 200::SMALLINT AS status, 'Leinenstoff' AS name, "
            "TIMESTAMP '2026-11-10 12:00:00' AS checked_at"
        )
        store.write_parquet(con, "old", names.day_path(settings.warehouse_dir, dt.date(2026, 11, 10)))
    finally:
        con.close()

    # Solche Dateien stammen aus der Zeit, als auf Deutsch abgerufen wurde.
    german = dataclasses.replace(settings, locale="de_DE")
    client = FakeItems()
    names.run(german, client=client, now=NOW)

    # Das schon bekannte Item wird nicht erneut gefragt, die uebrigen schon.
    assert client.asked == [7, 12359, 99999]
    rows = known_rows(german)
    assert rows[2589][:2] == (200, "Leinenstoff")
    assert len(rows) == 4


def test_changing_the_language_refetches_found_items_but_not_misses(settings: Settings) -> None:
    german = dataclasses.replace(settings, locale="de_DE")
    names.run(german, client=FakeItems(), now=NOW)

    # Umstellung auf Englisch: was es gibt, wird neu geholt. Fehlanzeigen haengen
    # nicht an der Sprache und bleiben bekannt.
    english = dataclasses.replace(settings, locale="en_US")
    client = FakeItems()
    result = names.run(english, client=client, now=NOW + dt.timedelta(hours=1))
    assert client.asked == [2589, 12359]
    assert result["found"] == 2

    # Danach ist Ruhe - und in der Tagesdatei steht jedes Item nur noch einmal.
    client = FakeItems()
    names.run(english, client=client, now=NOW + dt.timedelta(hours=2))
    assert client.asked == []

    con = store.connect()
    try:
        path = names.day_path(settings.warehouse_dir, NOW.date())
        rows = con.execute(
            f"SELECT item_id, locale, status FROM read_parquet('{store.sql_path(path)}') ORDER BY item_id"
        ).fetchall()
    finally:
        con.close()
    assert rows == [(7, "de_DE", 404), (2589, "en_US", 200), (12359, "en_US", 200), (99999, "de_DE", 404)]


def test_second_run_asks_nothing(settings: Settings) -> None:
    names.run(settings, client=FakeItems(), now=NOW)

    client = FakeItems()
    result = names.run(settings, client=client, now=NOW + dt.timedelta(hours=1))

    assert client.asked == []
    assert (result["known"], result["pending"]) == (4, 0)


def test_misses_are_retried_after_a_week_but_hits_are_not(settings: Settings) -> None:
    names.run(settings, client=FakeItems(), now=NOW)

    client = FakeItems()
    names.run(settings, client=client, now=NOW + dt.timedelta(days=6))
    assert client.asked == []

    names.run(settings, client=client, now=NOW + dt.timedelta(days=8))
    assert client.asked == [7, 99999]

    # Die spaetere Pruefung steht in der Datei ihres Tages, die juengste gilt.
    files = sorted(p.name for p in names.ref_dir(settings.warehouse_dir).glob("*.parquet"))
    assert files == ["dt=2026-11-17.parquet", "dt=2026-11-25.parquet"]
    assert len(known_rows(settings)) == 4


def test_limit_and_server_errors(settings: Settings) -> None:
    client = FakeItems()
    client.broken = {2589}

    result = names.run(settings, client=client, limit=2, now=NOW)
    assert client.asked == [7, 2589]
    assert (result["found"], result["missing"], result["failed"]) == (0, 1, 1)

    # Ein Serverfehler ist keine Fehlanzeige: das Item bleibt offen.
    client.broken = set()
    result = names.run(settings, client=client, now=NOW)
    assert client.asked[2:] == [2589, 12359, 99999]
    assert result["found"] == 2


def test_same_day_runs_extend_the_day_file(settings: Settings) -> None:
    client = FakeItems()
    names.run(settings, client=client, limit=2, now=NOW)
    names.run(settings, client=client, now=NOW + dt.timedelta(hours=1))

    files = list(names.ref_dir(settings.warehouse_dir).glob("*.parquet"))
    assert len(files) == 1
    assert len(known_rows(settings)) == 4


def test_publish_writes_names_json(settings: Settings, tmp_path: Path) -> None:
    con = store.connect()
    try:
        con.execute(
            "CREATE TEMP TABLE t AS SELECT TIMESTAMP '2026-11-17 11:18:56' AS snapshot_ts, 114 AS house, "
            "unnest([7, 2589, 12359, 99999]) AS item_id, 'auction' AS kind, 1 AS n_listings, 1::BIGINT AS quantity, "
            "100::BIGINT AS min_price, 100::BIGINT AS p25_price, 100::BIGINT AS median_price, "
            "100::BIGINT AS total_value, 0 AS n_bid"
        )
        store.write_parquet(
            con, "t", store.snapshot_path(settings.warehouse_dir, store.ITEMS, 114, dt.datetime(2026, 11, 17, 11, 18, 56))
        )
    finally:
        con.close()
    names.run(settings, client=FakeItems(), now=NOW)

    out = tmp_path / "site"
    meta = publish.build(settings, out_dir=out)

    assert meta["names"] is True
    assert meta["items_with_name"] == 2
    assert json.loads((out / publish.NAMES).read_text(encoding="utf-8")) == {
        "2589": "Leinenstoff",
        "12359": "Thoriumbarren",
    }
