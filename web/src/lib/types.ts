/** Die Formen der Dateien, die `python -m collector publish` schreibt. */

export type Kind = "auction" | "commodity"

/** Eine Zeile aus market.parquet: der juengste Stand eines Items. */
export interface MarketRow {
  item_id: number
  kind: Kind
  ts: number
  min_price: number | null
  p25_price: number | null
  median_price: number | null
  n_listings: number
  quantity: number
  snapshots_24h: number | null
  qty_sold_24h: number | null
  value_sold_24h: number | null
  /** Wie viele der letzten 24 Stunden durch Vergleiche gedeckt sind. */
  sales_hours_24h: number | null
  low_24h: number | null
  high_24h: number | null
  open_24h: number | null
  change_24h_pct: number | null
  /** Typ, z. B. "Recipe" oder "Armor". Fehlt, wenn keine Quelle das Item kennt. */
  item_class: string | null
  /** Untertyp, bei Rezepten der Beruf. */
  item_subclass: string | null
  /** Was ein Haendler fuer das Item zahlt, in Kupfer. Fehlt, wenn die API das Item nicht kennt. */
  vendor_sell: number | null
  /** Listenpreis beim Haendler je Stueck. Steht bei jedem Item, auch wenn es kein Haendler fuehrt. */
  vendor_buy: number | null
  /** Der uebliche Preis: Median des guenstigsten Angebots der letzten Tage (`usual_days`). Fehlt bei zu kurzer Geschichte. */
  usual_price: number | null
  /** Auf wie vielen Staenden der uebliche Preis beruht. */
  usual_points: number
  /**
   * Der Trend ueber das ganze Zeitfenster: Aenderung des guenstigsten Angebots in Prozent
   * je Tag, und wie genau der Verlauf einer Geraden folgt (0 bis 1). Fehlt bei kurzer Geschichte.
   */
  trend_pct_day: number | null
  trend_fit: number | null
  /** Wie viele Stueck in 24 Stunden neu eingestellt wurden. */
  qty_new_24h: number | null
  /** Marktwert des aktuellen Stands nach TSMs Verfahren. Nur mit Preisleiter. */
  market_value: number | null
}

/** Eine Zeile aus hourly.parquet, auf die Spalten des Diagramms beschraenkt. */
export interface SeriesPoint {
  item_id: number
  kind: Kind
  /** Unix-Sekunden, UTC. */
  ts: number
  min_price: number | null
  median_price: number | null
  n_listings: number
  qty_sold: number | null
}

export interface Meta {
  built_at: string
  house: number
  window_days: number
  /** Ueber so viele Tage zaehlt der uebliche Preis. Fehlt in aelteren Builds. */
  usual_days?: number
  first_snapshot: string
  last_snapshot: string
  snapshots: number
  snapshots_with_sales: number
  items: number
  names: boolean
  /** Wie viele Items im Markt ihren Namen aus welcher Quelle haben. */
  name_sources?: { blizzard: number; foreverdb: number }
  /** Zahl der Haendler-Flips, oder null, wenn es die Datei nicht gibt. */
  vendor_flips?: number | null
  /** Zahl der Rezepte, deren Ergebnis im Auktionshaus steht - oder null ohne Abzug. */
  crafts?: number | null
  /** Zahl der Zeilen in item_vendors.parquet - oder null ohne Abzug der Haendler. */
  item_vendors?: number | null
  /** Zahl der Preisstufen in ladder.parquet - oder null ohne aktuellen Stand von Blizzard. */
  ladder?: number | null
  /** Von wann der aktuelle Stand ist, aus dem Preisleiter und Marktpreise stammen. */
  live_snapshot?: string | null
}

/** Item-ID als Text -> Name. Fehlt ein Eintrag, zeigt die Seite "Item 2589". */
export type Names = Record<string, string>

export interface Sort<K extends string = string> {
  key: K
  /** 1 aufsteigend, -1 absteigend. */
  dir: 1 | -1
}

/** Eine Zeile aus vendor_flips.parquet: beim Haendler kaufen, im Auktionshaus verkaufen. */
export interface VendorFlip {
  item_id: number
  kind: Kind
  item_class: string | null
  item_subclass: string | null
  /** Preis je Stueck beim guenstigsten erreichbaren Haendler. */
  vendor_price: number
  /** Guenstigstes Angebot im Auktionshaus. */
  ah_price: number
  /** Gewinn je Stueck nach 5 % Gebuehr des Auktionshauses. */
  profit: number
  profit_pct: number
  n_listings: number
  qty_sold_24h: number | null
  sales_hours_24h: number | null
  /** Der Haendler hat nur einen begrenzten Bestand. */
  limited: boolean
  limited_stock: number | null
  vendor: string
  zone: string | null
  side: string
  reputation: string | null
  seen_in_forever: boolean | null
}

/** Wie man ein Rezept lernt. */
export type Learned = "automatic" | "trainer" | "recipe" | "unknown"

/** Woher ein Preis stammt: Auktionshaus oder Haendler. */
export type PriceSource = "ah" | "vendor"

/**
 * Eine Zeile aus crafts.parquet: ein Rezept, dessen Ergebnis im Auktionshaus steht.
 * Kosten und Gewinn gelten fuer einen Durchgang, also fuer `item_count` Stueck.
 */
export interface Craft {
  recipe_id: number
  /** Name des Rezepts - meist der des Items, beim Verhuetten z. B. "Smelt Copper". */
  name: string
  profession: string
  /** Gruppe im Berufsfenster, z. B. "Potions". */
  category: string | null
  /** Ab diesem Skill lernbar. */
  skill: number | null
  /** Was das Rezept herstellt. */
  item_id: number
  kind: Kind
  /** Stueck je Durchgang; bei zufaelliger Menge die Mitte. */
  item_count: number
  /** Zahl der Zutaten, und wie viele davon gerade keinen Preis haben. */
  reagents: number
  unpriced: number
  /** Summe der Zutaten mit Preis. */
  cost_known: number
  /** Kosten aller Zutaten - fehlt, sobald eine keinen Preis hat. */
  cost: number | null
  /** Guenstigstes Angebot des Ergebnisses im Auktionshaus, je Stueck. */
  ah_price: number
  /** Gewinn je Durchgang nach 5 % Gebuehr des Auktionshauses. */
  profit: number | null
  profit_pct: number | null
  n_listings: number
  qty_sold_24h: number | null
  sales_hours_24h: number | null
  learned: Learned
  trainer_cost: number | null
  /** Das Item, das das Rezept lehrt, mit dem, was es gerade kostet. */
  recipe_item_id: number | null
  recipe_price: number | null
  recipe_source: PriceSource | null
  item_class: string | null
  item_subclass: string | null
  new_in_forever: boolean
  /** So lange sperrt ein Durchgang den naechsten, in Sekunden. Fehlt ohne Abklingzeit. */
  cooldown_seconds: number | null
  /** So lange dauert ein Durchgang, in Sekunden. */
  cast_seconds: number | null
}

/** Eine Zeile aus craft_reagents.parquet: eine Zutat eines Rezepts mit ihrem Preis. */
export interface CraftReagent {
  recipe_id: number
  item_id: number
  name: string
  count: number
  /** Guenstigster Preis je Stueck - fehlt, wenn das Item gerade nirgends zu haben ist. */
  unit_price: number | null
  source: PriceSource | null
  /** Nur beim Haendler: einer, der es verkauft, wo er steht, und wie viele es insgesamt fuehren. */
  vendor: string | null
  zone: string | null
  n_vendors: number | null
}

/** Eine Zeile aus item_vendors.parquet: einer der guenstigsten Haendler, die ein Item fuehren. */
export interface ItemVendor {
  item_id: number
  vendor: string
  zone: string | null
  price_per_item: number
  limited: boolean
  limited_stock: number | null
  /** Wie viele erreichbare Haendler das Item insgesamt fuehren. */
  n_vendors: number
}

/** Eine Zeile aus ladder.parquet: eine Stufe der Preisleiter. */
export interface LadderRow {
  item_id: number
  price: number
  quantity: number
}

/** Wie gut der Nutzer einen Beruf beherrscht: Beruf -> Skill. */
export type Professions = Record<string, number>

/** Eine Zeile der Einkaufsliste: ein Rezept und wie oft es hergestellt werden soll. */
export interface CartLine {
  recipeId: number
  quantity: number
}
