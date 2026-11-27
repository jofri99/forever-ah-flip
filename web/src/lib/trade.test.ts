import { describe, expect, it } from "vitest"

import { craft, flip, marketRow } from "./test-fixtures"
import {
  belowVendor,
  bestReset,
  churn,
  churnLevels,
  craftPerDay,
  craftProfit,
  DEFAULT_ASSUMPTIONS,
  flipPerDay,
  flipProfit,
  isDowntrend,
  isFalling,
  isSpiked,
  lowBuy,
  pickResets,
  plan,
  refillsFast,
  sellAt,
  verdict,
} from "./trade"
import type { Assumptions, Tier } from "./trade"

const a: Assumptions = { ...DEFAULT_ASSUMPTIONS }

describe("Verkaufspreis", () => {
  const row = marketRow({ item_id: 1, min_price: 1000, low_24h: 600, change_24h_pct: 128 })

  it("nimmt das guenstigste Angebot oder, vorsichtiger, das Tief des Tages", () => {
    expect(sellAt(row, "now")).toBe(1000)
    expect(sellAt(row, "low")).toBe(600)
    // Liegt der Preis gerade unter dem Tief des gespeicherten Verlaufs, gilt der aktuelle.
    expect(sellAt(marketRow({ item_id: 1, min_price: 500, low_24h: 600 }), "low")).toBe(500)
    expect(sellAt(marketRow({ item_id: 1 }), "now")).toBeNull()
    expect(sellAt(undefined, "now")).toBeNull()
  })

  it("warnt vor einem frischen Sprung nur, wenn mit dem aktuellen Preis gerechnet wird", () => {
    expect(isSpiked(row, "now")).toBe(true)
    expect(isSpiked(row, "low")).toBe(false)
    expect(isFalling(marketRow({ item_id: 1, change_24h_pct: -30 }))).toBe(true)
    expect(isFalling(marketRow({ item_id: 1, change_24h_pct: -29 }))).toBe(false)
    expect(isFalling(marketRow({ item_id: 1 }))).toBe(false)
  })

  it("nennt es einen Abwaertstrend, wenn der Preis stetig faellt - nicht, wenn er nur schwankt", () => {
    const trend = (trend_pct_day: number | null, trend_fit: number | null) =>
      isDowntrend(marketRow({ item_id: 1, trend_pct_day, trend_fit }))
    expect(trend(-7.7, 0.74)).toBe(true)
    expect(trend(-3, 0.5)).toBe(true)
    // Faellt zu langsam, oder die Gerade passt nicht zum Verlauf: ein Einbruch, kein Trend.
    expect(trend(-2.9, 0.9)).toBe(false)
    expect(trend(-12, 0.3)).toBe(false)
    expect(trend(4, 0.9)).toBe(false)
    expect(trend(null, null)).toBe(false)
    expect(isDowntrend(undefined)).toBe(false)
  })
})

describe("Rezepte und Haendler-Flips", () => {
  const row = marketRow({ item_id: 10, min_price: 1000, low_24h: 800, qty_sold_24h: 200 })

  it("rechnet den Gewinn eines Rezepts mit dem gewaehlten Verkaufspreis", () => {
    const potion = craft({ recipe_id: 1, item_id: 10, cost: 600, item_count: 2 })
    // 2 * 1000 * 0,95 - 600 = 1300; zum Tagestief 2 * 800 * 0,95 - 600 = 920.
    expect(craftProfit(potion, row, "now")).toBe(1300)
    expect(craftProfit(potion, row, "low")).toBe(920)
    expect(craftProfit(craft({ recipe_id: 2, item_id: 10, cost: null }), row, "now")).toBeNull()
    expect(craftProfit(potion, undefined, "now")).toBeNull()
  })

  it("schaetzt den Tagesgewinn aus dem Anteil an den Verkaeufen", () => {
    const potion = craft({ recipe_id: 1, item_id: 10, cost: 600, item_count: 2 })
    // 10 % von 200 verkauften Stueck = 20 Stueck, je Stueck 650 Gewinn.
    expect(craftPerDay(potion, row, a)).toBe(13_000)
    expect(craftPerDay(potion, marketRow({ item_id: 10, min_price: 1000 }), a)).toBeNull()
  })

  it("deckelt den Tagesgewinn durch die Abklingzeit", () => {
    // Alle zwei Tage ein Durchgang: ein halbes Stueck am Tag, egal wie viel verkauft wird.
    const transmute = craft({ recipe_id: 3, item_id: 10, cost: 500, cooldown_seconds: 172_800 })
    expect(craftProfit(transmute, row, "now")).toBe(450)
    expect(craftPerDay(transmute, row, a)).toBe(225)
  })

  it("deckelt den Flip durch den begrenzten Bestand des Haendlers", () => {
    const unlimited = flip({ item_id: 10, vendor_price: 500 })
    expect(flipProfit(unlimited, row, "now")).toBe(450)
    expect(flipPerDay(unlimited, row, a)).toBe(9000)
    expect(flipPerDay(flip({ item_id: 10, vendor_price: 500, limited: true, limited_stock: 2 }), row, a)).toBe(900)
  })

  it("zaehlt, was unter dem Haendlerpreis liegt", () => {
    const cheap = marketRow({ item_id: 5, min_price: 100, vendor_sell: 400 })
    const tiers: Tier[] = [[100, 2], [250, 3], [400, 9], [900, 1]]
    // 2 * 300 + 3 * 150; was genau den Haendlerpreis kostet, bringt nichts mehr.
    expect(belowVendor(cheap, tiers)).toEqual({ itemId: 5, each: 300, units: 5, total: 1050 })
    // Ohne Preisleiter zaehlt wenigstens das eine guenstigste Stueck.
    expect(belowVendor(cheap, undefined)).toEqual({ itemId: 5, each: 300, units: 1, total: 300 })
    // Unter einem Silber Gewinn lohnt der Weg nicht.
    expect(belowVendor(marketRow({ item_id: 5, min_price: 350, vendor_sell: 400 }), tiers)).toBeNull()
    expect(belowVendor(marketRow({ item_id: 5, min_price: 100 }), tiers)).toBeNull()
  })
})

describe("Kaufen und wieder einstellen", () => {
  // Fuenf Stueck fuer 1g, drei fuer 1g 20s, dann eine Luecke bis 3g und eine Wand bei 10g.
  const tiers: Tier[] = [[10_000, 5], [12_000, 3], [30_000, 4], [100_000, 50]]
  const row = marketRow({
    item_id: 7,
    min_price: 10_000,
    usual_price: 30_000,
    usual_points: 200,
    qty_sold_24h: 10,
    qty_new_24h: 20,
    vendor_sell: 1000,
  })

  it("stellt nach einem Reset knapp unter dem naechsten Angebot wieder ein", () => {
    const p = plan(row, tiers, 1, "reset", a)!
    expect(p.units).toBe(8)
    expect(p.cost).toBe(86_000)
    expect(p.average).toBe(10_750)
    expect(p.rule).toBe("next")
    expect(p.target).toBe(29_999)
    expect(p.gross).toBe(239_992)
    expect(p.cut).toBeCloseTo(11_999.6)
    expect(p.profit).toBeCloseTo(141_992.4)
    expect(p.ret).toBeCloseTo(1.651)
    // 86.000 / (29.999 * 0,95) = 3,02: das vierte Stueck bringt das Gold zurueck.
    expect(p.breakeven).toBe(4)
    // Zehn Verkaeufe am Tag gehoeren nach dem Reset alle dem Guenstigsten.
    expect(p.days).toBeCloseTo(0.8)
    expect(p.refill).toBeCloseTo(0.4)
    // Muss alles zum alten Tiefstpreis weg: 8 * 10.000 * 0,95 - 86.000.
    expect(p.worst).toBe(-10_000)
    expect(p.deposit).toBe(2400)
    expect(p.goldShare).toBeCloseTo(0.0172)
    expect(p.rows.map((tier) => [tier.take, tier.units, tier.cost])).toEqual([[5, 5, 50_000], [3, 8, 86_000]])
  })

  it("geht dabei nie weiter als 10 % ueber den ueblichen Preis", () => {
    // Alles bis einschliesslich 3g gekauft: das naechste Angebot waere 10g, das Ziel bleibt bei 3g 30s.
    const p = plan(row, tiers, 2, "reset", a)!
    expect(p.rule).toBe("cap")
    expect(p.target).toBe(33_000)
    expect(p.next).toBe(100_000)
  })

  it("zielt beim guenstigen Einkauf auf den ueblichen Preis und teilt sich die Verkaeufe", () => {
    const p = plan(row, tiers, 1, "usual", a, 6)!
    // Hoechstens sechs Stueck: fuenf aus der ersten Stufe, eines aus der zweiten.
    expect(p.units).toBe(6)
    expect(p.cost).toBe(62_000)
    expect(p.rule).toBe("usual")
    expect(p.target).toBe(30_000)
    // Mit 10 % Anteil an zehn Verkaeufen am Tag dauert das sechs Tage.
    expect(p.days).toBeCloseTo(6)
  })

  it("rechnet nichts ohne Ziel oder ausserhalb der Leiter", () => {
    expect(plan(marketRow({ item_id: 7, min_price: 10_000 }), tiers, 0, "usual", a)).toBeNull()
    expect(plan(row, tiers, 9, "reset", a)).toBeNull()
    expect(plan(row, tiers, -1, "reset", a)).toBeNull()
  })

  it("findet den Reset mit dem meisten Gewinn, den das Gold hergibt", () => {
    // 500g, davon 40 % je Reset: Platz fuer alle drei Stufen; verkaufen lassen sich in 3 Tagen 30 Stueck.
    // Auch die Stufe zum ueblichen Preis lohnt mit: sie hebt das Ziel fuer alle auf 3g 30s.
    const all = bestReset(row, tiers, a)!
    expect(all.k).toBe(2)
    expect(all.target).toBe(33_000)
    expect(all.profit).toBeCloseTo(12 * 33_000 * 0.95 - 206_000)
    // Mit 30g sind 12g je Reset erlaubt: die dritte Stufe ist nicht mehr bezahlbar.
    const some = bestReset(row, tiers, { ...a, gold: 30 })!
    expect(some.k).toBe(1)
    expect(some.target).toBe(29_999)
    // Mit 15g bleibt nur die erste Stufe: 5 * 11.999 * 0,95 - 50.000 = 6995, also 14 % - zu wenig Rendite.
    expect(bestReset(row, tiers, { ...a, gold: 15 })).toBeNull()
  })

  it("laesst die Finger von Resets, die sich nicht absetzen lassen", () => {
    // Ein Verkauf am Tag: in drei Tagen gehen keine fuenf Stueck weg.
    expect(bestReset({ ...row, qty_sold_24h: 1 }, tiers, a)).toBeNull()
    expect(bestReset({ ...row, qty_sold_24h: null }, tiers, a)).toBeNull()
    expect(bestReset({ ...row, usual_price: null }, tiers, a)).toBeNull()
    expect(bestReset(row, [[10_000, 5]], a)).toBeNull()
    expect(bestReset(row, undefined, a)).toBeNull()
  })

  it("kauft guenstig nur bis zur Kaufgrenze und nur, was der eigene Anteil absetzt", () => {
    // Grenze 80 % von 3g = 2g 40s: die ersten beiden Stufen. Anteil 10 % von 10 am Tag, 3 Tage: 3 Stueck.
    const p = lowBuy(row, tiers, a)!
    expect(p.k).toBe(1)
    expect(p.units).toBe(3)
    expect(p.cost).toBe(30_000)
    expect(p.profit).toBe(3 * 30_000 * 0.95 - 30_000)
    // Bei 30 % Kaufgrenze liegt nichts mehr darunter.
    expect(lowBuy(row, tiers, { ...a, buyAt: 0.3 })).toBeNull()
    expect(lowBuy({ ...row, usual_price: null }, tiers, a)).toBeNull()
  })

  it("waehlt die Resets, die zusammen ins Gold passen, beste Rendite zuerst", () => {
    const first = plan(row, tiers, 1, "reset", a)!
    const second = { ...plan(row, tiers, 0, "reset", a)!, itemId: 8 }
    const third = { ...plan(row, tiers, 2, "reset", a)!, itemId: 9 }
    // 20g: der kleine (5g) und der mittlere (8g 60s) passen, der grosse (20g 60s) nicht mehr.
    const picked = pickResets([third, first, second], { ...a, gold: 20 })
    expect([...picked.picked].sort()).toEqual([7, 8])
    expect(picked.used).toBe(first.cost + second.cost)
    expect(picked.profit).toBeCloseTo(first.profit + second.profit)
  })
})

describe("Nachschub und Urteil", () => {
  const market = [
    marketRow({ item_id: 1, qty_sold_24h: 100, qty_new_24h: 150 }),
    marketRow({ item_id: 2, qty_sold_24h: 100, qty_new_24h: 250 }),
    marketRow({ item_id: 3, qty_sold_24h: 100, qty_new_24h: 300 }),
    marketRow({ item_id: 4, qty_sold_24h: 100, qty_new_24h: 600 }),
    // Zu wenig Absatz: zaehlt nicht fuer die Schwellen.
    marketRow({ item_id: 5, qty_sold_24h: 2, qty_new_24h: 400 }),
    marketRow({ item_id: 6 }),
  ]
  const levels = churnLevels(market)

  it("misst den Nachschub am Markt, nicht an einer festen Zahl", () => {
    expect(churn(market[0])).toBe(1.5)
    expect(churn(market[5])).toBeNull()
    expect(levels).toEqual({ typical: 3, fast: 6 })
    expect(refillsFast(market[3], levels)).toBe(true)
    expect(refillsFast(market[2], levels)).toBe(false)
    // Ohne Daten gibt es vernuenftige Vorgaben.
    expect(churnLevels([])).toEqual({ typical: 3, fast: 4 })
  })

  it("nennt das schwerste Problem zuerst", () => {
    const tiers: Tier[] = [[10_000, 5], [30_000, 4]]
    const steady = marketRow({ item_id: 7, min_price: 10_000, usual_price: 30_000, qty_sold_24h: 10, qty_new_24h: 20 })
    const p = plan(steady, tiers, 0, "reset", a)!
    expect(verdict(p, steady, a, levels)).toBe("workable")
    expect(verdict(p, { ...steady, qty_new_24h: 80 }, a, levels)).toBe("refills-fast")
    expect(verdict(p, { ...steady, qty_new_24h: 80, change_24h_pct: -45 }, a, levels)).toBe("falling")
    expect(verdict(p, { ...steady, qty_new_24h: 80, trend_pct_day: -8, trend_fit: 0.8 }, a, levels)).toBe("downtrend")
    expect(verdict(p, steady, { ...a, gold: 4 }, levels)).toBe("workable")
    expect(verdict(plan(steady, tiers, 0, "reset", { ...a, gold: 4 })!, steady, { ...a, gold: 4 }, levels)).toBe("too-expensive")
    expect(verdict(plan(steady, tiers, 0, "reset", a)!, steady, { ...a, horizon: 0.25 }, levels)).toBe("slow")
    const unsold = { ...steady, qty_sold_24h: null }
    expect(verdict(plan(unsold, tiers, 0, "reset", a)!, unsold, a, levels)).toBe("no-sales")
    // Teurer gekauft, als es wieder einbringt.
    const dear = marketRow({ item_id: 7, min_price: 10_000, usual_price: 8000, qty_sold_24h: 10 })
    expect(verdict(plan(dear, tiers, 0, "usual", a)!, dear, a, levels)).toBe("loss")
  })
})
