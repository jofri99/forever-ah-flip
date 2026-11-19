import type {
  Craft,
  CraftReagent,
  CraftSortKey,
  FlipSortKey,
  Kind,
  KindFilter,
  MarketRow,
  Names,
  Sort,
  VendorFlip,
} from "./types"

/** Was Markt- und Flip-Zeilen gemeinsam haben - genug zum Filtern. */
interface Classified {
  item_id: number
  kind: Kind
  item_class: string | null
  item_subclass: string | null
}

/** Ein Item kann es als Einzelstueck und als Stapelware geben - beides zusammen ist der Schluessel. */
export function rowKey(row: Pick<MarketRow, "item_id" | "kind">): string {
  return `${row.item_id}:${row.kind}`
}

export function itemName(itemId: number, names: Names): string {
  return names[String(itemId)] ?? `Item ${itemId}`
}

/** Kennzeichnet in den Filtern "keine Einschraenkung". */
export const ALL = "all"

export interface Option {
  value: string
  count: number
}

function tally(values: (string | null)[]): Option[] {
  const counts = new Map<string, number>()
  for (const value of values) {
    if (value) counts.set(value, (counts.get(value) ?? 0) + 1)
  }
  return [...counts]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value))
}

/** Die Typen, die im Markt vorkommen, haeufigste zuerst. */
export function categories(rows: Classified[]): Option[] {
  return tally(rows.map((row) => row.item_class))
}

/** Die Untertypen eines Typs - bei Rezepten die Berufe. */
export function subcategories(rows: Classified[], category: string): Option[] {
  return tally(rows.filter((row) => row.item_class === category).map((row) => row.item_subclass))
}

export function filterRows<T extends Classified>(
  rows: T[],
  query: string,
  kind: KindFilter,
  names: Names,
  category: string = ALL,
  subcategory: string = ALL,
): T[] {
  const needle = query.trim().toLowerCase()
  return rows.filter((row) => {
    if (kind !== "all" && row.kind !== kind) return false
    if (category !== ALL && row.item_class !== category) return false
    if (subcategory !== ALL && row.item_subclass !== subcategory) return false
    if (!needle) return true
    return (
      String(row.item_id) === needle ||
      itemName(row.item_id, names).toLowerCase().includes(needle)
    )
  })
}

/**
 * Sortiert, ohne das Eingabefeld zu veraendern. Fehlende Werte stehen immer am
 * Ende, egal in welche Richtung sortiert wird - sonst fuellt "keine Angabe" beim
 * Umdrehen die ersten Zeilen.
 */
export function sortRows(rows: MarketRow[], sort: Sort, names: Names): MarketRow[] {
  const { key, dir } = sort
  return sortBy(rows, key === "name" ? (row) => itemName(row.item_id, names) : (row) => row[key], dir)
}

/** Dasselbe fuer die Haendler-Flips. */
export function sortFlips(rows: VendorFlip[], sort: Sort<FlipSortKey>, names: Names): VendorFlip[] {
  const { key, dir } = sort
  return sortBy(rows, key === "name" ? (row) => itemName(row.item_id, names) : (row) => row[key], dir)
}

function sortBy<T extends { item_id: number }>(
  rows: T[],
  value: (row: T) => number | string | null | undefined,
  dir: 1 | -1,
): T[] {
  return [...rows].sort((a, b) => {
    const x = value(a)
    const y = value(b)
    if (x == null && y == null) return a.item_id - b.item_id
    if (x == null) return 1
    if (y == null) return -1
    const order =
      typeof x === "string" || typeof y === "string"
        ? String(x).localeCompare(String(y), "en")
        : x - y
    return order * dir || a.item_id - b.item_id
  })
}

/** Die Haendler-Flips weiter einschraenken: nur unbegrenzter Bestand, nur mit Verkaeufen. */
export function filterFlips(
  rows: VendorFlip[],
  options: { unlimitedOnly: boolean; soldOnly: boolean },
): VendorFlip[] {
  return rows.filter((row) => {
    if (options.unlimitedOnly && row.limited) return false
    if (options.soldOnly && !(row.qty_sold_24h != null && row.qty_sold_24h > 0)) return false
    return true
  })
}

/** Der Name, unter dem ein Rezept in der Tabelle steht: das Item, das es herstellt. */
export function craftName(row: Pick<Craft, "item_id" | "name">, names: Names): string {
  return names[String(row.item_id)] ?? row.name
}

/** Die Berufe, die in den Rezepten vorkommen, haeufigste zuerst. */
export function professions(rows: Craft[]): Option[] {
  return tally(rows.map((row) => row.profession))
}

/** Die Gruppen eines Berufs, wie das Berufsfenster sie zeigt - etwa Potions, Elixirs. */
export function craftCategories(rows: Craft[], profession: string): Option[] {
  return tally(rows.filter((row) => row.profession === profession).map((row) => row.category))
}

export interface CraftFilter {
  query: string
  profession: string
  category: string
  /** Nur Rezepte, bei denen nach Kosten und Gebuehr etwas uebrig bleibt. */
  profitableOnly: boolean
  /** Nur Rezepte, deren Ergebnis in den letzten 24 Stunden verkauft wurde. */
  soldOnly: boolean
}

export function filterCrafts(rows: Craft[], filter: CraftFilter, names: Names): Craft[] {
  const needle = filter.query.trim().toLowerCase()
  return rows.filter((row) => {
    if (filter.profession !== ALL && row.profession !== filter.profession) return false
    if (filter.category !== ALL && row.category !== filter.category) return false
    if (filter.profitableOnly && !(row.profit != null && row.profit > 0)) return false
    if (filter.soldOnly && !(row.qty_sold_24h != null && row.qty_sold_24h > 0)) return false
    if (!needle) return true
    return (
      String(row.item_id) === needle ||
      craftName(row, names).toLowerCase().includes(needle) ||
      row.name.toLowerCase().includes(needle)
    )
  })
}

export function sortCrafts(rows: Craft[], sort: Sort<CraftSortKey>, names: Names): Craft[] {
  const { key, dir } = sort
  return sortBy(rows, key === "name" ? (row) => craftName(row, names) : (row) => row[key], dir)
}

/** Die Zutaten nach Rezept gebuendelt, teuerster Posten zuerst, ohne Preis ans Ende. */
export function groupReagents(rows: CraftReagent[]): Map<number, CraftReagent[]> {
  const groups = new Map<number, CraftReagent[]>()
  for (const row of rows) {
    const group = groups.get(row.recipe_id)
    if (group) group.push(row)
    else groups.set(row.recipe_id, [row])
  }
  const total = (row: CraftReagent) => (row.unit_price == null ? -1 : row.unit_price * row.count)
  for (const group of groups.values()) {
    group.sort((a, b) => total(b) - total(a) || a.item_id - b.item_id)
  }
  return groups
}

/** Die Rezepte nach dem Item gebuendelt, das sie herstellen - das lohnendste zuerst. */
export function craftsByItem(rows: Craft[]): Map<number, Craft[]> {
  const groups = new Map<number, Craft[]>()
  for (const row of rows) {
    const group = groups.get(row.item_id)
    if (group) group.push(row)
    else groups.set(row.item_id, [row])
  }
  for (const group of groups.values()) {
    group.sort((a, b) => (b.profit ?? -Infinity) - (a.profit ?? -Infinity) || a.recipe_id - b.recipe_id)
  }
  return groups
}

/** Erster Klick auf eine Spalte sortiert absteigend, bei Text aufsteigend; der zweite dreht um. */
export function nextSort<K extends string>(current: Sort<K>, key: K): Sort<K> {
  if (current.key === key) return { key, dir: current.dir === 1 ? -1 : 1 }
  return { key, dir: key === "name" || key === "vendor" || key === "profession" ? 1 : -1 }
}
