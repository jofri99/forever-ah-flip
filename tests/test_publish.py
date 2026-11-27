"""Tests fuer die Anzeige-Dateien - ein kleines Warehouse aus echten Parquet-Dateien."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from collector import foreverdb_dump, publish, store
from collector.blizzard import ApiResponse
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

    # Dazu je Item die guenstigsten erreichbaren Haendler - der der Allianz fehlt.
    assert meta["item_vendors"] == 2
    assert query(out / publish.ITEM_VENDORS, "SELECT item_id, vendor, zone, price_per_item, limited, limited_stock, n_vendors FROM FILE") == [
        (100, "Horde Vendor", "Orgrimmar", 200.0, True, 1, 1),
        (300, "Horde Vendor", "Orgrimmar", 98.0, False, None, 1),
    ]

    # Verschwindet der Abzug, darf keine veraltete Datei liegen bleiben.
    (directory / foreverdb_dump.VENDOR_DETAILS_FILE).unlink()
    meta = publish.build(warehouse, out_dir=out)
    assert meta["vendor_flips"] is None
    assert not (out / publish.VENDOR_FLIPS).exists()
    assert not (out / publish.ITEM_VENDORS).exists()


class FakeLive:
    """Der aktuelle Stand, wie Blizzard ihn liefert: zwei Dateien mit jedem einzelnen Angebot."""

    def __init__(self, stamp: dt.datetime, auctions: list[dict], commodities: list[dict], status: int = 200) -> None:
        self.stamp, self.auction_rows, self.commodity_rows, self.status = stamp, auctions, commodities, status

    def _respond(self, rows: list[dict], stream_to: Path) -> ApiResponse:
        if self.status != 200:
            return ApiResponse(status=self.status, url="fake")
        stream_to.parent.mkdir(parents=True, exist_ok=True)
        stream_to.write_text(json.dumps({"auctions": rows}), encoding="utf-8")
        return ApiResponse(status=200, url="fake", headers={"last-modified": store.http_date(self.stamp)}, path=stream_to)

    def auctions(self, ruleset, house, stream_to=None, if_modified_since=None) -> ApiResponse:
        return self._respond(self.auction_rows, stream_to)

    def commodities(self, ruleset, house, stream_to=None, if_modified_since=None) -> ApiResponse:
        return self._respond(self.commodity_rows, stream_to)


def test_market_value_ignores_bargains_and_overpriced_walls() -> None:
    # Das Beispiel aus der Doku von TSM: von 23 Stueck zaehlen die guenstigsten 30 %,
    # das einzelne Schnaeppchen fuer 5 faellt als Ausreisser weg, der Rest ergibt 14,5.
    assert publish.market_value([(5, 1), (13, 2), (15, 3), (16, 1), (20, 16)]) == pytest.approx(14.5)
    # Nach den ersten 15 % endet die Betrachtung an einem Preissprung von 20 % oder mehr.
    assert publish.market_value([(10, 2), (13, 2), (50, 6)]) == pytest.approx(10.0)
    # Ein kleinerer Schritt zaehlt noch mit, bis die 30 % voll sind.
    assert publish.market_value([(10, 2), (11, 2), (50, 6)]) == pytest.approx(31 / 3)
    assert publish.market_value([(100, 1)]) == 100
    assert publish.market_value([]) is None


def test_live_snapshot_becomes_the_market_and_yields_the_price_ladder(warehouse: Settings, tmp_path: Path) -> None:
    out = tmp_path / "site"
    live_at = T2 + dt.timedelta(minutes=40)
    client = FakeLive(
        live_at,
        auctions=[
            {"id": 1, "item": {"id": 100}, "buyout": 400, "quantity": 1, "time_left": "LONG"},
            {"id": 2, "item": {"id": 100}, "buyout": 700, "quantity": 1, "time_left": "LONG"},
            # Ein Item, das es in keinem gespeicherten Stand gab.
            {"id": 3, "item": {"id": 555}, "buyout": 50, "quantity": 1, "time_left": "SHORT"},
            # Nur ein Gebot, kein Sofortkauf: zaehlt fuer keinen Preis.
            {"id": 4, "item": {"id": 100}, "buyout": 0, "bid": 10, "quantity": 1, "time_left": "LONG"},
        ],
        commodities=[
            {"id": 10, "item": {"id": 300}, "unit_price": 95, "quantity": 20, "time_left": "LONG"},
            {"id": 11, "item": {"id": 300}, "unit_price": 95, "quantity": 5, "time_left": "LONG"},
            {"id": 12, "item": {"id": 300}, "unit_price": 120, "quantity": 10, "time_left": "LONG"},
        ],
    )

    meta = publish.build(warehouse, out_dir=out, client=client)

    assert meta["live_snapshot"] == "2026-11-14T12:40:00Z"
    assert meta["last_snapshot"] == "2026-11-14T12:00:00Z"       # der Verlauf endet beim gespeicherten Stand
    assert meta["ladder"] == 5

    # Die Preisleiter: je Item und Preis die Menge, gleiche Preise zusammengefasst.
    assert query(out / publish.LADDER, "SELECT item_id, price, quantity FROM FILE") == [
        (100, 400.0, 1.0), (100, 700.0, 1.0), (300, 95.0, 25.0), (300, 120.0, 10.0), (555, 50.0, 1.0),
    ]
    types = dict(query(out / publish.LADDER, "SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM FILE)"))
    assert "BIGINT" not in types.values()

    rows = {
        r[0]: r[1:]
        for r in query(
            out / publish.MARKET,
            "SELECT item_id, ts, min_price, n_listings, quantity, open_24h, change_24h_pct, qty_sold_24h, "
            "market_value, usual_price, usual_points FROM FILE",
        )
    }
    # Preise und Mengen kommen aus dem aktuellen Stand, der Vergleich ueber 24 Stunden aus dem Verlauf.
    assert rows[100] == (epoch(live_at), 400.0, 2, 2.0, 500.0, -20.0, 1.0, 400.0, None, 3)
    assert rows[300] == (epoch(live_at), 95.0, 3, 35.0, 90.0, 5.6, 42.0, 95.0, None, 3)
    # Das neue Item hat einen Preis, aber noch keine Geschichte.
    assert rows[555] == (epoch(live_at), 50.0, 1, 1.0, None, None, None, 50.0, None, 0)

    # Ohne aktuellen Stand gilt wieder der gespeicherte, und die alte Preisleiter verschwindet.
    meta = publish.build(warehouse, out_dir=out)
    assert meta["ladder"] is None and meta["live_snapshot"] is None
    assert not (out / publish.LADDER).exists()
    assert query(out / publish.MARKET, "SELECT item_id, min_price, market_value FROM FILE") == [
        (100, 550.0, None), (300, 99.0, None),
    ]

    # Liefert Blizzard den Stand nicht, ist das ein klarer Fehler und kein halber Bau.
    with pytest.raises(RuntimeError, match="HTTP 503"):
        publish.build(warehouse, out_dir=out, client=FakeLive(live_at, [], [], status=503))


def test_usual_price_needs_enough_snapshots(settings: Settings, tmp_path: Path) -> None:
    # 24 Staende: zwoelfmal 100, zwoelfmal 200 - der uebliche Preis ist die Mitte.
    start = dt.datetime(2026, 11, 14, 0, 0, 0)
    for hour in range(24):
        ts = start + dt.timedelta(hours=hour)
        write_items(settings, ts, [(100, "auction", 1, 1, 100 if hour < 12 else 200, 300), (300, "commodity", 1, 1, 50, 50)])
    # Das zweite Item kommt erst spaeter dazu und hat zu wenig Geschichte.
    out = tmp_path / "site"
    publish.build(settings, out_dir=out)
    assert query(out / publish.MARKET, "SELECT item_id, usual_price, usual_points FROM FILE") == [
        (100, 150.0, 24), (300, 50.0, 24),
    ]

    settings2_out = tmp_path / "short"
    publish.build(settings, out_dir=settings2_out, days=0.4)       # nur die letzten knapp zehn Stunden
    assert query(settings2_out / publish.MARKET, "SELECT item_id, usual_price, usual_points FROM FILE") == [
        (100, None, 10), (300, None, 10),
    ]


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
    # Das erste Rezept hat eine Abklingzeit von zwei Tagen.
    (directory / "spells.jsonl").write_text(
        '{"id":1,"name":"Big Bar","cooldownMs":172800000,"castTimeMs":25000}\n', encoding="utf-8"
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
    # Die Abklingzeit kommt aus der Spell-Liste; wo die nichts sagt, bleibt sie leer.
    assert query(out / publish.CRAFTS, "SELECT recipe_id, cooldown_seconds, cast_seconds FROM FILE") == [
        (1, 172800, 25.0),
        (2, None, None),
    ]

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
