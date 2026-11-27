import { describe, expect, it } from "vitest"

import { lookback, relist } from "./relist"
import { marketRow, seriesPoint } from "./test-fixtures"
import type { Tier } from "./trade"

const HOUR = 3_600

/** Stuendliche Staende: der Preis jeder Stunde kommt aus `price`. */
const hourly = (hours: number, price: (hour: number) => number) =>
  Array.from({ length: hours }, (_, hour) => seriesPoint(hour * HOUR, price(hour)))

// Fuenf Tage: zwoelf Stunden 100, zwoelf Stunden 150, und wieder von vorn.
const swinging = hourly(120, (hour) => (hour % 24 < 12 ? 100 : 150))
const row = marketRow({ item_id: 1, kind: "commodity", usual_price: 140, qty_sold_24h: 100 })
const tiers: Tier[] = [
  [100, 10],
  [120, 5],
  [149, 20],
  [150, 50],
  [200, 5],
]

describe("lookback", () => {
  it("startet nur in vergleichbaren Stunden, die die ganze Frist vor sich haben", () => {
    const look = lookback(swinging, 100, 1)
    // Vier der fuenf guenstigen Phasen: aus der letzten reicht die Frist ueber das Ende hinaus.
    expect(look.peaks).toHaveLength(48)
    expect(new Set(look.peaks)).toEqual(new Set([1.5]))
    expect(new Set(look.ends)).toEqual(new Set([1]))
    expect(look.longEnough).toBe(true)
    expect(look.days).toBeCloseTo(119 / 24)
  })

  it("misst vom Preis der jeweiligen Stunde aus, nicht vom heutigen", () => {
    // Heute 105: die Stunden bei 100 liegen im Band, die bei 150 nicht.
    const look = lookback(swinging, 105, 1)
    expect(look.peaks).toHaveLength(48)
    expect(look.peaks[0]).toBe(1.5)
  })

  it("zaehlt ein Hoch nur, wenn dort auch verkauft wurde", () => {
    // Derselbe Verlauf, aber verkauft wird nur, solange der Preis bei 100 steht.
    const quiet = swinging.map((point) => ({ ...point, qty_sold: point.min_price === 100 ? 5 : 0 }))
    // Der letzte Stand bei 150 zaehlt noch: was danach verkauft wurde, ging zu 150 oder teurer weg.
    expect(new Set(lookback(quiet, 100, 1).peaks)).toEqual(new Set([1.5]))
    const dead = swinging.map((point) => ({ ...point, qty_sold: 0 }))
    expect(new Set(lookback(dead, 100, 1).peaks)).toEqual(new Set([0]))
  })

  it("kennt keinen Start, wenn der Verlauf kuerzer ist als die Frist", () => {
    const look = lookback(hourly(12, () => 100), 100, 1)
    expect(look.peaks).toHaveLength(0)
    expect(look.longEnough).toBe(false)
  })
})

describe("relist", () => {
  it("empfiehlt den hoechsten Preis, den der Markt verlaesslich erreicht hat", () => {
    const result = relist(row, tiers, swinging, 1)!
    expect(result.untested).toBeNull()
    expect(result.starts).toBe(48)
    expect(result.first).toMatchObject({ kind: "first", price: 99, ahead: 0, reached: 1 })
    // 1c unter der Stufe bei 149: 15 Stueck davor, die ein Sechstel Tag brauchen.
    expect(result.best).toMatchObject({ kind: "step", price: 148, ahead: 15, clearDays: 0.15, reached: 1 })
    expect(result.best.expected).toBeCloseTo(148 * 0.95)
    // Unter 150 ist kein Platz (149 steht schon da), und 199 hat der Markt nie erreicht.
    expect(result.usual).toMatchObject({ kind: "usual", price: 140, ahead: 15, reached: 1 })
  })

  it("rechnet ein verfehltes Ziel mit dem Preis am Ende der Frist ab", () => {
    // 36 Stunden 100, dann 12 Stunden 150, Frist zwoelf Stunden. Von den 84 Starts bei 100
    // sehen 22 die 150 mit einem Verkauf danach. Zwei sehen sie erst im letzten Stand der
    // Frist: zu spaet fuer einen Verkauf, aber am Ende steht der Markt bei 150. Die
    // uebrigen 60 enden, wo sie anfingen.
    const mixed = hourly(120, (hour) => (hour % 48 < 36 ? 100 : 150))
    const result = relist(row, [[100, 10], [150, 50]], mixed, 0.5)!
    const usual = result.usual!
    expect(result.starts).toBe(84)
    expect(usual.reached).toBeCloseTo(22 / 84)
    expect(usual.expected).toBeCloseTo(((22 * 140 + 2 * 150 + 60 * 100) / 84) * 0.95)
  })

  it("geht nie mehr als 10 % ueber den ueblichen Preis", () => {
    // Ueblich sind 110: die Stufe bei 148 hat der Markt zwar erreicht, sie liegt aber zu weit darueber.
    const result = relist({ ...row, usual_price: 110 }, tiers, swinging, 1)!
    expect(result.best).toMatchObject({ kind: "step", price: 119 })
  })

  it("bleibt beim Verkaufen als Guenstigster, wenn der Markt nicht steigt", () => {
    const result = relist(row, tiers, hourly(120, () => 100), 1)!
    expect(result.untested).toBeNull()
    expect(result.best).toBe(result.first)
    expect(result.usual?.reached).toBe(0)
  })

  it("wartet nicht fuer zwei Prozent", () => {
    const flat = hourly(120, (hour) => (hour % 2 ? 100 : 102))
    const result = relist(marketRow({ item_id: 1, qty_sold_24h: 100 }), [[100, 1], [102, 1]], flat, 1)!
    expect(result.best).toBe(result.first)
  })

  it("sagt es, wenn der Preis noch nie so tief stand", () => {
    const falling = hourly(120, (hour) => 200 - (hour * 100) / 119)
    const result = relist(row, tiers, falling, 1)!
    expect(result.untested).toBe("level")
    expect(result.best).toBe(result.first)
    expect(result.usual).toMatchObject({ price: 140, reached: null, expected: null })
  })

  it("sagt es, wenn der Verlauf zu kurz ist", () => {
    expect(relist(row, tiers, hourly(12, () => 100), 1)!.untested).toBe("short")
  })

  it("braucht Angebote", () => {
    expect(relist(row, undefined, swinging, 1)).toBeNull()
    expect(relist(row, [], swinging, 1)).toBeNull()
  })
})
