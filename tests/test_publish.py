"""Tests fuer die Anzeige-Dateien - ein kleines Warehouse aus echten Parquet-Dateien."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from collector import foreverdb_dump, publish, store
from collector.config import Settings

T0 = dt.datetime(2026, 11, 14, 10, 0, 0)
T1 = dt.datetime(2026, 11, 14, 11, 0, 0)
T2 = dt.datetime(2026, 11, 14, 12, 0, 0)
OLD = T0 - dt.timedelta(days=30)


def epoch(ts: dt.datetime) -> int:
    return int(ts.replace(tzinfo=dt.timezone.utc).timestamp())


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env(
        {"BLIZZARD_CLIENT_ID": "x", "BLIZZARD_CLIENT_SECRET": "x", "AH_DATA_DIR": str(tmp_path / "data")}
    )


def write_items(settings: Settings, ts: dt.datetime, rows: list[tuple]) -> None:
    """rows: (item_id, kind, n_listings, quantity, min_price, median_price)"""
    con = store.connect()
    try:
        con.execute(
            "CREATE TEMP TABLE t (snapshot_ts TIMESTAMP, house INTEGER, item_id INTEGER, kind VARCHAR, "
            "n_listings INTEGER, quantity BIGINT, min_price BIGINT, p25_price BIGINT, "
            "median_price BIGINT, total_value BIGINT, n_bid INTEGER)"
        )
        for item_id, kind, n_listings, quantity, min_price, median_price in rows:
            con.execute(
                "INSERT INTO t VALUES (?, 114, ?, ?, ?, ?, ?, ?, ?, 0, 0)",
                [ts, item_id, kind, n_listings, quantity, min_price, min_price, median_price],
            )
        store.write_parquet(con, "t", store.snapshot_path(settings.warehouse_dir, store.ITEMS, 114, ts))
    finally:
        con.close()


def write_sales(settings: Settings, ts: dt.datetime, rows: list[tuple]) -> None:
    """rows: (item_id, kind, n_sold, qty_sold, value_sold)"""
    con = store.connect()
    try:
        con.execute(
            "CREATE TEMP TABLE t (snapshot_ts TIMESTAMP, previous_ts TIMESTAMP, gap_hours DOUBLE, "
            "house INTEGER, item_id INTEGER, kind VARCHAR, n_sold INTEGER, qty_sold BIGINT, "
            "value_sold BIGINT, n_expired INTEGER, n_unclear INTEGER, n_new INTEGER, qty_new BIGINT)"
        )
        for item_id, kind, n_sold, qty_sold, value_sold in rows:
            con.execute(
                "INSERT INTO t VALUES (?, ?, 1.0, 114, ?, ?, ?, ?, ?, 0, 0, 0, 0)",
                [ts, ts - dt.timedelta(hours=1), item_id, kind, n_sold, qty_sold, value_sold],
            )
        store.write_parquet(con, "t", store.snapshot_path(settings.warehouse_dir, store.SALES, 114, ts))
    finally:
        con.close()


@pytest.fixture
def warehouse(settings: Settings) -> Settings:
    write_items(settings, T0, [(100, "auction", 2, 2, 500, 600), (300, "commodity", 2, 25, 90, 93)])
    write_items(settings, T1, [(100, "auction", 3, 3, 450, 600), (300, "commodity", 3, 40, 80, 90)])
    write_items(settings, T2, [(100, "auction", 2, 2, 550, 650), (300, "commodity", 1, 10, 99, 99)])
    write_sales(settings, T1, [(100, "auction", 1, 1, 500), (300, "commodity", 2, 12, 1080)])
    write_sales(settings, T2, [(300, "commodity", 3, 30, 2400)])
    return settings


def query(path: Path, sql: str) -> list[tuple]:
    con = store.connect()
    try:
        return con.execute(sql.replace("FILE", f"'{store.sql_path(path)}'")).fetchall()
    finally:
        con.close()


def test_hourly_is_sorted_by_item_and_joined_with_sales(warehouse: Settings, tmp_path: Path) -> None:
    out = tmp_path / "site"
    meta = publish.build(warehouse, out_dir=out)

    rows = query(out / publish.HOURLY, "SELECT item_id, kind, ts, min_price, qty_sold, value_sold FROM FILE")

    # Reihenfolge in der Datei: erst Item, dann Zeit. Daran haengt das gezielte Lesen.
    assert [(r[0], r[2]) for r in rows] == [
        (100, epoch(T0)), (100, epoch(T1)), (100, epoch(T2)),
        (300, epoch(T0)), (300, epoch(T1)), (300, epoch(T2)),
    ]
    # Verkaeufe haengen am richtigen Stand; wo es keinen Vergleich gab, steht NULL statt 0.
    assert rows[0][4:] == (None, None)
    assert rows[1][4:] == (1.0, 500.0)
    assert rows[2][4:] == (None, None)
    assert rows[4][4:] == (12.0, 1080.0)
    assert rows[5][4:] == (30.0, 2400.0)

    assert meta["snapshots"] == 3
    assert meta["snapshots_with_sales"] == 2
    assert meta["files"][publish.HOURLY]["rows"] == 6


def test_hourly_types_arrive_as_plain_numbers_in_a_browser(warehouse: Settings, tmp_path: Path) -> None:
    out = tmp_path / "site"
    publish.build(warehouse, out_dir=out)

    types = dict(query(out / publish.HOURLY, "SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM FILE)"))

    # Kein BIGINT (waere im Browser BigInt) und kein TIMESTAMP (waere ein Datumsobjekt).
    assert "BIGINT" not in types.values()
    assert "TIMESTAMP" not in types.values()
    assert types["ts"] == "INTEGER"
    assert types["min_price"] == "DOUBLE"

    codecs = {r[0] for r in query(out / publish.HOURLY, "SELECT DISTINCT compression FROM parquet_metadata(FILE)")}
    assert codecs == {"SNAPPY"}


def test_market_has_latest_snapshot_and_24h_figures(warehouse: Settings, tmp_path: Path) -> None:
    out = tmp_path / "site"
    publish.build(warehouse, out_dir=out)

    rows = {
        r[0]: r[1:]
        for r in query(
            out / publish.MARKET,
            "SELECT item_id, ts, min_price, qty_sold_24h, value_sold_24h, sales_hours_24h, "
            "low_24h, high_24h, open_24h, change_24h_pct, snapshots_24h FROM FILE",
        )
    }

    assert set(rows) == {100, 300}
    # Item 100: juengster Preis 550, vor 24 h (hier: erster Stand) 500 -> +10 %.
    assert rows[100] == (epoch(T2), 550.0, 1.0, 500.0, 1.0, 450.0, 550.0, 500.0, 10.0, 3)
    # Item 300: Verkaeufe aus zwei Vergleichen aufsummiert, zwei Stunden gedeckt.
    assert rows[300] == (epoch(T2), 99.0, 42.0, 3480.0, 2.0, 80.0, 99.0, 90.0, 10.0, 3)


def test_window_excludes_old_snapshots(warehouse: Settings, tmp_path: Path) -> None:
    write_items(warehouse, OLD, [(100, "auction", 9, 9, 1, 1)])
    out = tmp_path / "site"

    meta = publish.build(warehouse, out_dir=out, days=14)
    assert meta["snapshots"] == 3
    assert meta["first_snapshot"] == "2026-11-14T10:00:00Z"

    meta = publish.build(warehouse, out_dir=out, days=60)
    assert meta["snapshots"] == 4


def test_works_without_any_sales_files(settings: Settings, tmp_path: Path) -> None:
    write_items(settings, T0, [(100, "auction", 2, 2, 500, 600)])
    out = tmp_path / "site"

    meta = publish.build(settings, out_dir=out)

    assert meta["snapshots_with_sales"] == 0
    assert query(out / publish.HOURLY, "SELECT qty_sold, n_sold FROM FILE") == [(None, None)]
    assert query(out / publish.MARKET, "SELECT qty_sold_24h, sales_hours_24h FROM FILE") == [(None, None)]


def test_meta_json_describes_the_build(warehouse: Settings, tmp_path: Path) -> None:
    out = tmp_path / "site"
    publish.build(warehouse, out_dir=out)

    meta = json.loads((out / publish.META).read_text(encoding="utf-8"))

    assert meta["house"] == 114
    assert meta["last_snapshot"] == "2026-11-14T12:00:00Z"
    assert meta["items"] == 2
    assert meta["files"][publish.HOURLY]["sorted_by"] == ["item_id", "kind", "ts"]
    assert meta["files"][publish.HOURLY]["bytes"] == (out / publish.HOURLY).stat().st_size

    # Ohne names.json fragt die Seite gar nicht erst danach.
    assert meta["names"] is False
    (out / publish.NAMES).write_text('{"100": "Testitem"}', encoding="utf-8")
    assert publish.build(warehouse, out_dir=out)["names"] is True


def test_empty_warehouse_is_a_clear_error(settings: Settings, tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="noch kein Stand"):
        publish.build(settings, out_dir=tmp_path / "site")


def test_vendor_flips_exist_only_with_a_local_vendor_dump(warehouse: Settings, tmp_path: Path) -> None:
    out = tmp_path / "site"

    # Ohne Abzug der Haendler - so laeuft es in Actions - gibt es die Datei nicht.
    meta = publish.build(warehouse, out_dir=out)
    assert meta["vendor_flips"] is None
    assert not (out / publish.VENDOR_FLIPS).exists()

    # Item 100 steht im Auktionshaus fuer 550, Item 300 fuer 99.
    directory = foreverdb_dump.dump_dir(warehouse)
    directory.mkdir(parents=True)
    (directory / foreverdb_dump.VENDOR_DETAILS_FILE).write_text(
        '{"id":1,"name":"Horde Vendor","side":"Horde","zone":"Orgrimmar","sells":['
        '{"itemId":100,"price":200,"stack":1,"pricePerItem":200.0,"limited":true,"limitedStockCount":1,"seenInForever":true},'
        '{"itemId":300,"price":98,"stack":1,"pricePerItem":98.0,"limited":false,"seenInForever":true}]}\n'
        '{"id":2,"name":"Alliance Vendor","side":"Alliance","zone":"Stormwind","sells":['
        '{"itemId":300,"price":1,"stack":1,"pricePerItem":1.0,"limited":false,"seenInForever":true}]}\n',
        encoding="utf-8",
    )
    meta = publish.build(warehouse, out_dir=out)
    assert meta["vendor_flips"] == 1

    rows = query(
        out / publish.VENDOR_FLIPS,
        "SELECT item_id, kind, vendor_price, ah_price, profit, profit_pct, limited, limited_stock, vendor, "
        "qty_sold_24h FROM FILE",
    )
    # Item 100: 550 * 0,95 - 200 = 322,5, gerundet 323. Item 300 lohnt nur beim Haendler der Allianz,
    # und der ist fuer die Horde nicht erreichbar: 99 * 0,95 liegt unter 98.
    assert rows == [(100, "auction", 200.0, 550.0, 323.0, 161.0, True, 1, "Horde Vendor", 1.0)]

    types = dict(query(out / publish.VENDOR_FLIPS, "SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM FILE)"))
    assert "BIGINT" not in types.values()

    # Verschwindet der Abzug, darf keine veraltete Datei liegen bleiben.
    (directory / foreverdb_dump.VENDOR_DETAILS_FILE).unlink()
    meta = publish.build(warehouse, out_dir=out)
    assert meta["vendor_flips"] is None
    assert not (out / publish.VENDOR_FLIPS).exists()


def recipe_line(spell_id: int, name: str, item_id: int, count: int, reagents: str) -> str:
    return (
        f'{{"spellId":{spell_id},"name":"{name}","category":{{"id":1,"name":"Bars"}},"skill":{{"orange":50}},'
        f'"makes":{{"itemId":{item_id},"name":"{name}","count":{count}}},"reagents":{reagents},'
        '"learnedFrom":{"automatic":false,"trainer":{"cost":100,"trainers":2},"recipeItems":[],"sources":{"ways":["trainer"]}},'
        '"newInForever":false,"profession":"mining","professionName":"Mining"}\n'
    )


def test_crafts_exist_only_with_a_local_recipe_dump(warehouse: Settings, tmp_path: Path) -> None:
    out = tmp_path / "site"

    # Ohne Abzug der Rezepte - so laeuft es in Actions - gibt es die Dateien nicht.
    meta = publish.build(warehouse, out_dir=out)
    assert meta["crafts"] is None
    assert not (out / publish.CRAFTS).exists()
    assert not (out / publish.CRAFT_REAGENTS).exists()

    # Im Auktionshaus steht Item 100 fuer 550 und Item 300 fuer 99.
    directory = foreverdb_dump.dump_dir(warehouse)
    directory.mkdir(parents=True)
    (directory / foreverdb_dump.RECIPES_FILE).write_text(
        recipe_line(1, "Big Bar", 100, 1, '[{"itemId":300,"name":"Ore","count":3}]')
        + recipe_line(2, "Ore Dust", 300, 5, '[{"itemId":100,"name":"Big Bar","count":1}]')
        # Was dabei herauskommt, steht nicht im Auktionshaus: nichts fuer die Anzeige.
        + recipe_line(3, "Unsold", 999, 1, '[{"itemId":300,"name":"Ore","count":1}]'),
        encoding="utf-8",
    )
    meta = publish.build(warehouse, out_dir=out)
    assert meta["crafts"] == 2

    rows = query(
        out / publish.CRAFTS,
        "SELECT recipe_id, name, profession, category, skill, item_id, kind, item_count, reagents, unpriced, "
        "cost, ah_price, profit, profit_pct, qty_sold_24h, learned, trainer_cost FROM FILE ORDER BY recipe_id",
    )
    assert rows == [
        # 3 * 99 = 297 Kosten, 550 * 0,95 = 522,5 Erloes.
        (1, "Big Bar", "Mining", "Bars", 50, 100, "auction", 1.0, 1, 0, 297.0, 550.0, 226.0, 76.0, 1.0, "trainer", 100.0),
        # Fuenf Stueck je Durchgang: 5 * 99 * 0,95 = 470,25 Erloes gegen 550 Kosten - ein Verlust.
        (2, "Ore Dust", "Mining", "Bars", 50, 300, "commodity", 5.0, 1, 0, 550.0, 99.0, -80.0, -15.0, 42.0, "trainer", 100.0),
    ]
    # In der Datei steht das lohnendste Rezept zuerst.
    assert query(out / publish.CRAFTS, "SELECT recipe_id FROM FILE") == [(1,), (2,)]

    assert query(
        out / publish.CRAFT_REAGENTS,
        "SELECT recipe_id, item_id, name, count, unit_price, source, vendor FROM FILE",
    ) == [(1, 300, "Ore", 3, 99.0, "ah", None), (2, 100, "Big Bar", 1, 550.0, "ah", None)]

    for file in (publish.CRAFTS, publish.CRAFT_REAGENTS):
        types = dict(query(out / file, "SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM FILE)"))
        assert "BIGINT" not in types.values(), file

    # Verschwindet der Abzug, darf keine veraltete Datei liegen bleiben.
    (directory / foreverdb_dump.RECIPES_FILE).unlink()
    meta = publish.build(warehouse, out_dir=out)
    assert meta["crafts"] is None
    assert not (out / publish.CRAFTS).exists()
    assert not (out / publish.CRAFT_REAGENTS).exists()
