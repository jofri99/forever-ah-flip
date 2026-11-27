import type { FileMetaData } from "hyparquet"
import { describe, expect, it } from "vitest"

import { buildGroupIndex, spansFor } from "./data"
import { craft, marketRow, reagent } from "./test-fixtures"
import {
  formatDays,
  formatDuration,
  formatPercent,
  kindLabel,
  moneyShort,
  moneyText,
  splitCoins,
} from "./format"
import { heatCells, median, priceLevel, soldLevel } from "./heat"
import { HOME, parseHash, toHash } from "./route"
import {
  canCraft,
  cheapestRows,
  craftName,
  craftsByItem,
  groupReagents,
  hasCooldown,
  itemName,
  matches,
  nextSort,
  rowKey,
  sortBy,
  tally,
  usedIn,
} from "./rows"
import type { SeriesPoint } from "./types"

describe("Geld", () => {
  it("zerlegt Kupfer in Gold, Silber, Kupfer", () => {
    expect(splitCoins(2049)).toEqual({ gold: 0, silver: 20, copper: 49 })
    expect(splitCoins(25_000_000)).toEqual({ gold: 2500, silver: 0, copper: 0 })
    expect(splitCoins(123_456)).toEqual({ gold: 12, silver: 34, copper: 56 })
    expect(splitCoins(24)).toEqual({ gold: 0, silver: 0, copper: 24 })
  })

  it("kuerzt fuer die Achse auf die groesste Einheit", () => {
    expect(moneyShort(24)).toBe("24c")
    expect(moneyShort(2049)).toBe("20.49s")
    expect(moneyShort(15_000)).toBe("1.5g")
  })

  it("schreibt Betraege als Text mit zwei Einheiten", () => {
    expect(moneyText(123_456)).toBe("12g 34s")
    expect(moneyText(2049)).toBe("20s 49c")
    expect(moneyText(24)).toBe("24c")
    // Ein Verlust behaelt sein Vorzeichen, ohne Wert steht ein Strich.
    expect(moneyText(-4263)).toBe("−42s 63c")
    expect(moneyText(null)).toBe("–")
  })

  it("schreibt Prozente mit Vorzeichen", () => {
    expect(formatPercent(60)).toBe("+60%")
    expect(formatPercent(-12.34)).toBe("-12.3%")
    expect(formatPercent(0)).toBe("0%")
  })

  it("benennt die Art", () => {
    expect(kindLabel("commodity")).toBe("Commodity")
    expect(kindLabel("auction")).toBe("Single item")
  })

  it("schreibt eine Dauer in der groessten passenden Einheit", () => {
    expect(formatDuration(45)).toBe("45s")
    expect(formatDuration(600)).toBe("10m")
    // Eine Transmutation: 47 Stunden bleiben Stunden, vier Tage werden Tage.
    expect(formatDuration(169_200)).toBe("47h")
    expect(formatDuration(345_600)).toBe("4d")
    expect(formatDays(2.14)).toBe("2.1 d")
    expect(formatDays(0.04)).toBe("< 0.1 d")
  })
})

describe("Zeilen", () => {
  const rows = [
    marketRow({ item_id: 2589, kind: "commodity", min_price: 24, n_listings: 600, change_24h_pct: 4 }),
    marketRow({ item_id: 6592, kind: "auction", min_price: 2049, n_listings: 1, change_24h_pct: null }),
    marketRow({ item_id: 16250, kind: "auction", min_price: 25_000_000, n_listings: 2, change_24h_pct: -9 }),
  ]
  const names = { "2589": "Linen Cloth", "16250": "Formula: Enchant Weapon - Superior Striking" }
  const ids = (list: { item_id: number }[]) => list.map((row) => row.item_id)

  it("bildet den Schluessel aus ID und Art", () => {
    expect(rowKey(rows[0])).toBe("2589:commodity")
  })

  it("faellt ohne Namen auf die ID zurueck", () => {
    expect(itemName(2589, names)).toBe("Linen Cloth")
    expect(itemName(6592, names)).toBe("Item 6592")
  })

  it("sucht in mehreren Texten, ohne Ruecksicht auf Gross und Klein", () => {
    expect(matches("linen", "Linen Cloth")).toBe(true)
    expect(matches("  ", "anything")).toBe(true)
    expect(matches("orgri", "Mahu", "Orgrimmar", null)).toBe(true)
    expect(matches("silk", "Linen Cloth", undefined)).toBe(false)
  })

  it("stellt fehlende Werte in beiden Richtungen ans Ende", () => {
    expect(ids(sortBy(rows, (row) => row.change_24h_pct, -1))).toEqual([2589, 16250, 6592])
    expect(ids(sortBy(rows, (row) => row.change_24h_pct, 1))).toEqual([16250, 2589, 6592])
  })

  it("veraendert das Eingabefeld nicht und sortiert Text nach dem Alphabet", () => {
    const before = ids(rows)
    expect(ids(sortBy(rows, (row) => itemName(row.item_id, names), 1))).toEqual([16250, 6592, 2589])
    expect(ids(rows)).toEqual(before)
  })

  it("sortiert Text aufsteigend, Zahlen absteigend und dreht beim zweiten Klick um", () => {
    expect(nextSort({ key: "profit", dir: -1 }, "name", true)).toEqual({ key: "name", dir: 1 })
    expect(nextSort({ key: "name", dir: 1 }, "profit", false)).toEqual({ key: "profit", dir: -1 })
    expect(nextSort({ key: "profit", dir: -1 }, "profit", false)).toEqual({ key: "profit", dir: 1 })
  })

  it("zaehlt Werte, haeufigste zuerst, und laesst Unbekanntes weg", () => {
    expect(tally(["Recipe", "Armor", "Recipe", null, "Weapon", "Armor", "Recipe"])).toEqual([
      { value: "Recipe", count: 3 },
      { value: "Armor", count: 2 },
      { value: "Weapon", count: 1 },
    ])
  })

  it("nimmt je Item die guenstigere Zeile", () => {
    const both = [
      marketRow({ item_id: 1, kind: "auction", min_price: 500 }),
      marketRow({ item_id: 1, kind: "commodity", min_price: 300 }),
      marketRow({ item_id: 2, kind: "auction", min_price: null }),
    ]
    const cheapest = cheapestRows(both)
    expect(cheapest.get(1)?.kind).toBe("commodity")
    expect(cheapest.get(2)?.min_price).toBeNull()
    expect(cheapest.size).toBe(2)
  })
})

describe("Rezepte", () => {
  const crafts = [
    craft({ recipe_id: 1, item_id: 10, profit: 500 }),
    craft({ recipe_id: 3, item_id: 30, unpriced: 1, cost: null, profit: null }),
    craft({ recipe_id: 4, item_id: 40, profession: "Mining", skill: 250, name: "Smelt Copper" }),
    // Ein zweites Rezept fuer dasselbe Item wie das erste, aber lohnender.
    craft({ recipe_id: 5, item_id: 10, profit: 700, profession: "Cooking", skill: null }),
  ]
  const recipeIds = (list: { recipe_id: number }[] | undefined) => (list ?? []).map((row) => row.recipe_id)

  it("nennt ein Rezept nach dem Item, das es herstellt", () => {
    expect(craftName(crafts[2], { "40": "Copper Bar" })).toBe("Copper Bar")
    expect(craftName(crafts[2], {})).toBe("Smelt Copper")
  })

  it("erkennt eine Abklingzeit", () => {
    expect(hasCooldown(craft({ recipe_id: 9, item_id: 90, cooldown_seconds: 169_200 }))).toBe(true)
    expect(hasCooldown(crafts[0])).toBe(false)
  })

  it("prueft Beruf und Skill des Nutzers", () => {
    expect(canCraft(crafts[0], { Alchemy: 100 })).toBe(true)
    expect(canCraft(crafts[0], { Alchemy: 99 })).toBe(false)
    expect(canCraft(crafts[2], { Alchemy: 300 })).toBe(false)
    // Ohne Angabe zum Skill genuegt der Beruf.
    expect(canCraft(crafts[3], { Cooking: 1 })).toBe(true)
    expect(canCraft(crafts[0], {})).toBe(false)
  })

  it("buendelt Rezepte nach Item, das lohnendste zuerst", () => {
    const byItem = craftsByItem(crafts)
    expect(recipeIds(byItem.get(10))).toEqual([5, 1])
    expect(recipeIds(byItem.get(30))).toEqual([3])
    expect(byItem.get(99)).toBeUndefined()
  })

  it("buendelt Zutaten nach Rezept, teuerster Posten zuerst, ohne Preis ans Ende", () => {
    const groups = groupReagents([
      reagent({ recipe_id: 1, item_id: 100, unit_price: 5, count: 2 }),
      reagent({ recipe_id: 1, item_id: 101, unit_price: null, source: null }),
      reagent({ recipe_id: 1, item_id: 102, unit_price: 3, count: 20 }),
      reagent({ recipe_id: 4, item_id: 100 }),
    ])
    expect(groups.get(1)?.map((row) => row.item_id)).toEqual([102, 100, 101])
    expect(groups.get(4)?.map((row) => row.item_id)).toEqual([100])

    // Und umgekehrt: welche Rezepte ein Item verbrauchen.
    const uses = usedIn(crafts, groups)
    expect(recipeIds(uses.get(100))).toEqual([1, 4])
    expect(recipeIds(uses.get(102))).toEqual([1])
    expect(uses.get(10)).toBeUndefined()
  })
})

describe("Adresse", () => {
  it("liest Seite und Item aus der Adresse", () => {
    expect(parseHash("#crafting")).toEqual({ page: "crafting", id: null })
    expect(parseHash("#reset/3826")).toEqual({ page: "reset", id: 3826 })
    expect(parseHash("#item/3826")).toEqual({ page: "item", id: 3826 })
    expect(parseHash("")).toEqual(HOME)
  })

  it("versteht die alte Form und faengt Unsinn ab", () => {
    expect(parseHash("#12359:commodity")).toEqual({ page: "market", id: 12359 })
    expect(parseHash("#nowhere/12")).toEqual(HOME)
    // Eine Vollseite ohne Item gibt es nicht.
    expect(parseHash("#item")).toEqual(HOME)
    expect(parseHash("#market/abc")).toEqual({ page: "market", id: null })
  })

  it("schreibt sie auch wieder", () => {
    expect(toHash({ page: "low", id: null })).toBe("#low")
    expect(toHash({ page: "item", id: 42 })).toBe("#item/42")
    expect(parseHash(toHash({ page: "shopping", id: 7 }))).toEqual({ page: "shopping", id: 7 })
  })
})

describe("Heatmap", () => {
  const point = (iso: string, min_price: number | null, qty_sold: number | null): SeriesPoint => ({
    item_id: 1,
    kind: "auction",
    ts: new Date(iso).getTime() / 1000,
    min_price,
    median_price: null,
    n_listings: 1,
    qty_sold,
  })

  it("sortiert den Verlauf in Wochentag und Stunde der Ortszeit", () => {
    // Zwei Montage um 20 Uhr und ein Dienstag um 9 Uhr, in Ortszeit geschrieben.
    const cells = heatCells([
      point("2026-11-16T20:10:00", 100, 4),
      point("2026-11-23T20:40:00", 300, 6),
      point("2026-11-17T09:00:00", null, null),
    ])
    expect(cells.size).toBe(2)
    expect(cells.get(0 * 24 + 20)).toEqual({ day: 0, hour: 20, price: 200, sold: 5, samples: 2 })
    // Ohne Preis und ohne Vergleich bleibt die Zelle da, aber leer.
    expect(cells.get(1 * 24 + 9)).toEqual({ day: 1, hour: 9, price: null, sold: 0, samples: 1 })
  })

  it("nimmt den Median und stuft Abweichungen in fuenf Stufen ein", () => {
    expect(median([3, 1, 2])).toBe(2)
    expect(median([4, 1, 2, 3])).toBe(2.5)
    expect(median([])).toBeNull()
    expect([85, 95, 101, 106, 120].map((price) => priceLevel(price, 100))).toEqual([-2, -1, 0, 1, 2])
  })

  it("stuft Mengen relativ zur groessten ein", () => {
    expect([0, 1, 40, 99, 100].map((sold) => soldLevel(sold, 100))).toEqual([0, 1, 2, 5, 5])
    expect(soldLevel(5, 0)).toBe(0)
  })
})

describe("Zeilengruppen", () => {
  // So sieht das Verzeichnis der echten Datei aus: Item 14283 liegt auf der Grenze.
  const metadata = {
    row_groups: [
      { num_rows: 8192n, columns: [{ meta_data: { path_in_schema: ["item_id"], statistics: { min_value: 35, max_value: 14283 } } }] },
      { num_rows: 4606n, columns: [{ meta_data: { path_in_schema: ["item_id"], statistics: { min_value: 14283, max_value: 288206 } } }] },
    ],
  } as unknown as FileMetaData

  const groups = buildGroupIndex(metadata)

  it("rechnet die Zeilenbereiche fortlaufend aus", () => {
    expect(groups).toEqual([
      { start: 0, end: 8192, minItem: 35, maxItem: 14283 },
      { start: 8192, end: 12798, minItem: 14283, maxItem: 288206 },
    ])
  })

  it("findet meist eine Gruppe, an der Grenze beide, ausserhalb keine", () => {
    expect(spansFor(2589, groups)).toHaveLength(1)
    expect(spansFor(2589, groups)[0].start).toBe(0)
    expect(spansFor(14283, groups)).toHaveLength(2)
    expect(spansFor(20000, groups)[0].start).toBe(8192)
    expect(spansFor(1, groups)).toEqual([])
    expect(spansFor(999999, groups)).toEqual([])
  })

  it("meldet eine Datei ohne Statistik klar", () => {
    const broken = { row_groups: [{ num_rows: 1n, columns: [{ meta_data: { path_in_schema: ["item_id"] } }] }] } as unknown as FileMetaData
    expect(() => buildGroupIndex(broken)).toThrow(/Statistik/)
  })
})
