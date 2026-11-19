"""Das Schema der Stammdaten: die festen Tabellen der lokalen Datenbank.

Stammdaten aendern sich nur mit einem neuen Spielstand - Items, Haendler und ihr
Sortiment, Rezepte und ihre Zutaten. Sie liegen als Tabellen mit Schluesseln in der
Datenbank. Was sich stuendlich aendert - Staende, Verkaeufe, Preise - bleibt in den
Parquet-Dateien des Warehouse, und die Datenbank schaut mit Sichten darauf.

    items ─┬─< vendor_stock >── vendors
           ├─< recipe_reagents >─┐
           ├─< recipe_items >────┼── recipes
           └── recipes.item_id ──┘      (was ein Rezept herstellt)

Ein Primaerschluessel haelt jede Zeile eindeutig. Die Zeilen eines Rezepts und eines
Haendlers haengen ueber einen Fremdschluessel an ihrem Kopf. Verweise auf Items sind
bewusst keine Fremdschluessel: ForeverDB nennt Zutaten und Ergebnisse, die in seiner
eigenen Item-Liste fehlen, und daran soll der Bau nicht scheitern. `db` zaehlt diese
Verweise stattdessen und nennt sie.

Die Reihenfolge ist die, in der die Tabellen angelegt und gefuellt werden.
"""

from __future__ import annotations

TABLES: dict[str, str] = {
    # Ein Item, wie beide Quellen zusammen es beschreiben. Blizzard gilt zuerst,
    # ForeverDB fuellt auf, was Blizzard nicht kennt.
    "items": """
        CREATE TABLE items (
            item_id        INTEGER PRIMARY KEY,
            name           VARCHAR,
            quality        VARCHAR,           -- COMMON, UNCOMMON, RARE, EPIC ...
            item_class     VARCHAR,           -- Recipe, Armor, Trade Goods ...
            item_subclass  VARCHAR,           -- bei Rezepten der Beruf
            inventory_type VARCHAR,
            item_level     INTEGER,
            required_level INTEGER,
            is_stackable   BOOLEAN,
            vendor_sell    BIGINT,            -- was ein Haendler zahlt, in Kupfer
            vendor_buy     DOUBLE,            -- Listenpreis je Stueck; steht auch da, wenn es kein Haendler fuehrt
            icon           VARCHAR,
            foreverdb_url  VARCHAR,
            bonding        VARCHAR,
            disenchantable BOOLEAN,
            in_blizzard    BOOLEAN NOT NULL,
            in_foreverdb   BOOLEAN NOT NULL,
            has_details    BOOLEAN NOT NULL   -- einzeln von ForeverDB abgezogen
        )
    """,
    "vendors": """
        CREATE TABLE vendors (
            vendor_id       INTEGER PRIMARY KEY,
            name            VARCHAR,
            title           VARCHAR,
            side            VARCHAR,          -- Alliance, Horde oder both
            zone            VARCHAR,
            x               DOUBLE,
            y               DOUBLE,
            reputation      VARCHAR,          -- die Fraktion, deren Ruf den Preis senkt
            seen_in_forever BOOLEAN
        )
    """,
    # Was ein Haendler verkauft. Fuehrt er ein Item zweimal, gilt das guenstigere Angebot.
    "vendor_stock": """
        CREATE TABLE vendor_stock (
            vendor_id       INTEGER NOT NULL REFERENCES vendors (vendor_id),
            item_id         INTEGER NOT NULL,
            item_name       VARCHAR,
            price           BIGINT,           -- fuer einen Kauf, also fuer `stack` Stueck
            stack           INTEGER,
            price_per_item  DOUBLE,
            limited         BOOLEAN,
            limited_stock   INTEGER,
            classic_data    BOOLEAN,          -- aus Classic uebernommen, in Forever nicht bestaetigt
            seen_in_forever BOOLEAN,
            PRIMARY KEY (vendor_id, item_id)
        )
    """,
    # Je Item der guenstigste Haendler, den die Horde erreicht und der unbegrenzt liefert.
    "vendor_prices": """
        CREATE TABLE vendor_prices (
            item_id      INTEGER PRIMARY KEY,
            vendor_price DOUBLE NOT NULL,
            vendor       VARCHAR,
            zone         VARCHAR,
            n_vendors    BIGINT NOT NULL      -- wie viele solche Haendler das Item fuehren
        )
    """,
    # Ein Rezept: was es herstellt, was man dafuer koennen muss, wie man es lernt.
    "recipes": """
        CREATE TABLE recipes (
            recipe_id       INTEGER PRIMARY KEY,   -- die ID des Zaubers
            name            VARCHAR,
            profession      VARCHAR,          -- Alchemy, First Aid ...
            profession_slug VARCHAR,          -- alchemy, first-aid ...
            category        VARCHAR,          -- Gruppe im Berufsfenster: Potions, Elixirs ...
            skill           INTEGER,          -- ab diesem Skill lernbar
            skill_yellow    INTEGER,
            skill_green     INTEGER,
            skill_grey      INTEGER,
            required_level  INTEGER,
            item_id         INTEGER,          -- was es herstellt; fehlt bei Verzauberungen
            item_count      DOUBLE,           -- Stueck je Durchgang; bei zufaelliger Menge die Mitte
            learned         VARCHAR NOT NULL, -- trainer, recipe, automatic oder unknown
            trainer_cost    BIGINT,
            recipe_item_id  INTEGER,          -- das erste Item, das es lehrt; alle stehen in recipe_items
            ways            VARCHAR[],        -- trainer, vendor, drop, quest, auto
            new_in_forever  BOOLEAN NOT NULL,
            url             VARCHAR
        )
    """,
    # Die Zutaten: eine Zeile je Rezept und Item.
    "recipe_reagents": """
        CREATE TABLE recipe_reagents (
            recipe_id INTEGER NOT NULL REFERENCES recipes (recipe_id),
            item_id   INTEGER NOT NULL,
            name      VARCHAR,
            count     INTEGER NOT NULL,
            PRIMARY KEY (recipe_id, item_id)
        )
    """,
    # Die Items, die ein Rezept lehren. Ein Rezept kann mehrere haben, viele haben keins.
    "recipe_items": """
        CREATE TABLE recipe_items (
            recipe_id INTEGER NOT NULL REFERENCES recipes (recipe_id),
            item_id   INTEGER NOT NULL,
            name      VARCHAR,
            PRIMARY KEY (recipe_id, item_id)
        )
    """,
}

# Woraus die Datenbank gebaut wurde. Daran erkennt sie, dass Stammdaten sich geaendert haben.
BUILD_INFO = "CREATE TABLE build_info (built_at TIMESTAMP NOT NULL, sources VARCHAR NOT NULL)"

# Verweise auf Items, denen kein Fremdschluessel nachgeht: Tabelle, Spalte.
ITEM_REFERENCES: tuple[tuple[str, str], ...] = (
    ("vendor_stock", "item_id"),
    ("recipes", "item_id"),
    ("recipes", "recipe_item_id"),
    ("recipe_reagents", "item_id"),
    ("recipe_items", "item_id"),
)
