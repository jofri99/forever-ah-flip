import { describe, expect, it } from "vitest"

import { buyScore, scoreLevel } from "./score"
import { marketRow } from "./test-fixtures"
import { DEFAULT_ASSUMPTIONS } from "./trade"
import type { Tier } from "./trade"

const a = DEFAULT_ASSUMPTIONS // 10 % Anteil, 3 Tage, 500 Gold
const levels = { typical: 3, fast: 4 }

// Ueblich ein Gold, 100 verkauft am Tag, und in den letzten 24 Stunden stand der Preis noch dort.
const row = marketRow({ item_id: 1, usual_price: 10_000, qty_sold_24h: 100, high_24h: 10_000 })
// 30 Stueck zum halben Preis; was darueber liegt, bringt nach der Gebuehr kaum noch etwas.
const tiers: Tier[] = [
  [5_000, 30],
  [9_000, 10],
  [9_600, 10],
]

describe("Kauf-Score", () => {
  it("rechnet Marge, Gewinn, Absatz und Frische zusammen", () => {
    const result = buyScore(row, tiers, a, levels)
    // Der eigene Anteil setzt in drei Tagen 30 Stueck ab: genau die guenstige Stufe.
    expect(result.plan).toMatchObject({ units: 30, cost: 150_000, profit: 135_000 })
    expect(result.margin).toBeCloseTo(0.9) // 90 % Rendite
    expect(result.profit).toBeCloseTo(Math.log(27) / Math.log(200)) // 13,5 Gold zwischen 50 Silber und 100 Gold
    expect(result.demand).toBe(1)
    expect(result.fresh).toBe(1)
    expect(result.score).toBe(75)
    expect(result.why).toBeNull()
  })

  it("zieht fuer einen Abwaertstrend und schnellen Nachschub ab", () => {
    expect(buyScore({ ...row, trend_pct_day: -8, trend_fit: 0.8 }, tiers, a, levels)).toMatchObject({
      score: 19,
      downtrend: true,
    })
    // Fuenf neue Stueck je verkauftem: das schnellste Viertel des Markts.
    expect(buyScore({ ...row, qty_new_24h: 500 }, tiers, a, levels)).toMatchObject({ score: 60, refillsFast: true })
  })

  it("wertet einen Preis ab, der schon den ganzen Tag tief steht", () => {
    expect(buyScore({ ...row, high_24h: 7_500 }, tiers, a, levels)).toMatchObject({ fresh: 0.5, score: 37 })
    expect(buyScore({ ...row, high_24h: 6_000 }, tiers, a, levels).score).toBe(0)
    // Ohne Stand aus den letzten 24 Stunden: halbe Punktzahl.
    expect(buyScore({ ...row, high_24h: null }, tiers, a, levels).fresh).toBe(0.5)
  })

  it("wertet ab, was sich im Zeitraum nicht absetzen laesst", () => {
    // Ein teures Einzelstueck, eines verkauft sich am Tag: der eigene Anteil braucht zehn Tage.
    const rare = marketRow({ item_id: 2, usual_price: 1_000_000, qty_sold_24h: 1, high_24h: 1_000_000 })
    const result = buyScore(rare, [[500_000, 1]], a, levels)
    expect(result.demand).toBeCloseTo(0.3)
    expect(result.score).toBe(26)
    expect(buyScore({ ...rare, qty_sold_24h: null }, [[500_000, 1]], a, levels).score).toBe(0)
  })

  it("kauft nicht mehr, als das Gold hergibt", () => {
    const result = buyScore(row, tiers, { ...a, gold: 10 }, levels)
    expect(result.plan).toMatchObject({ units: 20, cost: 100_000 })
    // Mit zehn Gold gilt die Untergrenze: volle Punktzahl ab zehn Gold Gewinn.
    expect(result.fullProfit).toBe(100_000)
  })

  it("gibt null Punkte, wenn sich nichts lohnt, und keinen Score, wenn sich nichts messen laesst", () => {
    expect(buyScore(row, [[9_600, 5]], a, levels)).toMatchObject({ score: 0, why: "not-cheap" })
    expect(buyScore(row, tiers, { ...a, gold: 0 }, levels)).toMatchObject({ score: 0, why: "no-gold" })
    // 50 Kupfer Gewinn sind keinen Punkt wert.
    expect(buyScore(row, [[9_400, 1]], a, levels).score).toBe(0)
    expect(buyScore({ ...row, usual_price: null }, tiers, a, levels)).toMatchObject({ score: null, why: "no-usual" })
    expect(buyScore(row, undefined, a, levels)).toMatchObject({ score: null, why: "no-ladder" })
  })

  it("fasst den Score in ein Wort", () => {
    expect([85, 70, 55, 40, 20, 15, 14, 0].map(scoreLevel)).toEqual([
      "strong", "strong", "decent", "decent", "thin", "thin", "skip", "skip",
    ])
  })
})
