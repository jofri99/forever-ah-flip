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
}

/** Item-ID als Text -> Name. Fehlt ein Eintrag, zeigt die Seite "Item 2589". */
export type Names = Record<string, string>

export type SortKey =
  | "name"
  | "min_price"
  | "median_price"
  | "n_listings"
  | "quantity"
  | "change_24h_pct"
  | "qty_sold_24h"
  | "value_sold_24h"

export interface Sort<K extends string = SortKey> {
  key: K
  /** 1 aufsteigend, -1 absteigend. */
  dir: 1 | -1
}

export type KindFilter = "all" | Kind

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

export type FlipSortKey =
  | "name"
  | "vendor_price"
  | "ah_price"
  | "profit"
  | "profit_pct"
  | "n_listings"
  | "qty_sold_24h"
  | "vendor"
