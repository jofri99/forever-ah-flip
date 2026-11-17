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

export interface Sort {
  key: SortKey
  /** 1 aufsteigend, -1 absteigend. */
  dir: 1 | -1
}

export type KindFilter = "all" | Kind
