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


def test_build_creates_tables_and_views_over_every_dataset(filled: Settings) -> None:
    result = db.build(filled)

    assert result["path"] == filled.local_dir / "forever.duckdb"
    assert result["counts"] == {
        "ah_prices": 2,
        "blizzard_items": 1,
        "craft_reagents": 0,
        "crafts": 0,
        "foreverdb_item_details": 0,
        "foreverdb_items": 2,
        "foreverdb_recipes": 0,
        "foreverdb_vendor_details": 0,
        "history": 4,
        "item_prices": 2,
        "items": 2,
        "latest": 2,
        "recipe_items": 0,
        "recipe_reagents": 0,
        "recipes": 0,
        "runs": 0,
        "sales": 1,
        "snapshots": 4,
        "sold_daily": 1,
        "vendor_flips": 0,
        "vendor_items": 0,
        "vendor_prices": 0,
        "vendor_stock": 0,
        "vendors": 0,
    }
    assert result["present"]["runs"] is False


def test_reference_data_lives_in_tables_with_keys(filled: Settings) -> None:
    result = db.build(filled)

    # Stammdaten sind Tabellen, in der Reihenfolge des Schemas ...
    assert result["tables"] == [
        "items", "vendors", "vendor_stock", "vendor_prices", "recipes", "recipe_reagents", "recipe_items",
    ]
    kinds = dict(
        rows(filled, "SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = 'main'")
    )
    assert {kinds[name] for name in result["tables"]} == {"BASE TABLE"}
    # ... und alles, was am stuendlichen Stand haengt, bleibt eine Sicht.
    assert {kinds[name] for name in ("snapshots", "latest", "ah_prices", "item_prices", "crafts", "vendor_flips")} == {"VIEW"}

    keys = rows(
        filled,
        "SELECT table_name, constraint_type, constraint_column_names FROM duckdb_constraints() "
        "WHERE constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY') ORDER BY ALL",
    )
    assert keys == [
        ("items", "PRIMARY KEY", ["item_id"]),
        ("recipe_items", "FOREIGN KEY", ["recipe_id"]),
        ("recipe_items", "PRIMARY KEY", ["recipe_id", "item_id"]),
        ("recipe_reagents", "FOREIGN KEY", ["recipe_id"]),
        ("recipe_reagents", "PRIMARY KEY", ["recipe_id", "item_id"]),
        ("recipes", "PRIMARY KEY", ["recipe_id"]),
        ("vendor_prices", "PRIMARY KEY", ["item_id"]),
        ("vendor_stock", "FOREIGN KEY", ["vendor_id"]),
        ("vendor_stock", "PRIMARY KEY", ["vendor_id", "item_id"]),
        ("vendors", "PRIMARY KEY", ["vendor_id"]),
    ]


def test_tables_are_rebuilt_once_the_reference_data_changed(
    filled: Settings, capfd: pytest.CaptureFixture[str]
) -> None:
    db.build(filled)
    assert db.is_stale(filled) is False
    assert db.refresh(filled) is None

    # Ein neues Item in der Liste von ForeverDB - etwa nach foreverdb-refresh.
    with open(foreverdb_dump.dump_dir(filled) / "items.jsonl", "a", encoding="utf-8") as handle:
        handle.write('{"id":9000,"name":"New Thing","quality":"Rare","class":"Miscellaneous","subclass":"Junk"}\n')
    assert db.is_stale(filled) is True
    # Die Tabelle ist eine Kopie und kennt es noch nicht ...
    assert rows(filled, "SELECT count(*) FROM items WHERE item_id = 9000") == [(0,)]

    # ... bis zur naechsten Abfrage ueber `sql`: die baut zuerst neu und sagt das.
    db.query(filled, "SELECT name FROM items WHERE item_id = 9000")
    captured = capfd.readouterr()
    assert "New Thing" in captured.out
    assert "neu gebaut" in captured.err
    assert db.is_stale(filled) is False

    # Wer die Datenbank nie gebaut hat, bekommt durch einen Abzug auch keine.
    db.db_path(filled).unlink()
    assert db.refresh(filled) is None
    assert not db.db_path(filled).exists()


def test_duplicates_in_the_sources_do_not_break_the_keys(filled: Settings) -> None:
    directory = foreverdb_dump.dump_dir(filled)
    # Das Schwert steht zweimal in der Item-Liste, derselbe Haendler zweimal in der Datei,
    # er fuehrt den Stoff zweimal, und ein Rezept nennt dieselbe Zutat zweimal.
    with open(directory / "items.jsonl", "a", encoding="utf-8") as handle:
        handle.write('{"id":647,"name":"Destiny","quality":"Epic","class":"Weapon","subclass":"Sword"}\n')
    vendor = (
        '{"id":1,"name":"Twice","side":"Horde","zone":"Orgrimmar","sells":['
        '{"itemId":2589,"name":"Linen Cloth","price":5,"stack":1,"pricePerItem":5.0,"limited":false},'
        '{"itemId":2589,"name":"Linen Cloth","price":3,"stack":1,"pricePerItem":3.0,"limited":false}]}\n'
    )
    (directory / foreverdb_dump.VENDOR_DETAILS_FILE).write_text(vendor + vendor, encoding="utf-8")
    (directory / foreverdb_dump.RECIPES_FILE).write_text(
        recipe(
            1, "Destiny", '{"itemId":647,"name":"Destiny","count":1}',
            '[{"itemId":2589,"name":"Linen Cloth","count":2},{"itemId":2589,"name":"Linen Cloth","count":3}]',
            '{"automatic":false,"trainer":null,"recipeItems":[{"itemId":647,"name":"Destiny"},{"itemId":647,"name":"Destiny"}],"sources":{"ways":[]}}',
        ),
        encoding="utf-8",
    )

    db.build(filled)

    assert rows(filled, "SELECT count(*) FROM items WHERE item_id = 647") == [(1,)]
    assert rows(filled, "SELECT vendor_id, name FROM vendors") == [(1, "Twice")]
    # Vom doppelt gefuehrten Stoff gilt das guenstigere Angebot.
    assert rows(filled, "SELECT vendor_id, item_id, price_per_item FROM vendor_stock") == [(1, 2589, 3.0)]
    # Die Mengen derselben Zutat zaehlen zusammen.
    assert rows(filled, "SELECT recipe_id, item_id, count FROM recipe_reagents") == [(1, 2589, 5)]
    assert rows(filled, "SELECT recipe_id, item_id FROM recipe_items") == [(1, 647)]


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
    # Ein Verlust behaelt sein Vorzeichen und wird sonst gleich zerlegt.
    assert rows(filled, "SELECT money(-4263), money(-63), money(-123456)") == [
        ("-42s 63c", "-63c", "-12g 34s 56c")
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
    # Ein neuer Stand macht die Tabellen der Stammdaten nicht alt.
    assert db.is_stale(filled) is False


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


def test_vendor_flips_compare_the_cheapest_reachable_vendor_with_the_auction_house(filled: Settings) -> None:
    directory = foreverdb_dump.dump_dir(filled)
    # Drei Haendler fuehren den Stoff (Item 2589, im Auktionshaus fuer 24c):
    # einer der Horde fuer 20c, ein neutraler fuer 10c, einer der Allianz fuer 1c.
    (directory / foreverdb_dump.VENDOR_DETAILS_FILE).write_text(
        '{"id":1,"name":"Horde Cloth","title":"Trade Supplies","side":"Horde","zone":"Orgrimmar","x":1.0,"y":2.0,'
        '"reputationFaction":{"id":76,"name":"Orgrimmar"},"sells":['
        '{"itemId":2589,"name":"Linen Cloth","price":20,"stack":1,"pricePerItem":20.0,"limited":false,"limitedStockCount":null,"seenInForever":true},'
        '{"itemId":647,"name":"Destiny","price":999999,"stack":1,"pricePerItem":999999.0,"limited":true,"limitedStockCount":1,"seenInForever":true}]}\n'
        '{"id":2,"name":"Neutral Goods","title":"Merchant","side":"Neutral","zone":"Booty Bay","x":3.0,"y":4.0,'
        '"sells":[{"itemId":2589,"name":"Linen Cloth","price":50,"stack":5,"pricePerItem":10.0,"limited":true,"limitedStockCount":2,"seenInForever":false}]}\n'
        '{"id":3,"name":"Alliance Cloth","title":"Trade Supplies","side":"Alliance","zone":"Stormwind","x":5.0,"y":6.0,'
        '"sells":[{"itemId":2589,"name":"Linen Cloth","price":1,"stack":1,"pricePerItem":1.0,"limited":false,"limitedStockCount":null,"seenInForever":true}]}\n',
        encoding="utf-8",
    )
    result = db.build(filled)
    assert result["counts"]["foreverdb_vendor_details"] == 3
    assert result["counts"]["vendor_items"] == 4

    offers = rows(
        filled,
        "SELECT vendor, side, item_id, price_per_item, limited, limited_stock, reputation "
        "FROM vendor_items WHERE item_id = 2589 ORDER BY price_per_item",
    )
    assert offers == [
        ("Alliance Cloth", "Alliance", 2589, 1.0, False, None, None),
        ("Neutral Goods", "Neutral", 2589, 10.0, True, 2, None),
        ("Horde Cloth", "Horde", 2589, 20.0, False, None, "Orgrimmar"),
    ]

    flips = rows(
        filled,
        "SELECT name, vendor_price, ah_price, profit, profit_pct, vendor, side, limited, limited_stock FROM vendor_flips",
    )
    # Der Haendler der Allianz waere am billigsten, ist fuer die Horde aber nicht erreichbar.
    # Es zaehlt der neutrale: 24c * 0,95 - 10c = 12,8c Gewinn je Stueck. Das Schwert kostet
    # beim Haendler mehr als im Auktionshaus und taucht nicht auf.
    assert flips == [("Linen Cloth", 10.0, 24, 13, 128, "Neutral Goods", "Neutral", True, 2)]


def recipe(spell_id: int, name: str, makes: str, reagents: str, learned: str) -> str:
    """Eine Zeile recipes.jsonl, wie /professions/{slug} sie liefert - gekuerzt."""
    return (
        f'{{"spellId":{spell_id},"name":"{name}","category":{{"id":1,"name":"Blades","parent":{{"id":2,"name":"Blacksmithing"}}}},'
        f'"skill":{{"orange":120,"orangeSource":"client","yellow":140,"green":160,"grey":180}},"requiredLevel":20,'
        f'"makes":{makes},"effect":null,"reagents":{reagents},"tools":[],"learnedFrom":{learned},'
        '"newInForever":true,"url":"https://example.invalid/spell","profession":"blacksmithing","professionName":"Blacksmithing"}\n'
    )


def test_crafts_price_every_reagent_at_the_cheaper_source(filled: Settings) -> None:
    directory = foreverdb_dump.dump_dir(filled)
    # Im Auktionshaus: das Schwert (647) fuer 450, der Stoff (2589) fuer 24.
    # Beim Haendler der Horde: Stoff fuer 30 (teurer als im Auktionshaus), Faden (4000)
    # fuer 10 und die Vorlage (4100) fuer 150. Ein Haendler mit begrenztem Bestand und
    # einer der Allianz waeren billiger, zaehlen fuers Herstellen aber nicht.
    (directory / foreverdb_dump.VENDOR_DETAILS_FILE).write_text(
        '{"id":1,"name":"Horde Supplies","side":"Horde","zone":"Orgrimmar","sells":['
        '{"itemId":2589,"name":"Linen Cloth","price":30,"stack":1,"pricePerItem":30.0,"limited":false,"seenInForever":true},'
        '{"itemId":4000,"name":"Thread","price":10,"stack":1,"pricePerItem":10.0,"limited":false,"seenInForever":true},'
        '{"itemId":4100,"name":"Plans: Destiny","price":150,"stack":1,"pricePerItem":150.0,"limited":false,"seenInForever":true}]}\n'
        '{"id":2,"name":"Rare Goods","side":"both","zone":"Booty Bay","sells":['
        '{"itemId":2589,"name":"Linen Cloth","price":5,"stack":1,"pricePerItem":5.0,"limited":true,"limitedStockCount":2,"seenInForever":true}]}\n'
        '{"id":3,"name":"Alliance Supplies","side":"Alliance","zone":"Stormwind","sells":['
        '{"itemId":4000,"name":"Thread","price":1,"stack":1,"pricePerItem":1.0,"limited":false,"seenInForever":true}]}\n'
        # Derselbe Faden zum selben Preis, aber weit weg - und mit der kleineren Nummer.
        '{"id":0,"name":"Far Away","side":"both","zone":"Swamp of Sorrows","sells":['
        '{"itemId":4000,"name":"Thread","price":10,"stack":1,"pricePerItem":10.0,"limited":false,"seenInForever":true}]}\n',
        encoding="utf-8",
    )
    (directory / foreverdb_dump.RECIPES_FILE).write_text(
        # Schwert aus 10 Stoff und 2 Faden, beim Lehrer gelernt.
        recipe(
            1, "Destiny", '{"itemId":647,"name":"Destiny","count":1,"quality":"Epic"}',
            '[{"itemId":2589,"name":"Linen Cloth","count":10},{"itemId":4000,"name":"Thread","count":2}]',
            '{"automatic":false,"trainer":{"cost":500,"trainers":1},"recipeItems":[],"sources":{"ways":["trainer"],"learnAtSkill":125,"trainerCost":550}}',
        )
        # Stoff, zwei bis vier Stueck je Durchgang, aus einer Zutat ohne Preis; gelernt aus einer Vorlage.
        + recipe(
            2, "Weave Linen", '{"itemId":2589,"name":"Linen Cloth","min":2,"max":4,"quality":"Common"}',
            '[{"itemId":5000,"name":"Moonfiber","count":1}]',
            '{"automatic":false,"trainer":null,"recipeItems":[{"itemId":4100,"name":"Plans: Destiny"}],"sources":{"ways":["vendor"],"learnAtSkill":120}}',
        )
        # Eine Verzauberung stellt nichts her, was sich verkaufen liesse.
        + recipe(
            3, "Enchant Blade", "null", '[{"itemId":2589,"name":"Linen Cloth","count":3}]',
            '{"automatic":true,"trainer":null,"recipeItems":[],"sources":{"ways":[]}}',
        )
        # Dasselbe Rezept noch einmal unter einem zweiten Beruf: es bleibt eines.
        + recipe(
            3, "Enchant Blade", "null", '[{"itemId":2589,"name":"Linen Cloth","count":3}]',
            '{"automatic":true,"trainer":null,"recipeItems":[],"sources":{"ways":[]}}',
        ).replace('"profession":"blacksmithing","professionName":"Blacksmithing"', '"profession":"enchanting","professionName":"Enchanting"'),
        encoding="utf-8",
    )
    result = db.build(filled)
    # Faden, Vorlage und die Zutat ohne Preis stehen in keiner Item-Liste. Das darf sein
    # und wird gezaehlt, statt den Bau scheitern zu lassen.
    assert result["dangling"] == {
        "vendor_stock.item_id": 2,
        "recipes.item_id": 0,
        "recipes.recipe_item_id": 1,
        "recipe_reagents.item_id": 2,
        "recipe_items.item_id": 1,
    }
    assert result["counts"]["recipes"] == 3
    assert result["counts"]["recipe_reagents"] == 4
    assert result["counts"]["recipe_items"] == 1

    assert rows(
        filled,
        "SELECT recipe_id, profession, category, skill, item_id, item_count, learned, trainer_cost, recipe_item_id "
        "FROM recipes ORDER BY recipe_id",
    ) == [
        (1, "Blacksmithing", "Blades", 125, 647, 1.0, "trainer", 550, None),
        (2, "Blacksmithing", "Blades", 120, 2589, 3.0, "recipe", None, 4100),
        (3, "Blacksmithing", "Blades", 120, None, None, "automatic", None, None),
    ]

    assert rows(
        filled,
        "SELECT item_id, ah_price, vendor_price, buy_price, buy_source FROM item_prices ORDER BY item_id",
    ) == [
        (647, 450, None, 450.0, "ah"),
        (2589, 24, 30.0, 24.0, "ah"),
        (4000, None, 10.0, 10.0, "vendor"),
        (4100, None, 150.0, 150.0, "vendor"),
    ]
    # Fuehren mehrere Haendler ein Item zum selben Preis, wird einer in einer Hauptstadt genannt.
    assert rows(filled, "SELECT vendor, zone, n_vendors FROM vendor_prices WHERE item_id = 4000") == [
        ("Horde Supplies", "Orgrimmar", 2)
    ]

    assert rows(
        filled,
        "SELECT item_id, count, unit_price, source, vendor, total FROM craft_reagents WHERE recipe_id = 1 ORDER BY item_id",
    ) == [(2589, 10, 24.0, "ah", None, 240.0), (4000, 2, 10.0, "vendor", "Horde Supplies", 20.0)]

    crafts = {
        r[0]: r[1:]
        for r in rows(
            filled,
            "SELECT recipe_id, reagents, unpriced, cost_known, cost, ah_price, profit, profit_pct, "
            "recipe_price, recipe_source FROM crafts",
        )
    }
    # Schwert: 10 * 24 + 2 * 10 = 260 Kosten, 450 * 0,95 = 427,5 Erloes -> 167,5 Gewinn.
    assert crafts[1] == (2, 0, 260.0, 260.0, 450, 168.0, 64.0, None, None)
    # Ohne Preis fuer die Zutat gibt es keine Kosten und keinen Gewinn - aber die Vorlage hat einen Preis.
    assert crafts[2] == (1, 1, 0.0, None, 24, None, None, 150.0, "vendor")
    # Die Verzauberung hat Kosten, aber nichts zu verkaufen.
    assert crafts[3] == (1, 0, 72.0, 72.0, None, None, None, None, None)
