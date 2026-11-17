"""Tests fuer die lokale Datenbank - echte Dateien, echtes DuckDB."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import duckdb
import pytest

from collector import db, foreverdb_dump, names, store
from collector.config import Settings

T0 = dt.datetime(2026, 11, 17, 9, 18, 54)
T1 = dt.datetime(2026, 11, 17, 10, 18, 56)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env(
        {"BLIZZARD_CLIENT_ID": "x", "BLIZZARD_CLIENT_SECRET": "x", "AH_DATA_DIR": str(tmp_path / "data")}
    )


def write(settings: Settings, sql: str, path: Path) -> None:
    con = store.connect()
    try:
        con.execute(f"CREATE TEMP TABLE t AS {sql}")
        store.write_parquet(con, "t", path)
    finally:
        con.close()


@pytest.fixture
def filled(settings: Settings) -> Settings:
    warehouse = settings.warehouse_dir
    for ts, price in ((T0, 500), (T1, 450)):
        write(
            settings,
            f"SELECT TIMESTAMP '{ts}' AS snapshot_ts, 114 AS house, unnest([647, 2589]) AS item_id, "
            f"unnest(['auction', 'commodity']) AS kind, 3 AS n_listings, 30::BIGINT AS quantity, "
            f"unnest([{price}, 24])::BIGINT AS min_price, 0::BIGINT AS p25_price, "
            f"unnest([{price}, 35])::BIGINT AS median_price, 0::BIGINT AS total_value, 0 AS n_bid",
            store.snapshot_path(warehouse, store.ITEMS, 114, ts),
        )
    write(
        settings,
        f"SELECT TIMESTAMP '{T1}' AS snapshot_ts, TIMESTAMP '{T0}' AS previous_ts, 1.0 AS gap_hours, "
        "114 AS house, 2589 AS item_id, 'commodity' AS kind, 2 AS n_sold, 40::BIGINT AS qty_sold, "
        "123456::BIGINT AS value_sold, 0 AS n_expired, 0 AS n_unclear, 1 AS n_new, 5::BIGINT AS qty_new",
        store.snapshot_path(warehouse, store.SALES, 114, T1),
    )
    # Blizzard kennt nur den Stoff; das Schwert ist dort eine Fehlanzeige.
    write(
        settings,
        "SELECT unnest([2589, 647]) AS item_id, unnest([200, 404])::SMALLINT AS status, "
        "unnest(['Linen Cloth', NULL]) AS name, unnest(['COMMON', NULL]) AS quality, "
        "unnest([13, NULL])::BIGINT AS sell_price, unnest([55, NULL])::BIGINT AS purchase_price, "
        "unnest([1, NULL]) AS purchase_quantity, unnest(['Trade Goods', NULL]) AS item_class, "
        "unnest(['{\"preview_item\":{\"armor\":{\"value\":7}}}', NULL]) AS raw, "
        "TIMESTAMP '2026-11-17 11:00:00' AS checked_at, unnest(['en_US', NULL]) AS locale",
        names.day_path(warehouse, dt.date(2026, 11, 17)),
    )
    # ForeverDB kennt beide - das Schwert nur von dort.
    directory = foreverdb_dump.dump_dir(settings)
    directory.mkdir(parents=True)
    (directory / "items.jsonl").write_text(
        '{"id":647,"name":"Destiny","quality":"Epic","itemLevel":57,"requiredLevel":52,"class":"Weapon",'
        '"subclass":"Sword","inventoryType":"Two-Hand","icon":"https://example.invalid/a.webp","url":"https://example.invalid/item/647"}\n'
        '{"id":2589,"name":"Linen Cloth (fdb)","quality":"Common","itemLevel":5,"requiredLevel":0,"class":"Trade Goods",'
        '"subclass":"Cloth","inventoryType":"Non-equippable","icon":"https://example.invalid/b.webp","url":"https://example.invalid/item/2589"}\n',
        encoding="utf-8",
    )
    return settings


def rows(settings: Settings, sql: str) -> list[tuple]:
    con = duckdb.connect(str(db.db_path(settings)), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_build_creates_views_over_every_dataset(filled: Settings) -> None:
    result = db.build(filled)

    assert result["path"] == filled.local_dir / "forever.duckdb"
    assert result["counts"] == {
        "blizzard_items": 1,
        "foreverdb_item_details": 0,
        "foreverdb_items": 2,
        "history": 4,
        "items": 2,
        "latest": 2,
        "runs": 0,
        "sales": 1,
        "snapshots": 4,
        "sold_daily": 1,
    }
    assert result["present"]["runs"] is False


def test_items_prefers_blizzard_and_fills_gaps_from_foreverdb(filled: Settings) -> None:
    db.build(filled)

    got = {
        r[0]: r[1:]
        for r in rows(
            filled,
            "SELECT item_id, name, quality, item_class, inventory_type, vendor_sell, vendor_buy, "
            "in_blizzard, in_foreverdb FROM items",
        )
    }
    # Den Stoff kennen beide: Blizzards Angaben gelten, Haendlerpreise kommen von dort.
    assert got[2589] == ("Linen Cloth", "COMMON", "Trade Goods", "NON_EQUIPPABLE", 13, 55.0, True, True)
    # Das Schwert kennt nur ForeverDB: Name und Einordnung von dort, Qualitaet einheitlich gross.
    assert got[647] == ("Destiny", "EPIC", "Weapon", "TWO_HAND", None, None, False, True)


def test_latest_and_history_join_names_and_sales(filled: Settings) -> None:
    db.build(filled)

    latest = rows(filled, "SELECT item_id, name, min_price, vendor_sell FROM latest ORDER BY item_id")
    assert latest == [(647, "Destiny", 450, None), (2589, "Linen Cloth", 24, 13)]

    history = rows(
        filled, "SELECT snapshot_ts, qty_sold, n_sold FROM history WHERE item_id = 2589 ORDER BY snapshot_ts"
    )
    # Fuer den ersten Stand gab es keinen Vergleich: NULL, nicht 0.
    assert history == [(T0, None, None), (T1, 40, 2)]

    daily = rows(filled, "SELECT day, name, qty_sold, value_sold, hours_covered FROM sold_daily")
    assert daily == [(dt.date(2026, 11, 17), "Linen Cloth", 40, 123456, 1.0)]


def test_money_macro_and_json_access(filled: Settings) -> None:
    db.build(filled)

    assert rows(filled, "SELECT money(123456), money(2049), money(24), money(NULL), gold(123456)") == [
        ("12g 34s 56c", "20s 49c", "24c", None, 12.35)
    ]
    assert rows(filled, "SELECT raw->>'$.preview_item.armor.value' FROM blizzard_items") == [("7",)]


def test_views_follow_new_files_without_rebuilding(filled: Settings) -> None:
    db.build(filled)
    later = T1 + dt.timedelta(hours=1)
    write(
        filled,
        f"SELECT TIMESTAMP '{later}' AS snapshot_ts, 114 AS house, 2589 AS item_id, 'commodity' AS kind, "
        "1 AS n_listings, 1::BIGINT AS quantity, 20::BIGINT AS min_price, 0::BIGINT AS p25_price, "
        "20::BIGINT AS median_price, 0::BIGINT AS total_value, 0 AS n_bid",
        store.snapshot_path(filled.warehouse_dir, store.ITEMS, 114, later),
    )

    # Kein neuer Aufruf von build: die Sicht schaut auf den Ordner, nicht auf eine Kopie.
    assert rows(filled, "SELECT count(*) FROM snapshots") == [(5,)]
    assert rows(filled, "SELECT item_id, min_price FROM latest") == [(2589, 20)]


def test_build_works_with_nothing_collected_yet(settings: Settings) -> None:
    result = db.build(settings)

    assert set(result["counts"].values()) == {0}
    assert not any(result["present"].values())
    assert rows(settings, "SELECT count(*) FROM latest") == [(0,)]


def test_query_prints_a_table_and_missing_db_is_a_clear_error(
    filled: Settings, settings: Settings, capfd: pytest.CaptureFixture[str]
) -> None:
    db.build(filled)
    db.query(filled, "SELECT name FROM items ORDER BY item_id")
    out = capfd.readouterr().out
    assert "Destiny" in out and "Linen Cloth" in out

    db.db_path(filled).unlink()
    with pytest.raises(RuntimeError, match="collector db"):
        db.query(filled, "SELECT 1")


def test_details_from_foreverdb_fill_the_vendor_price(filled: Settings) -> None:
    directory = foreverdb_dump.dump_dir(filled)
    # Die Details des Schwerts, wie sie /items/647 liefert - und eine abgerissene Zeile,
    # wie sie nach einem Abbruch am Dateiende stehen kann.
    (directory / foreverdb_dump.DETAILS_FILE).write_text(
        '{"id":647,"name":"Destiny","sellPrice":51234,"bonding":"Binds when equipped",'
        '"disenchantable":true,"unique":false,"stats":[{"name":"Strength","value":9}]}\n'
        '{"id":999,"name":"abger',
        encoding="utf-8",
    )
    result = db.build(filled)
    assert result["counts"]["foreverdb_item_details"] == 1

    got = {
        r[0]: r[1:]
        for r in rows(filled, "SELECT item_id, vendor_sell, bonding, disenchantable, has_details FROM items")
    }
    # Das Schwert kennt Blizzard nicht: der Haendlerpreis kommt aus den Details.
    assert got[647] == (51234, "Binds when equipped", True, True)
    # Beim Stoff gilt weiter Blizzards Angabe.
    assert got[2589] == (13, None, None, False)

    assert rows(filled, "SELECT vendor_sell FROM latest WHERE item_id = 647") == [(51234,)]
    # Auch die verschachtelten Felder sind da.
    assert rows(filled, "SELECT stats[1].name FROM foreverdb_item_details") == [("Strength",)]
