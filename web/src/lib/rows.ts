import type { Craft, CraftReagent, MarketRow, Names, Professions, Sort } from "./types"

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

/** Zaehlt Werte, haeufigste zuerst. Fehlende bleiben weg. */
export function tally(values: (string | null)[]): Option[] {
  const counts = new Map<string, number>()
  for (const value of values) {
    if (value) counts.set(value, (counts.get(value) ?? 0) + 1)
  }
  return [...counts]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value))
}

/** Passt der Suchtext auf einen der Texte? Ein leerer Suchtext passt immer. */
export function matches(query: string, ...texts: (string | number | null | undefined)[]): boolean {
  const needle = query.trim().toLowerCase()
  return !needle || texts.some((text) => text != null && String(text).toLowerCase().includes(needle))
}

/**
 * Sortiert, ohne das Eingabefeld zu veraendern. Fehlende Werte stehen immer am
 * Ende, egal in welche Richtung sortiert wird - sonst fuellt "keine Angabe" beim
 * Umdrehen die ersten Zeilen.
 */
export function sortBy<T>(
  rows: readonly T[],
  value: (row: T) => number | string | null | undefined,
  dir: 1 | -1,
): T[] {
  return rows
    .map((row, index) => ({ row, index, key: value(row) }))
    .sort((a, b) => {
      if (a.key == null && b.key == null) return a.index - b.index
      if (a.key == null) return 1
      if (b.key == null) return -1
      const order =
        typeof a.key === "string" || typeof b.key === "string"
          ? String(a.key).localeCompare(String(b.key), "en")
          : a.key - b.key
      return order * dir || a.index - b.index
    })
    .map((entry) => entry.row)
}

/** Erster Klick auf eine Spalte sortiert absteigend, bei Text aufsteigend; der zweite dreht um. */
export function nextSort(current: Sort, key: string, textual: boolean): Sort {
  if (current.key === key) return { key, dir: current.dir === 1 ? -1 : 1 }
  return { key, dir: textual ? 1 : -1 }
}

/** Je Item die guenstigere Zeile, falls es Einzelstueck und Stapelware zugleich gibt. */
export function cheapestRows(market: readonly MarketRow[]): Map<number, MarketRow> {
  const rows = new Map<number, MarketRow>()
  for (const row of market) {
    const known = rows.get(row.item_id)
    if (!known || (row.min_price ?? Infinity) < (known.min_price ?? Infinity)) rows.set(row.item_id, row)
  }
  return rows
}

/** Der Name, unter dem ein Rezept in der Tabelle steht: das Item, das es herstellt. */
export function craftName(row: Pick<Craft, "item_id" | "name">, names: Names): string {
  return names[String(row.item_id)] ?? row.name
}

/** Laesst sich das Rezept nur alle paar Stunden oder Tage wirken? */
export function hasCooldown(row: Pick<Craft, "cooldown_seconds">): boolean {
  return row.cooldown_seconds != null && row.cooldown_seconds > 0
}

/** Kann der Nutzer das Rezept mit seinen Berufen und seinem Skill herstellen? */
export function canCraft(craft: Pick<Craft, "profession" | "skill">, professions: Professions): boolean {
  const skill = professions[craft.profession]
  return skill != null && (craft.skill == null || craft.skill <= skill)
}

function groupBy<T>(rows: readonly T[], key: (row: T) => number): Map<number, T[]> {
  const groups = new Map<number, T[]>()
  for (const row of rows) {
    const group = groups.get(key(row))
    if (group) group.push(row)
    else groups.set(key(row), [row])
  }
  return groups
}

/** Die Zutaten nach Rezept gebuendelt, teuerster Posten zuerst, ohne Preis ans Ende. */
export function groupReagents(rows: readonly CraftReagent[]): Map<number, CraftReagent[]> {
  const groups = groupBy(rows, (row) => row.recipe_id)
  const total = (row: CraftReagent) => (row.unit_price == null ? -1 : row.unit_price * row.count)
  for (const group of groups.values()) {
    group.sort((a, b) => total(b) - total(a) || a.item_id - b.item_id)
  }
  return groups
}

/** Die Rezepte nach dem Item gebuendelt, das sie herstellen - das lohnendste zuerst. */
export function craftsByItem(rows: readonly Craft[]): Map<number, Craft[]> {
  const groups = groupBy(rows, (row) => row.item_id)
  for (const group of groups.values()) {
    group.sort((a, b) => (b.profit ?? -Infinity) - (a.profit ?? -Infinity) || a.recipe_id - b.recipe_id)
  }
  return groups
}

/** Welche Rezepte ein Item verbrauchen: Item -> Rezepte, in denen es Zutat ist. */
export function usedIn(crafts: readonly Craft[], reagents: Map<number, CraftReagent[]>): Map<number, Craft[]> {
  const uses = new Map<number, Craft[]>()
  for (const craft of crafts) {
    for (const reagent of reagents.get(craft.recipe_id) ?? []) {
      const list = uses.get(reagent.item_id)
      if (list) list.push(craft)
      else uses.set(reagent.item_id, [craft])
    }
  }
  return uses
}
