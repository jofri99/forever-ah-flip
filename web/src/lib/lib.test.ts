import type { FileMetaData } from "hyparquet"
import { describe, expect, it } from "vitest"

import { buildGroupIndex, spansFor } from "./data"
import { formatDuration, formatPercent, kindLabel, moneyShort, splitCoins } from "./format"
import {
  ALL,
  categories,
  craftCategories,
  craftName,
  craftsByItem,
  filterCrafts,
  filterFlips,
  filterRows,
  groupReagents,
  hasCooldown,
  itemName,
  nextSort,
  professions,
  rowKey,
  sortCrafts,
  sortFlips,
  sortRows,
  subcategories,
} from "./rows"
import type { Craft, CraftReagent, MarketRow, VendorFlip } from "./types"

function row(partial: Partial<MarketRow> & Pick<MarketRow, "item_id">): MarketRow {
  return {
    kind: "auction",
    ts: 0,
    min_price: null,
    p25_price: null,
    median_price: null,
    n_listings: 0,
    quantity: 0,
    snapshots_24h: null,
    qty_sold_24h: null,
    value_sold_24h: null,
    sales_hours_24h: null,
    low_24h: null,
    high_24h: null,
    open_24h: null,
    change_24h_pct: null,
    item_class: null,
    item_subclass: null,
    vendor_sell: null,
    vendor_buy: null,
    ...partial,
  }
}

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

  it("schreibt Prozente mit Vorzeichen", () => {
    expect(formatPercent(60)).toBe("+60%")
    expect(formatPercent(-94.3)).toBe("-94.3%")
    expect(formatPercent(0)).toBe("0%")
  })

  it("benennt die Art", () => {
    expect(kindLabel("commodity")).toBe("Commodity")
    expect(kindLabel("auction")).toBe("Single item")
  })
})

describe("Zeilen", () => {
  const names = { "2589": "Leinenstoff" }
  const rows = [
    row({ item_id: 2589, kind: "commodity", min_price: 24, qty_sold_24h: 900 }),
    row({ item_id: 12359, kind: "commodity", min_price: 2049, qty_sold_24h: null }),
    row({ item_id: 4409, min_price: 200, qty_sold_24h: 3 }),
    row({ item_id: 7, min_price: null, qty_sold_24h: null }),
  ]

  it("bildet den Schluessel aus ID und Art", () => {
    expect(rowKey(rows[0])).toBe("2589:commodity")
  })

  it("faellt ohne Namen auf die ID zurueck", () => {
    expect(itemName(2589, names)).toBe("Leinenstoff")
    expect(itemName(4409, names)).toBe("Item 4409")
  })

  it("filtert nach Art, Name und exakter ID", () => {
    expect(filterRows(rows, "", "commodity", names).map((r) => r.item_id)).toEqual([2589, 12359])
    expect(filterRows(rows, "leinen", "all", names).map((r) => r.item_id)).toEqual([2589])
    // Die ID muss ganz stimmen: "7" findet Item 7, nicht jedes mit einer 7 darin.
    expect(filterRows(rows, "7", "all", names).map((r) => r.item_id)).toEqual([7])
    expect(filterRows(rows, " 4409 ", "all", names).map((r) => r.item_id)).toEqual([4409])
  })

  it("stellt fehlende Werte in beiden Richtungen ans Ende", () => {
    const down = sortRows(rows, { key: "min_price", dir: -1 }, names).map((r) => r.item_id)
    const up = sortRows(rows, { key: "min_price", dir: 1 }, names).map((r) => r.item_id)
    expect(down).toEqual([12359, 4409, 2589, 7])
    expect(up).toEqual([2589, 4409, 12359, 7])

    const sold = sortRows(rows, { key: "qty_sold_24h", dir: 1 }, names).map((r) => r.item_id)
    expect(sold).toEqual([4409, 2589, 7, 12359])
  })

  it("veraendert das Eingabefeld nicht", () => {
    const before = rows.map((r) => r.item_id)
    sortRows(rows, { key: "min_price", dir: 1 }, names)
    expect(rows.map((r) => r.item_id)).toEqual(before)
  })

  it("sortiert Namen aufsteigend und dreht beim zweiten Klick um", () => {
    expect(nextSort({ key: "n_listings", dir: -1 }, "name")).toEqual({ key: "name", dir: 1 })
    expect(nextSort({ key: "n_listings", dir: -1 }, "min_price")).toEqual({ key: "min_price", dir: -1 })
    expect(nextSort({ key: "min_price", dir: -1 }, "min_price")).toEqual({ key: "min_price", dir: 1 })
  })
})

describe("Typen", () => {
  const rows = [
    row({ item_id: 1, item_class: "Recipe", item_subclass: "Tailoring" }),
    row({ item_id: 2, item_class: "Recipe", item_subclass: "Tailoring" }),
    row({ item_id: 3, item_class: "Recipe", item_subclass: "Alchemy" }),
    row({ item_id: 4, item_class: "Armor", item_subclass: "Cloth" }),
    row({ item_id: 5 }),
  ]

  it("zaehlt die Typen, haeufigste zuerst, und laesst Unbekanntes weg", () => {
    expect(categories(rows)).toEqual([
      { value: "Recipe", count: 3 },
      { value: "Armor", count: 1 },
    ])
    expect(subcategories(rows, "Recipe")).toEqual([
      { value: "Tailoring", count: 2 },
      { value: "Alchemy", count: 1 },
    ])
  })

  it("filtert nach Typ und Untertyp", () => {
    const ids = (category: string, subcategory = ALL) =>
      filterRows(rows, "", "all", {}, category, subcategory).map((r) => r.item_id)
    expect(ids(ALL)).toEqual([1, 2, 3, 4, 5])
    expect(ids("Recipe")).toEqual([1, 2, 3])
    expect(ids("Recipe", "Alchemy")).toEqual([3])
    expect(ids("Armor", "Alchemy")).toEqual([])
  })
})

describe("Haendler-Flips", () => {
  const flip = (partial: Partial<VendorFlip> & Pick<VendorFlip, "item_id">): VendorFlip => ({
    kind: "auction",
    item_class: "Recipe",
    item_subclass: "Tailoring",
    vendor_price: 100,
    ah_price: 200,
    profit: 90,
    profit_pct: 90,
    n_listings: 1,
    qty_sold_24h: null,
    sales_hours_24h: null,
    limited: false,
    limited_stock: null,
    vendor: "Mahu",
    zone: "Thunder Bluff",
    side: "Horde",
    reputation: null,
    seen_in_forever: true,
    ...partial,
  })
  const flips = [
    flip({ item_id: 1, profit: 500, limited: true, qty_sold_24h: 2, vendor: "Qia" }),
    flip({ item_id: 2, profit: 900, qty_sold_24h: 0, vendor: "Happy Camper" }),
    flip({ item_id: 3, profit: 100, qty_sold_24h: 7, vendor: "Mahu" }),
  ]

  it("sortiert nach Gewinn und nach Haendler", () => {
    expect(sortFlips(flips, { key: "profit", dir: -1 }, {}).map((f) => f.item_id)).toEqual([2, 1, 3])
    expect(sortFlips(flips, { key: "vendor", dir: 1 }, {}).map((f) => f.item_id)).toEqual([2, 3, 1])
    // Ohne Verkaufsdaten ans Ende, auch absteigend.
    const withGap = [...flips, flip({ item_id: 4, qty_sold_24h: null })]
    expect(sortFlips(withGap, { key: "qty_sold_24h", dir: -1 }, {}).map((f) => f.item_id)).toEqual([3, 1, 2, 4])
  })

  it("blendet begrenzten Bestand und Ladenhueter aus", () => {
    const ids = (unlimitedOnly: boolean, soldOnly: boolean) =>
      filterFlips(flips, { unlimitedOnly, soldOnly }).map((f) => f.item_id)
    expect(ids(false, false)).toEqual([1, 2, 3])
    expect(ids(true, false)).toEqual([2, 3])
    // 0 verkauft zaehlt nicht als verkauft.
    expect(ids(false, true)).toEqual([1, 3])
    expect(ids(true, true)).toEqual([3])
  })

  it("laesst sich wie der Markt nach Typ und Namen filtern", () => {
    const names = { "3": "Pattern: Red Linen Bag" }
    expect(filterRows(flips, "linen", "all", names).map((f) => f.item_id)).toEqual([3])
    expect(filterRows(flips, "", "all", names, "Recipe", "Alchemy")).toEqual([])
    expect(nextSort({ key: "profit", dir: -1 }, "vendor")).toEqual({ key: "vendor", dir: 1 })
  })
})

describe("Rezepte", () => {
  const craft = (partial: Partial<Craft> & Pick<Craft, "recipe_id" | "item_id">): Craft => ({
    name: `Recipe ${partial.recipe_id}`,
    profession: "Alchemy",
    category: "Potions",
    skill: 100,
    kind: "commodity",
    item_count: 1,
    reagents: 2,
    unpriced: 0,
    cost_known: 100,
    cost: 100,
    ah_price: 200,
    profit: 90,
    profit_pct: 90,
    n_listings: 1,
    qty_sold_24h: null,
    sales_hours_24h: null,
    learned: "trainer",
    trainer_cost: 500,
    recipe_item_id: null,
    recipe_price: null,
    recipe_source: null,
    item_class: "Consumable",
    item_subclass: "Potion",
    new_in_forever: false,
    cooldown_seconds: null,
    cast_seconds: null,
    ...partial,
  })
  const crafts = [
    craft({ recipe_id: 1, item_id: 10, profit: 500, qty_sold_24h: 4 }),
    craft({ recipe_id: 2, item_id: 20, profit: -50, profit_pct: -10, qty_sold_24h: 9, category: "Elixirs" }),
    // Eine Zutat ohne Preis: keine Kosten, kein Gewinn.
    craft({ recipe_id: 3, item_id: 30, unpriced: 1, cost: null, profit: null, profit_pct: null }),
    craft({ recipe_id: 4, item_id: 40, profit: 900, qty_sold_24h: 0, profession: "Mining", category: "Smelted Bars", name: "Smelt Copper" }),
    // Ein zweites Rezept fuer dasselbe Item wie das erste, aber lohnender.
    craft({ recipe_id: 5, item_id: 10, profit: 700, profession: "Cooking", category: null }),
  ]
  const everything = {
    query: "",
    profession: ALL,
    category: ALL,
    profitableOnly: false,
    soldOnly: false,
    noCooldown: false,
  }
  const ids = (rows: Craft[]) => rows.map((row) => row.recipe_id)

  it("nennt ein Rezept nach dem Item, das es herstellt", () => {
    expect(craftName(crafts[3], { "40": "Copper Bar" })).toBe("Copper Bar")
    expect(craftName(crafts[3], {})).toBe("Smelt Copper")
  })

  it("zaehlt Berufe und ihre Gruppen", () => {
    expect(professions(crafts)).toEqual([
      { value: "Alchemy", count: 3 },
      { value: "Cooking", count: 1 },
      { value: "Mining", count: 1 },
    ])
    expect(craftCategories(crafts, "Alchemy")).toEqual([
      { value: "Potions", count: 2 },
      { value: "Elixirs", count: 1 },
    ])
    // Ein Rezept ohne Gruppe ergibt keine leere Auswahl.
    expect(craftCategories(crafts, "Cooking")).toEqual([])
  })

  it("filtert nach Beruf, Gruppe, Gewinn und Verkaeufen", () => {
    expect(ids(filterCrafts(crafts, everything, {}))).toEqual([1, 2, 3, 4, 5])
    expect(ids(filterCrafts(crafts, { ...everything, profession: "Alchemy" }, {}))).toEqual([1, 2, 3])
    expect(ids(filterCrafts(crafts, { ...everything, profession: "Alchemy", category: "Elixirs" }, {}))).toEqual([2])
    // Verlust und fehlender Preis sind beide nicht lohnend.
    expect(ids(filterCrafts(crafts, { ...everything, profitableOnly: true }, {}))).toEqual([1, 4, 5])
    // 0 verkauft zaehlt nicht als verkauft.
    expect(ids(filterCrafts(crafts, { ...everything, soldOnly: true }, {}))).toEqual([1, 2])
  })

  it("blendet Rezepte mit Abklingzeit aus", () => {
    const transmute = craft({ recipe_id: 9, item_id: 90, cooldown_seconds: 169_200 })
    expect(hasCooldown(transmute)).toBe(true)
    expect(hasCooldown(crafts[0])).toBe(false)
    const rows = [...crafts, transmute]
    expect(ids(filterCrafts(rows, everything, {}))).toContain(9)
    expect(ids(filterCrafts(rows, { ...everything, noCooldown: true }, {}))).toEqual([1, 2, 3, 4, 5])
  })

  it("schreibt eine Dauer in der groessten passenden Einheit", () => {
    expect(formatDuration(45)).toBe("45s")
    expect(formatDuration(600)).toBe("10m")
    // Eine Transmutation: 47 Stunden bleiben Stunden, vier Tage werden Tage.
    expect(formatDuration(169_200)).toBe("47h")
    expect(formatDuration(345_600)).toBe("4d")
  })

  it("findet ein Rezept ueber den Namen des Items, den eigenen Namen und die ID", () => {
    const names = { "40": "Copper Bar" }
    expect(ids(filterCrafts(crafts, { ...everything, query: "copper bar" }, names))).toEqual([4])
    expect(ids(filterCrafts(crafts, { ...everything, query: "smelt" }, names))).toEqual([4])
    expect(ids(filterCrafts(crafts, { ...everything, query: "10" }, names))).toEqual([1, 5])
  })

  it("sortiert nach Gewinn und stellt Rezepte ohne Preis ans Ende", () => {
    expect(ids(sortCrafts(crafts, { key: "profit", dir: -1 }, {}))).toEqual([4, 5, 1, 2, 3])
    expect(ids(sortCrafts(crafts, { key: "profit", dir: 1 }, {}))).toEqual([2, 1, 5, 4, 3])
    expect(nextSort({ key: "profit", dir: -1 }, "profession")).toEqual({ key: "profession", dir: 1 })
  })

  it("buendelt Rezepte nach Item, das lohnendste zuerst", () => {
    const byItem = craftsByItem(crafts)
    expect(ids(byItem.get(10) ?? [])).toEqual([5, 1])
    expect(ids(byItem.get(30) ?? [])).toEqual([3])
    expect(byItem.get(99)).toBeUndefined()
  })

  it("buendelt Zutaten nach Rezept, teuerster Posten zuerst, ohne Preis ans Ende", () => {
    const reagent = (partial: Partial<CraftReagent> & Pick<CraftReagent, "recipe_id" | "item_id">): CraftReagent => ({
      name: `Item ${partial.item_id}`,
      count: 1,
      unit_price: 10,
      source: "ah",
      vendor: null,
      zone: null,
      n_vendors: null,
      ...partial,
    })
    const groups = groupReagents([
      reagent({ recipe_id: 1, item_id: 100, unit_price: 5, count: 2 }),
      reagent({ recipe_id: 1, item_id: 101, unit_price: null, source: null }),
      reagent({ recipe_id: 1, item_id: 102, unit_price: 3, count: 20 }),
      reagent({ recipe_id: 2, item_id: 100 }),
    ])
    expect(groups.get(1)?.map((row) => row.item_id)).toEqual([102, 100, 101])
    expect(groups.get(2)?.map((row) => row.item_id)).toEqual([100])
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
