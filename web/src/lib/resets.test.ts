import { describe, expect, it } from "vitest"

import { findResets, typicalHold } from "./resets"
import { seriesPoint } from "./test-fixtures"
import type { SeriesPoint } from "./types"

const HOUR = 3_600

/** Stuendliche Staende aus [Preis, angebotene Menge, verschwunden, neu]. */
const hourly = (rows: [number, number, number, number?][]): SeriesPoint[] =>
  rows.map(([price, quantity, sold, fresh], hour) =>
    seriesPoint(hour * HOUR, price, sold, { quantity, qty_new: fresh ?? 0 }),
  )

// Wie Bloodbelly Fish am 25. November: 225 der 272 Stueck sind weg, der Preis steht beim
// Dreizehnfachen, und 466 neue Stueck stehen zum neuen Preis da.
const reset = hourly([
  [88, 419, 3],
  [89, 272, 42],
  [1200, 466, 225, 466],
  [1200, 545, 0],
  [1000, 273, 336],
  [800, 584, 5],
  [590, 741, 17],
  [580, 688, 95],
  [300, 700, 60],
])

describe("Resets im Verlauf", () => {
  it("erkennt den Sprung, wenn dabei der Grossteil des Angebots verschwindet", () => {
    const [found, ...rest] = findResets(reset)
    expect(rest).toEqual([])
    expect(found).toMatchObject({
      ts: 2 * HOUR,
      before: 89,
      after: 1200,
      gone: 225,
      listed: 272,
      restocked: 466,
    })
  })

  it("misst, wie lange der neue Preis hielt und was dabei wegging", () => {
    const [found] = findResets(reset)
    // 1000 liegt noch in den 20 %, 800 nicht mehr: drei Stunden nach dem Reset.
    expect(found).toMatchObject({ heldHours: 3, holding: false, soldWhileHeld: 0 + 336 + 5 })
    // Bei 590 ist der Preis halbiert.
    expect(found.halvedHours).toBe(4)
    expect(typicalHold([found])).toBe(3)
  })

  it("haelt einen weggekauften Ausreisser nach unten nicht fuer einen Reset", () => {
    // Ein Angebot zu 100 in einem Markt bei 1390: nach einer Stunde ist es weg, der Preis
    // "springt" zurueck - aber von 739 Stueck sind nur 17 verschwunden.
    const snipe = hourly([
      [1390, 619, 8],
      [100, 739, 13],
      [1294, 877, 17],
      [1290, 928, 121],
    ])
    expect(findResets(snipe)).toEqual([])
  })

  it("zaehlt nicht, wo ohnehin kaum etwas angeboten war", () => {
    expect(findResets(hourly([[100, 3, 0], [900, 1, 2], [900, 1, 0]]))).toEqual([])
  })

  it("fasst einen Sprung ueber zwei Staende zu einem Reset zusammen", () => {
    const twoSteps = hourly([
      [100, 200, 0],
      [300, 80, 120],
      [900, 30, 50],
      [900, 60, 0],
    ])
    const found = findResets(twoSteps)
    expect(found).toHaveLength(1)
    expect(found[0]).toMatchObject({ ts: 2 * HOUR, before: 100, after: 900, gone: 170, listed: 200 })
  })

  it("sagt, wenn der Preis am Ende des Verlaufs noch haelt", () => {
    const [found] = findResets(reset.slice(0, 5))
    expect(found).toMatchObject({ heldHours: 2, holding: true, halvedHours: null })
  })

  it("laesst Luecken im Verlauf aus", () => {
    const gap = [seriesPoint(0, 100, 0, { quantity: 200 }), seriesPoint(6 * HOUR, 900, 150, { quantity: 50 })]
    expect(findResets(gap)).toEqual([])
    expect(typicalHold([])).toBeNull()
  })
})
