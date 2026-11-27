"""Baut aus dem Warehouse die Dateien, die die Anzeige liest.

Das Warehouse hat eine Datei je Stand - gut zum Sammeln, schlecht zum Anzeigen:
der Verlauf eines Items ueber 14 Tage laege in 336 Dateien. Hier entsteht daraus
eine Form, die ein Browser mit wenigen Teilabrufen lesen kann:

    hourly.parquet   alle Staende des Zeitfensters, nach Item sortiert und in
                     kleine Zeilengruppen geschnitten. Wer ein Item will, liest
                     am Dateiende nach, in welcher Gruppe es liegt, und holt nur die.
    market.parquet   der juengste Stand, eine Zeile je Item, dazu 24-Stunden-Werte.
    meta.json        was drin ist und von wann.

Mit Zugangsdaten holt `publish` ausserdem den aktuellen Stand direkt von Blizzard, mit
jedem einzelnen Angebot. Daraus entsteht die Preisleiter:

    ladder.parquet   je Item und Preis die angebotene Menge, von unten nach oben.
                     Erst damit laesst sich rechnen, was ein Aufkauf kostet - die
                     gespeicherten Kennzahlen verraten das nicht.

Mit einem lokalen Abzug von ForeverDB kommen dazu:

    vendor_flips.parquet    beim Haendler kaufen, im Auktionshaus verkaufen
    crafts.parquet          je Rezept Kosten, Erloes und Gewinn
    craft_reagents.parquet  die Zutaten dieser Rezepte mit Preis und Bezugsquelle
    item_vendors.parquet    je Item die guenstigsten erreichbaren Haendler

Diese Dateien sind abgeleitet und jederzeit neu baubar. Sie gehoeren deshalb
nicht ins Warehouse und nicht in Git.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import duckdb

from . import collect, crafting, foreverdb_dump, names, store
from .config import AH_KEEP, ROOT, UNREACHABLE_SIDE, Settings

HOURLY = "hourly.parquet"
MARKET = "market.parquet"
META = "meta.json"
NAMES = "names.json"      # optional: {"2589": "Leinenstoff", ...}
VENDOR_FLIPS = "vendor_flips.parquet"   # optional, nur mit lokalem Abzug von ForeverDB
CRAFTS = "crafts.parquet"               # ebenso: braucht den Abzug der Rezepte
CRAFT_REAGENTS = "craft_reagents.parquet"
ITEM_VENDORS = "item_vendors.parquet"   # ebenso: braucht den Abzug der Haendler
LADDER = "ladder.parquet"               # optional: braucht den aktuellen Stand von Blizzard

# Der uebliche Preis zaehlt nur die letzten Tage: was davor war - der Preissturz nach dem
# Erscheinen eines Items, eine alte Preislage - sagt nichts darueber, wo der Preis heute steht.
USUAL_DAYS = 7
# Ab so vielen Staenden in diesen Tagen gilt der uebliche Preis eines Items als belastbar.
USUAL_MIN_POINTS = 24
# Ein Trend braucht mehr Geschichte als ein Median: so viele Staende ueber so viele Tage.
TREND_MIN_POINTS = 48
TREND_MIN_DAYS = 3
# So viele Haendler je Item reichen der Anzeige; wie viele es insgesamt sind, steht daneben.
VENDORS_PER_ITEM = 3

DEFAULT_OUT = ROOT / "web" / "public" / "data"
DEFAULT_DAYS = 14

# Klein genug, dass ein Item nur einen Bruchteil der Datei kostet, gross genug,
# dass das Verzeichnis am Dateiende nicht selbst zur Last wird.
ROW_GROUP_SIZE = 8192

# Die Anzeige liest mit einem schlanken Parquet-Leser, der Snappy ohne
# Zusatzpaket versteht. zstd waere kleiner, braeuchte im Browser aber 75 KB mehr.
COMPRESSION = "snappy"

EMPTY_SALES = """
    CREATE OR REPLACE TEMP TABLE s (
        snapshot_ts TIMESTAMP, item_id INTEGER, kind VARCHAR, gap_hours DOUBLE,
        n_sold INTEGER, qty_sold BIGINT, value_sold BIGINT, n_new INTEGER, qty_new BIGINT
    )
"""


def _load(con: duckdb.DuckDBPyConnection, warehouse: Path, house: int) -> None:
    items = store.dataset_glob(warehouse, store.ITEMS, house)
    if items is None:
        raise RuntimeError(
            f"Im Warehouse {warehouse} liegt noch kein Stand fuer Haus {house}. "
            "Erst `git -C data/warehouse pull` oder `python -m collector collect`."
        )
    # Haus und Tag stehen auch im Pfad; die Spalten in der Datei genuegen.
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE i AS "
        f"SELECT * FROM read_parquet('{items}', hive_partitioning = false)"
    )

    sales = store.dataset_glob(warehouse, store.SALES, house)
    if sales is None:
        con.execute(EMPTY_SALES)
    else:
        con.execute(
            f"CREATE OR REPLACE TEMP TABLE s AS "
            f"SELECT * FROM read_parquet('{sales}', hive_partitioning = false)"
        )


def _load_local_details(con: duckdb.DuckDBPyConnection, settings: Settings) -> None:
    """Haendlerpreise aus dem lokalen Abzug von ForeverDB, wo Blizzard keinen nennt.

    Den Abzug gibt es nur auf diesem Rechner. In Actions bleibt die Tabelle leer.
    """
    con.execute("CREATE OR REPLACE TEMP TABLE fdb_details (item_id INTEGER, sell_price BIGINT)")
    target = foreverdb_dump.dump_dir(settings) / foreverdb_dump.DETAILS_FILE
    if not target.is_file() or target.stat().st_size == 0:
        return
    con.execute(
        f"INSERT INTO fdb_details SELECT id, max(sellPrice) FROM read_json('{store.sql_path(target)}', "
        "format = 'newline_delimited', columns = {'id': 'INTEGER', 'sellPrice': 'BIGINT'}, "
        "ignore_errors = true) WHERE id IS NOT NULL GROUP BY id"
    )


def _load_local_list(con: duckdb.DuckDBPyConnection, settings: Settings) -> None:
    """Typ und Untertyp aus der lokalen Item-Liste von ForeverDB, fuer Items ohne
    Stammdaten von Blizzard. Beide Quellen benennen die Typen gleich."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE fdb_list (item_id INTEGER, item_class VARCHAR, item_subclass VARCHAR)"
    )
    target = foreverdb_dump.dump_dir(settings) / "items.jsonl"
    if not target.is_file() or target.stat().st_size == 0:
        return
    con.execute(
        f"INSERT INTO fdb_list SELECT id, any_value(\"class\"), any_value(subclass) "
        f"FROM read_json('{store.sql_path(target)}', format = 'newline_delimited', "
        "columns = {'id': 'INTEGER', 'class': 'VARCHAR', 'subclass': 'VARCHAR'}, ignore_errors = true) "
        "WHERE id IS NOT NULL GROUP BY id"
    )


class LiveSnapshotError(RuntimeError):
    """Der aktuelle Stand liess sich nicht von Blizzard holen."""


def market_value(tiers: list[tuple[float, float]]) -> float | None:
    """Der Marktwert eines Stands nach dem Verfahren von TSMs AuctionDB.

    `tiers` sind (Preis, Menge), aufsteigend nach Preis. Betrachtet werden die guenstigsten
    30 % der Stuecke. Nach den ersten 15 % endet die Betrachtung an einem Preissprung von
    20 % oder mehr. Was dann noch mehr als 1,5 Standardabweichungen vom Mittel liegt, faellt
    weg; der Rest wird gemittelt. So zaehlt weder ein einzelnes Schnaeppchen noch eine Wand
    ueberteuerter Angebote.
    """
    total = sum(qty for _, qty in tiers)
    if total <= 0:
        return None
    limit, early = max(1, math.ceil(total * 0.30)), total * 0.15
    kept: list[tuple[float, float]] = []
    seen, previous = 0.0, None
    for price, qty in tiers:
        if seen >= limit or (previous is not None and seen >= early and price >= previous * 1.2):
            break
        take = min(qty, limit - seen)
        kept.append((price, take))
        seen += take
        previous = price
    count = sum(qty for _, qty in kept)
    mean = sum(price * qty for price, qty in kept) / count
    deviation = math.sqrt(sum(qty * (price - mean) ** 2 for price, qty in kept) / count)
    inside = [(price, qty) for price, qty in kept if abs(price - mean) <= 1.5 * deviation] or kept
    return sum(price * qty for price, qty in inside) / sum(qty for _, qty in inside)


def _empty_live(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        "CREATE OR REPLACE TEMP TABLE live (item_id INTEGER, kind VARCHAR, min_price DOUBLE, "
        "p25_price DOUBLE, median_price DOUBLE, n_listings INTEGER, quantity DOUBLE)"
    )
    con.execute("CREATE OR REPLACE TEMP TABLE ladder (item_id INTEGER, price DOUBLE, quantity DOUBLE)")
    con.execute("CREATE OR REPLACE TEMP TABLE mv (item_id INTEGER, market_value DOUBLE)")


def _load_live(con: duckdb.DuckDBPyConnection, settings: Settings, house: int, client: Any) -> int:
    """Holt den aktuellen Stand mit allen Angeboten und baut daraus `live`, `ladder` und `mv`.

    Gibt zurueck, von wann der Stand ist (Unix-Sekunden). Die heruntergeladenen Dateien
    liegen unter data/raw/publish und werden beim naechsten Lauf ueberschrieben.
    """
    raw = settings.raw_dir / "publish"
    try:
        auctions = client.auctions(settings.ruleset, house, stream_to=raw / f"house{house}_auctions.json")
        commodities = client.commodities(settings.ruleset, house, stream_to=raw / f"house{house}_commodities.json")
    except Exception as exc:  # Netz, Anmeldung, Zeitueberschreitung
        raise LiveSnapshotError(f"Blizzard ist nicht erreichbar: {exc}") from exc
    if auctions.status != 200:
        raise LiveSnapshotError(f"Blizzard liefert den aktuellen Stand nicht (HTTP {auctions.status}).")
    collect.load_snapshot(
        con, raw / f"house{house}_auctions.json",
        raw / f"house{house}_commodities.json" if commodities.status == 200 else None,
    )
    _empty_live(con)
    con.execute(
        """
        INSERT INTO live
        SELECT item_id, kind, min(unit_price), round(quantile_cont(unit_price, 0.25)),
               round(median(unit_price)), count(*), sum(quantity)
        FROM snap WHERE unit_price > 0 GROUP BY item_id, kind;

        INSERT INTO ladder
        SELECT item_id, unit_price, sum(quantity) FROM snap WHERE unit_price > 0 GROUP BY item_id, unit_price;
        """
    )
    # Der Marktwert braucht die Stufen der Reihe nach - das rechnet sich in Python leichter.
    values: list[tuple[int, float]] = []
    current, tiers = None, []
    for item_id, price, qty in con.execute("SELECT item_id, price, quantity FROM ladder ORDER BY item_id, price").fetchall():
        if item_id != current:
            if tiers:
                values.append((current, round(market_value(tiers) or 0)))
            current, tiers = item_id, []
        tiers.append((price, qty))
    if tiers:
        values.append((current, round(market_value(tiers) or 0)))
    if values:
        con.executemany("INSERT INTO mv VALUES (?, ?)", values)

    stamp = auctions.header("last-modified")
    try:
        return int(parsedate_to_datetime(stamp).timestamp()) if stamp else int(dt.datetime.now(dt.timezone.utc).timestamp())
    except (TypeError, ValueError):
        return int(dt.datetime.now(dt.timezone.utc).timestamp())


def _build_hourly(con: duckdb.DuckDBPyConnection, since: dt.datetime) -> int:
    """Eine Zeile je Item und Stand. Zeit als Unix-Sekunden, Preise als DOUBLE:
    beides kommt im Browser als gewoehnliche Zahl an, ohne BigInt und ohne Datumsobjekte."""
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE hourly AS
        SELECT i.item_id::INTEGER             AS item_id,
               i.kind                         AS kind,
               epoch(i.snapshot_ts)::INTEGER  AS ts,
               i.min_price::DOUBLE            AS min_price,
               i.p25_price::DOUBLE            AS p25_price,
               i.median_price::DOUBLE         AS median_price,
               i.n_listings::INTEGER          AS n_listings,
               i.quantity::DOUBLE             AS quantity,
               s.n_sold::INTEGER              AS n_sold,
               s.qty_sold::DOUBLE             AS qty_sold,
               s.value_sold::DOUBLE           AS value_sold,
               s.qty_new::DOUBLE              AS qty_new,
               s.gap_hours::FLOAT             AS gap_hours
        FROM i
        LEFT JOIN s
               ON s.snapshot_ts = i.snapshot_ts AND s.item_id = i.item_id AND s.kind = i.kind
        WHERE i.snapshot_ts >= ?
        """,
        [since],
    )
    return con.execute("SELECT count(*) FROM hourly").fetchone()[0]


def _build_market(con: duckdb.DuckDBPyConnection, live_ts: int | None = None) -> int:
    """Der juengste Stand mit dem, was eine Uebersichtstabelle braucht.

    Mit `live_ts` gilt als juengster Stand der eben von Blizzard geholte (Tabelle `live`),
    sonst der letzte gespeicherte. Die Werte der letzten 24 Stunden kommen immer aus dem
    gespeicherten Verlauf.
    """
    current = (
        f"SELECT item_id, kind, {int(live_ts)}::INTEGER AS ts, min_price, p25_price, median_price, n_listings, quantity FROM live"
        if live_ts is not None
        else "SELECT h.item_id, h.kind, h.ts, h.min_price, h.p25_price, h.median_price, h.n_listings, h.quantity "
             "FROM hourly h, latest WHERE h.ts = latest.ts"
    )
    trend_known = f"u.trend_points >= {TREND_MIN_POINTS} AND u.trend_days >= {TREND_MIN_DAYS}"
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE market AS
        WITH latest AS (SELECT max(ts) AS ts FROM hourly),
        cur AS ({current}),
        -- Der uebliche Preis: der Median des guenstigsten Angebots ueber die letzten USUAL_DAYS Tage.
        -- Der Trend: eine Gerade durch den Logarithmus desselben Preises, ueber das ganze Fenster. Ihre Steigung ist die
        -- Aenderung je Tag; trend_fit (r2) sagt, wie genau der Verlauf der Geraden folgt. Ein
        -- stetiger Verfall hat beides, ein Ausreisser nach unten nur einen niedrigen Preis.
        usual AS (
            SELECT item_id,
                   round(median(p) FILTER (WHERE age_days >= -{USUAL_DAYS}))       AS usual_price,
                   (count(*) FILTER (WHERE age_days >= -{USUAL_DAYS}))::INTEGER    AS usual_points,
                   count(*)                          AS trend_points,
                   regr_slope(ln(p), age_days)       AS trend_slope,
                   regr_r2(ln(p), age_days)          AS trend_fit,
                   max(age_days) - min(age_days)     AS trend_days
            FROM (
                SELECT h.item_id, (h.ts - latest.ts) / 86400.0 AS age_days, min(h.min_price) AS p
                FROM hourly h, latest WHERE h.min_price > 0 GROUP BY h.item_id, h.ts, latest.ts
            )
            GROUP BY item_id
        ),
        day AS (
            SELECT h.item_id, h.kind,
                   count(*)::INTEGER             AS snapshots_24h,
                   sum(h.qty_sold)               AS qty_sold_24h,
                   sum(h.value_sold)             AS value_sold_24h,
                   -- Wie viel neu eingestellt wurde: daran haengt, ob ein Reset haelt.
                   sum(h.qty_new)                AS qty_new_24h,
                   -- Wie viele der 24 Stunden ueberhaupt durch Vergleiche gedeckt sind.
                   -- Steht hier 6, sind die Verkaufszahlen ein Viertel der Wahrheit.
                   sum(h.gap_hours) FILTER (WHERE h.n_sold IS NOT NULL)::FLOAT
                                                 AS sales_hours_24h,
                   min(h.min_price)              AS low_24h,
                   max(h.min_price)              AS high_24h,
                   arg_min(h.min_price, h.ts)    AS open_24h
            FROM hourly h, latest
            WHERE h.ts > latest.ts - 86400
            GROUP BY h.item_id, h.kind
        )
        SELECT cur.item_id, cur.kind, cur.ts,
               cur.min_price, cur.p25_price, cur.median_price, cur.n_listings, cur.quantity,
               day.snapshots_24h, day.qty_sold_24h, day.value_sold_24h, day.sales_hours_24h,
               day.low_24h, day.high_24h, day.open_24h,
               CASE WHEN day.open_24h > 0
                    THEN round((cur.min_price - day.open_24h) * 100.0 / day.open_24h, 1)
               END AS change_24h_pct,
               -- Typ und Untertyp, z. B. Recipe / Tailoring. Fuer den Filter der Oberflaeche.
               coalesce(k.item_class, fl.item_class)       AS item_class,
               coalesce(k.item_subclass, fl.item_subclass) AS item_subclass,
               -- Was ein Haendler zahlt, und sein Listenpreis je Stueck. Der Listenpreis
               -- steht bei jedem Item, auch wenn es kein Haendler fuehrt.
               coalesce(k.sell_price, fd.sell_price)::DOUBLE AS vendor_sell,
               (k.purchase_price::DOUBLE / greatest(coalesce(k.purchase_quantity, 1), 1))
                   AS vendor_buy,
               CASE WHEN u.usual_points >= {USUAL_MIN_POINTS} THEN u.usual_price END::DOUBLE AS usual_price,
               coalesce(u.usual_points, 0)::INTEGER        AS usual_points,
               -- Aenderung des guenstigsten Angebots in Prozent je Tag, ueber das ganze Fenster.
               CASE WHEN {trend_known} AND isfinite(u.trend_slope)
                    THEN round((exp(u.trend_slope) - 1) * 100, 1) END::DOUBLE AS trend_pct_day,
               CASE WHEN {trend_known} AND isfinite(u.trend_slope) AND isfinite(u.trend_fit)
                    THEN round(u.trend_fit, 2) END::DOUBLE  AS trend_fit,
               day.qty_new_24h,
               -- Nur mit dem aktuellen Stand von Blizzard: der Marktwert nach TSMs Verfahren.
               mv.market_value
        FROM cur
        LEFT JOIN day ON day.item_id = cur.item_id AND day.kind = cur.kind
        LEFT JOIN usual u ON u.item_id = cur.item_id
        LEFT JOIN mv ON mv.item_id = cur.item_id
        LEFT JOIN known k ON k.item_id = cur.item_id AND k.status = 200
        LEFT JOIN fdb_details fd ON fd.item_id = cur.item_id
        LEFT JOIN fdb_list fl ON fl.item_id = cur.item_id
        """
    )
    return con.execute("SELECT count(*) FROM market").fetchone()[0]


def _load_vendor_offers(con: duckdb.DuckDBPyConnection, settings: Settings) -> bool:
    """Was erreichbare Haendler verkaufen: eine Zeile je Haendler und Item.

    Ohne Abzug der Haendler - in Actions also immer - bleibt die Tabelle leer,
    und es kommt False zurueck.
    """
    from . import db        # hier, um einen Importkreis zu vermeiden

    con.execute(
        "CREATE OR REPLACE TEMP TABLE vendor_offers (vendor VARCHAR, zone VARCHAR, side VARCHAR, "
        "reputation VARCHAR, item_id INTEGER, price_per_item DOUBLE, limited BOOLEAN, "
        "limited_stock INTEGER, seen_in_forever BOOLEAN, vendor_id INTEGER)"
    )
    source = db.vendor_details_source(settings)
    if source is None:
        return False
    con.execute(
        f"""
        INSERT INTO vendor_offers
        SELECT v.name, v.zone, v.side, v.reputationFaction.name,
               s.itemId, s.pricePerItem, coalesce(s.limited, false),
               s.limitedStockCount, s.seenInForever, v.id
        FROM ({source}) v, unnest(v.sells) AS t(s)
        WHERE v.side <> '{UNREACHABLE_SIDE}' AND s.pricePerItem > 0
        """
    )
    return True


def _build_vendor_flips(con: duckdb.DuckDBPyConnection) -> int:
    """Beim Haendler kaufen, im Auktionshaus verkaufen.

    Je Item der guenstigste erreichbare Haendler gegen das guenstigste Angebot im
    Auktionshaus, Gewinn nach 5 % Gebuehr. Setzt die Tabellen `market` und
    `vendor_offers` voraus.
    """
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE vendor_flips AS
        WITH cheapest AS (
            SELECT * FROM vendor_offers
            QUALIFY row_number() OVER (PARTITION BY item_id ORDER BY price_per_item, vendor_id) = 1
        )
        SELECT m.item_id, m.kind, m.item_class, m.item_subclass,
               c.price_per_item::DOUBLE                       AS vendor_price,
               m.min_price                                    AS ah_price,
               round(m.min_price * {AH_KEEP} - c.price_per_item)   AS profit,
               round((m.min_price * {AH_KEEP} - c.price_per_item) * 100.0 / c.price_per_item)
                                                              AS profit_pct,
               m.n_listings, m.qty_sold_24h, m.sales_hours_24h,
               coalesce(c.limited, false)                     AS limited,
               c.limited_stock::INTEGER                       AS limited_stock,
               c.vendor, c.zone, c.side, c.reputation,
               c.seen_in_forever
        FROM market m JOIN cheapest c USING (item_id)
        WHERE m.min_price * {AH_KEEP} > c.price_per_item
        """
    )
    return con.execute("SELECT count(*) FROM vendor_flips").fetchone()[0]


def _build_item_vendors(con: duckdb.DuckDBPyConnection) -> int:
    """Je Item die guenstigsten erreichbaren Haendler und wie viele es insgesamt fuehren."""
    hubs = ", ".join(f"'{zone}'" for zone in crafting.HUBS)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE item_vendors AS
        SELECT item_id::INTEGER AS item_id, vendor, zone, price_per_item::DOUBLE AS price_per_item,
               limited, limited_stock::INTEGER AS limited_stock,
               (count(*) OVER (PARTITION BY item_id))::INTEGER AS n_vendors
        FROM vendor_offers
        QUALIFY row_number() OVER (
            PARTITION BY item_id
            ORDER BY price_per_item, coalesce(zone IN ({hubs}), false) DESC, vendor_id
        ) <= {VENDORS_PER_ITEM}
        """
    )
    return con.execute("SELECT count(*) FROM item_vendors").fetchone()[0]


def _build_crafts(con: duckdb.DuckDBPyConnection, settings: Settings) -> int | None:
    """Herstellen und im Auktionshaus verkaufen: je Rezept Kosten, Erloes, Gewinn.

    Die Rechnung selbst steht in crafting.py und gilt genauso in der lokalen
    Datenbank. Hier kommen nur die Preise aus `market` und `vendor_offers` dazu.
    Gibt None zurueck, wenn es keinen Abzug der Rezepte gibt.
    """
    source = crafting.recipes_source(settings)
    if source is None:
        return None
    table = "CREATE OR REPLACE TEMP TABLE"
    con.execute(f"{table} foreverdb_recipes AS {source}")
    con.execute(f"{table} spell_timing AS {crafting.spell_timing_source(settings)}")
    con.execute(
        f"""
        {table} ah_prices AS
        SELECT item_id, kind, min_price AS ah_price, n_listings, qty_sold_24h, sales_hours_24h,
               item_class, item_subclass
        FROM market
        WHERE min_price > 0
        QUALIFY row_number() OVER (PARTITION BY item_id ORDER BY min_price, kind) = 1;
        """
    )
    # Zum Herstellen taugt nur, wer unbegrenzt liefert.
    con.execute(crafting.model_sql(table, "SELECT * FROM vendor_offers WHERE NOT limited"))
    con.execute(crafting.costs_sql(table))

    # Fuer die Anzeige nur, was sich im Auktionshaus verkaufen laesst. Zahlen als
    # DOUBLE oder INTEGER, damit im Browser nichts als BigInt ankommt.
    con.execute(
        f"""
        {table} crafts_out AS
        SELECT recipe_id::INTEGER AS recipe_id, name, profession, category, skill::INTEGER AS skill,
               item_id::INTEGER AS item_id, kind, item_count::DOUBLE AS item_count,
               reagents::INTEGER AS reagents, unpriced::INTEGER AS unpriced,
               cost_known::DOUBLE AS cost_known, cost::DOUBLE AS cost, ah_price::DOUBLE AS ah_price,
               profit::DOUBLE AS profit, profit_pct::DOUBLE AS profit_pct,
               n_listings::INTEGER AS n_listings, qty_sold_24h::DOUBLE AS qty_sold_24h,
               sales_hours_24h::FLOAT AS sales_hours_24h,
               learned, trainer_cost::DOUBLE AS trainer_cost, recipe_item_id::INTEGER AS recipe_item_id,
               recipe_price::DOUBLE AS recipe_price, recipe_source,
               item_class, item_subclass, new_in_forever,
               cooldown_seconds::INTEGER AS cooldown_seconds, cast_seconds::DOUBLE AS cast_seconds
        FROM crafts
        WHERE ah_price IS NOT NULL;

        {table} craft_reagents_out AS
        SELECT recipe_id::INTEGER AS recipe_id, item_id::INTEGER AS item_id, name,
               count::INTEGER AS count, unit_price::DOUBLE AS unit_price, source, vendor, zone,
               n_vendors::INTEGER AS n_vendors
        FROM craft_reagents
        WHERE recipe_id IN (SELECT recipe_id FROM crafts_out);
        """
    )
    return con.execute("SELECT count(*) FROM crafts_out").fetchone()[0]


def _iso(epoch_seconds: int | None) -> str | None:
    if epoch_seconds is None:
        return None
    return dt.datetime.fromtimestamp(epoch_seconds, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build(
    settings: Settings,
    out_dir: Path = DEFAULT_OUT,
    house: int | None = None,
    days: int = DEFAULT_DAYS,
    client: Any = None,
) -> dict[str, Any]:
    """Baut alle Dateien. Mit `client` wird zusaetzlich der aktuelle Stand von Blizzard geholt:
    er wird zum juengsten Stand des Markts, und aus seinen Angeboten entsteht die Preisleiter.
    """
    house = house or settings.house
    out_dir = Path(out_dir)

    con = store.connect()
    try:
        _load(con, settings.warehouse_dir, house)
        last = con.execute("SELECT max(snapshot_ts) FROM i").fetchone()[0]
        since = last - dt.timedelta(days=days)

        hourly_rows = _build_hourly(con, since)
        # Stammdaten (Namen, Haendlerpreise) stehen im Warehouse unter ref/items.
        names.load_known(con, settings.warehouse_dir, settings.locale)
        _load_local_details(con, settings)
        _load_local_list(con, settings)
        _empty_live(con)
        live_ts = _load_live(con, settings, house, client) if client is not None else None
        market_rows = _build_market(con, live_ts)

        store.write_parquet(
            con, "hourly", out_dir / HOURLY,
            order_by="item_id, kind, ts",
            compression=COMPRESSION, row_group_size=ROW_GROUP_SIZE,
        )
        store.write_parquet(
            con, "market", out_dir / MARKET,
            order_by="item_id, kind", compression=COMPRESSION,
        )

        # Haendler-Flips gibt es nur mit dem lokalen Abzug. Eine alte Datei darf nicht
        # liegen bleiben, wenn der Abzug fehlt - sie wuerde veraltete Zahlen zeigen.
        # Die Preisleiter gibt es nur mit dem aktuellen Stand. Ohne ihn darf keine alte liegen bleiben.
        ladder_rows = None
        if live_ts is None:
            (out_dir / LADDER).unlink(missing_ok=True)
        else:
            ladder_rows = store.write_parquet(
                con, "ladder", out_dir / LADDER, order_by="item_id, price", compression=COMPRESSION,
            )

        has_vendors = _load_vendor_offers(con, settings)
        flip_rows = _build_vendor_flips(con) if has_vendors else None
        vendor_rows = _build_item_vendors(con) if has_vendors else None
        if vendor_rows is None:
            (out_dir / ITEM_VENDORS).unlink(missing_ok=True)
        else:
            store.write_parquet(
                con, "item_vendors", out_dir / ITEM_VENDORS,
                order_by="item_id, price_per_item", compression=COMPRESSION,
            )
        if flip_rows is None:
            (out_dir / VENDOR_FLIPS).unlink(missing_ok=True)
        else:
            store.write_parquet(
                con, "vendor_flips", out_dir / VENDOR_FLIPS,
                order_by="profit DESC, item_id", compression=COMPRESSION,
            )

        # Dasselbe fuer das Herstellen: nur mit dem Abzug der Rezepte.
        craft_rows = _build_crafts(con, settings)
        if craft_rows is None:
            (out_dir / CRAFTS).unlink(missing_ok=True)
            (out_dir / CRAFT_REAGENTS).unlink(missing_ok=True)
        else:
            store.write_parquet(
                con, "crafts_out", out_dir / CRAFTS,
                order_by="profit DESC NULLS LAST, recipe_id", compression=COMPRESSION,
            )
            store.write_parquet(
                con, "craft_reagents_out", out_dir / CRAFT_REAGENTS,
                order_by="recipe_id, item_id", compression=COMPRESSION,
            )

        # Ohne Namen zeigt die Seite "Item 2589". Zuerst gilt Blizzards Name. Wo Blizzard
        # ein Item nicht kennt, fuellt ein lokaler Abzug von ForeverDB auf - den gibt es
        # nur auf diesem Rechner, in Actions also nie.
        official = names.names_from_known(con)
        fallback = foreverdb_dump.english_names(con, settings)
        item_names = {**fallback, **official}
        # Nur Items, die im Zeitfenster vorkommen. ForeverDB kennt 23.770 Items, die
        # Seite zeigt gut 6.000 - der Rest waere bei jedem Laden mitgeschleppter Ballast.
        shown = {
            str(row[0])
            for row in con.execute("SELECT item_id FROM hourly UNION SELECT item_id FROM market").fetchall()
        }
        item_names = {item_id: name for item_id, name in item_names.items() if item_id in shown}
        names_file = out_dir / NAMES
        if item_names:
            names_file.write_text(
                json.dumps(item_names, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
            )
        market_ids = [str(row[0]) for row in con.execute("SELECT DISTINCT item_id FROM market").fetchall()]
        named_in_market = sum(1 for item_id in market_ids if item_id in item_names)
        named_official = sum(1 for item_id in market_ids if item_id in official)

        first_ts, last_ts, snapshots, with_sales = con.execute(
            "SELECT min(ts), max(ts), count(DISTINCT ts), "
            "count(DISTINCT ts) FILTER (WHERE n_sold IS NOT NULL) FROM hourly"
        ).fetchone()
        row_groups = con.execute(
            f"SELECT count(DISTINCT row_group_id) FROM parquet_metadata('{store.sql_path(out_dir / HOURLY)}')"
        ).fetchone()[0]
    finally:
        con.close()

    meta = {
        "built_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "house": house,
        "window_days": days,
        # Ueber so viele Tage zaehlt der uebliche Preis.
        "usual_days": USUAL_DAYS,
        "first_snapshot": _iso(first_ts),
        "last_snapshot": _iso(last_ts),
        "snapshots": snapshots,
        "snapshots_with_sales": with_sales,
        "items": market_rows,
        # Die Seite fragt names.json nur ab, wenn hier true steht.
        "names": (out_dir / NAMES).is_file(),
        "items_with_name": named_in_market,
        # Die Seite zeigt die Ansicht nur, wenn hier eine Zahl steht.
        "vendor_flips": flip_rows,
        "crafts": craft_rows,
        "item_vendors": vendor_rows,
        # Die Preisleiter und von wann sie ist - oder null ohne aktuellen Stand.
        "ladder": ladder_rows,
        "live_snapshot": _iso(live_ts),
        "name_sources": {"blizzard": named_official, "foreverdb": named_in_market - named_official},
        "files": {
            HOURLY: {
                "rows": hourly_rows,
                "bytes": (out_dir / HOURLY).stat().st_size,
                "row_groups": row_groups,
                "sorted_by": ["item_id", "kind", "ts"],
            },
            MARKET: {"rows": market_rows, "bytes": (out_dir / MARKET).stat().st_size},
        },
    }
    (out_dir / META).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def main(
    settings: Settings,
    out_dir: Path | None = None,
    house: int | None = None,
    days: int = DEFAULT_DAYS,
    live: bool = True,
) -> int:
    target = Path(out_dir or DEFAULT_OUT)
    # Den aktuellen Stand gibt es nur mit Zugangsdaten. Fehlen sie oder ist Blizzard nicht
    # erreichbar, entstehen die uebrigen Dateien trotzdem - nur eben ohne Preisleiter.
    client = None
    if live and settings.client_id and settings.client_secret:
        from .blizzard import BlizzardClient

        client = BlizzardClient(settings)
    try:
        try:
            meta = build(settings, out_dir=target, house=house, days=days, client=client)
        except LiveSnapshotError as exc:
            print(f"{exc} Baue ohne Preisleiter.")
            meta = build(settings, out_dir=target, house=house, days=days)
    except RuntimeError as exc:
        print(exc)
        return 1

    hourly = meta["files"][HOURLY]
    market = meta["files"][MARKET]
    print(f"Haus {meta['house']}, {meta['snapshots']} Staende von {meta['first_snapshot']} bis {meta['last_snapshot']}")
    print(f"  davon mit Verkaufsdaten: {meta['snapshots_with_sales']}")
    print(
        f"  {HOURLY:<15} {hourly['rows']:>9,} Zeilen, {hourly['bytes'] / 1024:>8,.0f} KB, "
        f"{hourly['row_groups']} Zeilengruppen"
    )
    print(f"  {MARKET:<15} {market['rows']:>9,} Zeilen, {market['bytes'] / 1024:>8,.0f} KB")
    if meta["vendor_flips"] is not None:
        print(f"  {VENDOR_FLIPS:<15} {meta['vendor_flips']:>9,} Zeilen")
    if meta["crafts"] is not None:
        print(f"  {CRAFTS:<15} {meta['crafts']:>9,} Zeilen")
    if meta["ladder"] is not None:
        print(f"  {LADDER:<15} {meta['ladder']:>9,} Preisstufen, Stand von {meta['live_snapshot']}")
    else:
        print("  ohne Preisleiter: kein aktueller Stand von Blizzard (Zugangsdaten oder --no-live)")
    sources = meta["name_sources"]
    print(
        f"  Namen fuer {meta['items_with_name']:,} von {meta['items']:,} Items "
        f"({sources['blizzard']:,} von Blizzard, {sources['foreverdb']:,} von ForeverDB)"
    )
    print(f"  nach {target}")
    return 0
