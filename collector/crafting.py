"""Das Modell fuers Herstellen: Rezepte, Zutaten, Preise - und was dabei herauskommt.

Die Rohdaten sind der Abzug der Berufe von ForeverDB (recipes.jsonl, eine Zeile je
Rezept). Daraus entstehen hier die Tabellen, mit denen sich rechnen laesst:

    recipes          ein Rezept: Beruf, Skill, was es herstellt, wie man es lernt
    recipe_reagents  die Zutaten eines Rezepts mit Menge
    recipe_items     die Items, die ein Rezept lehren
    item_prices      was ein Item kostet, wenn man es kaufen muss
    craft_reagents   die Zutaten mit Preis und Bezugsquelle
    crafts           je Rezept: Kosten, Erloes, Gewinn

Dieselben Definitionen gelten an zwei Stellen: in der lokalen Datenbank als
Sichten und beim Bauen der Anzeige-Dateien als Tabellen. Wer sie benutzt, stellt
drei Dinge bereit und bekommt den Rest:

    foreverdb_recipes  die Rezepte, wie `recipes_source` sie liest
    ah_prices          je Item das guenstigste Angebot im Auktionshaus:
                       item_id, kind, ah_price, n_listings, qty_sold_24h,
                       sales_hours_24h, item_class, item_subclass
    vendor_prices      je Item der guenstigste erreichbare Haendler mit
                       unbegrenztem Bestand - siehe `vendor_prices_sql`
"""

from __future__ import annotations

from . import foreverdb_dump, store
from .config import Settings

# Was das Auktionshaus vom Verkaufspreis behaelt.
AH_CUT = 0.05

# Viele Zutaten fuehrt jeder zweite Haendler zum selben Preis. Genannt wird dann einer,
# zu dem man ohnehin kommt, statt irgendeiner am Ende der Welt.
HUBS = ("Orgrimmar", "Thunder Bluff", "Undercity")

# Ein Rezept, wie /professions/{slug} es liefert, auf das beschraenkt, was das
# Modell braucht. `count` ist die feste Menge, `min`/`max` gibt es bei zufaelliger.
RECIPE_COLUMNS = (
    "profession VARCHAR, professionName VARCHAR, spellId INTEGER, name VARCHAR, icon VARCHAR, "
    "category STRUCT(id INTEGER, name VARCHAR, parent STRUCT(id INTEGER, name VARCHAR)), "
    "skill STRUCT(orange INTEGER, yellow INTEGER, green INTEGER, grey INTEGER), "
    "requiredLevel INTEGER, "
    "makes STRUCT(itemId INTEGER, name VARCHAR, count DOUBLE, min DOUBLE, max DOUBLE, quality VARCHAR), "
    "reagents STRUCT(itemId INTEGER, name VARCHAR, count INTEGER)[], "
    "learnedFrom STRUCT(automatic BOOLEAN, trainer STRUCT(cost BIGINT, trainers INTEGER), "
    "recipeItems STRUCT(itemId INTEGER, name VARCHAR)[], "
    "sources STRUCT(ways VARCHAR[], learnAtSkill INTEGER, trainerCost BIGINT, "
    "trainersInAll STRUCT(alliance INTEGER, horde INTEGER))), "
    "newInForever BOOLEAN, speculation BOOLEAN, url VARCHAR"
)


def recipes_source(settings: Settings) -> str | None:
    """Die abgezogenen Rezepte als Abfrage, oder None, wenn es den Abzug nicht gibt."""
    target = foreverdb_dump.dump_dir(settings) / foreverdb_dump.RECIPES_FILE
    if not target.is_file() or target.stat().st_size == 0:
        return None
    # Ein Rezept kann bei zwei Berufen stehen. Im Modell ist es eines: sonst zaehlten
    # seine Zutaten doppelt. Es gilt der Beruf, der im Alphabet zuerst kommt.
    return (
        f"SELECT * FROM read_json('{store.sql_path(target)}', format = 'newline_delimited', "
        f"columns = {store.json_columns(RECIPE_COLUMNS)}, ignore_errors = true) "
        "WHERE spellId IS NOT NULL "
        "QUALIFY row_number() OVER (PARTITION BY spellId ORDER BY profession) = 1"
    )


def vendor_prices_sql(create: str, offers: str) -> str:
    """Je Item der guenstigste Haendler und wie viele es insgesamt fuehren.

    `offers` ist eine Abfrage mit item_id, price_per_item, vendor, zone und vendor_id,
    schon beschraenkt auf Haendler, die erreichbar sind und unbegrenzt liefern.
    """
    hubs = ", ".join(f"'{zone}'" for zone in HUBS)
    return f"""
{create} vendor_prices AS
SELECT item_id, price_per_item AS vendor_price, vendor, zone,
       count(*) OVER (PARTITION BY item_id) AS n_vendors
FROM ({offers})
QUALIFY row_number() OVER (
    PARTITION BY item_id
    ORDER BY price_per_item, coalesce(zone IN ({hubs}), false) DESC, vendor_id
) = 1;
"""


def model_sql(create: str) -> str:
    """Rezepte, Zutaten und Rezept-Items aus `foreverdb_recipes`.

    `create` ist der Anfang der Anweisung: "CREATE OR REPLACE VIEW" in der
    Datenbank, "CREATE OR REPLACE TEMP TABLE" beim Bauen der Anzeige-Dateien.
    """
    return f"""
-- Ein Rezept: was es herstellt, was man dafuer koennen muss und wie man es lernt.
-- `item_id` fehlt bei Rezepten, die nichts Handelbares herstellen (Verzauberungen).
{create} recipes AS
SELECT r.spellId                                             AS recipe_id,
       r.name,
       coalesce(r.professionName, r.profession)              AS profession,
       r.profession                                          AS profession_slug,
       r.category.name                                       AS category,
       coalesce(r.learnedFrom.sources.learnAtSkill, r.skill.orange) AS skill,
       r.skill.yellow                                        AS skill_yellow,
       r.skill.green                                         AS skill_green,
       r.skill.grey                                          AS skill_grey,
       r.requiredLevel                                       AS required_level,
       r.makes.itemId                                        AS item_id,
       -- Bei zufaelliger Menge die Mitte zwischen kleinster und groesster.
       CASE WHEN r.makes.itemId IS NOT NULL
            THEN coalesce(r.makes.count, (r.makes.min + r.makes.max) / 2.0, 1.0)
       END                                                   AS item_count,
       CASE WHEN r.learnedFrom.automatic THEN 'automatic'
            WHEN r.learnedFrom.trainer IS NOT NULL
              OR r.learnedFrom.sources.trainerCost IS NOT NULL THEN 'trainer'
            WHEN len(coalesce(r.learnedFrom.recipeItems, [])) > 0 THEN 'recipe'
            ELSE 'unknown'
       END                                                   AS learned,
       coalesce(r.learnedFrom.sources.trainerCost, r.learnedFrom.trainer.cost) AS trainer_cost,
       r.learnedFrom.recipeItems[1].itemId                   AS recipe_item_id,
       r.learnedFrom.sources.ways                            AS ways,
       coalesce(r.newInForever, false)                       AS new_in_forever,
       r.url
FROM foreverdb_recipes r;

-- Die Zutaten: eine Zeile je Rezept und Item.
{create} recipe_reagents AS
SELECT r.spellId AS recipe_id, g.itemId AS item_id, g.name, g.count
FROM foreverdb_recipes r, unnest(r.reagents) AS t(g)
WHERE g.itemId IS NOT NULL;

-- Die Items, die ein Rezept lehren. Ein Rezept kann mehrere haben, viele haben keins.
{create} recipe_items AS
SELECT r.spellId AS recipe_id, i.itemId AS item_id, i.name
FROM foreverdb_recipes r, unnest(r.learnedFrom.recipeItems) AS t(i)
WHERE i.itemId IS NOT NULL;
"""


def costs_sql(create: str) -> str:
    """Preise und Rechnung. Setzt recipes, recipe_reagents, ah_prices und vendor_prices voraus."""
    keep = 1 - AH_CUT
    cheaper_at_vendor = "v.vendor_price IS NOT NULL AND (a.ah_price IS NULL OR v.vendor_price <= a.ah_price)"
    return f"""
-- Was ein Item kostet, wenn man es kaufen muss: beim Haendler oder im Auktionshaus,
-- je nachdem, was guenstiger ist. Ein Item ohne Zeile ist gerade nirgends zu haben.
{create} item_prices AS
SELECT item_id,
       a.ah_price,
       v.vendor_price,
       v.vendor,
       v.zone,
       v.n_vendors,
       CASE WHEN {cheaper_at_vendor} THEN v.vendor_price ELSE a.ah_price END AS buy_price,
       CASE WHEN {cheaper_at_vendor} THEN 'vendor'
            WHEN a.ah_price IS NOT NULL THEN 'ah'
       END                                                                   AS buy_source
FROM ah_prices a
FULL OUTER JOIN vendor_prices v USING (item_id);

-- Die Zutaten mit ihrem Preis. Ohne Preis bleiben unit_price und total leer.
{create} craft_reagents AS
SELECT g.recipe_id, g.item_id, g.name, g.count,
       p.buy_price                                         AS unit_price,
       p.buy_source                                        AS source,
       CASE WHEN p.buy_source = 'vendor' THEN p.vendor END AS vendor,
       CASE WHEN p.buy_source = 'vendor' THEN p.zone END   AS zone,
       CASE WHEN p.buy_source = 'vendor' THEN p.n_vendors END AS n_vendors,
       g.count * p.buy_price                               AS total
FROM recipe_reagents g
LEFT JOIN item_prices p USING (item_id);

-- Je Rezept, was die Zutaten kosten und was das Ergebnis im Auktionshaus bringt.
-- `cost` und `profit` stehen nur da, wenn jede Zutat einen Preis hat; `cost_known`
-- ist die Summe der bekannten. `profit` gilt fuer einen Durchgang, also fuer
-- `item_count` Stueck, und rechnet die Gebuehr des Auktionshauses schon ab.
{create} crafts AS
WITH cost AS (
    SELECT recipe_id,
           count(*)                                   AS reagents,
           count(*) FILTER (WHERE unit_price IS NULL) AS unpriced,
           coalesce(sum(total), 0)                    AS cost_known
    FROM craft_reagents
    GROUP BY recipe_id
)
SELECT r.recipe_id, r.name, r.profession, r.category, r.skill,
       r.item_id, a.kind, r.item_count,
       c.reagents, c.unpriced, c.cost_known,
       CASE WHEN c.unpriced = 0 THEN c.cost_known END                  AS cost,
       a.ah_price,
       CASE WHEN c.unpriced = 0
            THEN round(a.ah_price * r.item_count * {keep} - c.cost_known)
       END                                                             AS profit,
       CASE WHEN c.unpriced = 0 AND c.cost_known > 0
            THEN round((a.ah_price * r.item_count * {keep} - c.cost_known) * 100.0 / c.cost_known)
       END                                                             AS profit_pct,
       a.n_listings, a.qty_sold_24h, a.sales_hours_24h,
       r.learned, r.trainer_cost, r.recipe_item_id,
       rp.buy_price                                                    AS recipe_price,
       rp.buy_source                                                   AS recipe_source,
       a.item_class, a.item_subclass, r.new_in_forever
FROM recipes r
JOIN cost c USING (recipe_id)
LEFT JOIN ah_prices a ON a.item_id = r.item_id
LEFT JOIN item_prices rp ON rp.item_id = r.recipe_item_id;
"""
