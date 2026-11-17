import type { KindFilter, MarketRow, Names, Sort } from "./types"

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
export function categories(rows: MarketRow[]): Option[] {
  return tally(rows.map((row) => row.item_class))
}

/** Die Untertypen eines Typs - bei Rezepten die Berufe. */
export function subcategories(rows: MarketRow[], category: string): Option[] {
  return tally(rows.filter((row) => row.item_class === category).map((row) => row.item_subclass))
}

export function filterRows(
  rows: MarketRow[],
  query: string,
  kind: KindFilter,
  names: Names,
  category: string = ALL,
  subcategory: string = ALL,
): MarketRow[] {
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
  return [...rows].sort((a, b) => {
    if (key === "name") {
      return (
        itemName(a.item_id, names).localeCompare(itemName(b.item_id, names), "de") * dir ||
        a.item_id - b.item_id
      )
    }
    const x = a[key]
    const y = b[key]
    if (x == null && y == null) return a.item_id - b.item_id
    if (x == null) return 1
    if (y == null) return -1
    return (x - y) * dir || a.item_id - b.item_id
  })
}

/** Erster Klick auf eine Spalte sortiert absteigend, bei Namen aufsteigend; der zweite dreht um. */
export function nextSort(current: Sort, key: Sort["key"]): Sort {
  if (current.key === key) return { key, dir: current.dir === 1 ? -1 : 1 }
  return { key, dir: key === "name" ? 1 : -1 }
}
