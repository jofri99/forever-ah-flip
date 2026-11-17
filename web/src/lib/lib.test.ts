import type { FileMetaData } from "hyparquet"
import { describe, expect, it } from "vitest"

import { buildGroupIndex, spansFor } from "./data"
import { formatPercent, kindLabel, moneyShort, splitCoins } from "./format"
import { filterRows, itemName, nextSort, rowKey, sortRows } from "./rows"
import type { MarketRow } from "./types"

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
    expect(moneyShort(24)).toBe("24k")
    expect(moneyShort(2049)).toBe("20,49s")
    expect(moneyShort(15_000)).toBe("1,5g")
  })

  it("schreibt Prozente mit Vorzeichen", () => {
    expect(formatPercent(60)).toBe("+60 %")
    expect(formatPercent(-94.3)).toBe("-94,3 %")
    expect(formatPercent(0)).toBe("0 %")
  })

  it("benennt die Art", () => {
    expect(kindLabel("commodity")).toBe("Stapelware")
    expect(kindLabel("auction")).toBe("Einzelstück")
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
