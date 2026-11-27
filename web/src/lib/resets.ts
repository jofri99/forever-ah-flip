import { median } from "./heat"
import type { SeriesPoint } from "./types"

/**
 * Resets im Verlauf eines Items: Stunden, in denen der guenstigste Preis sprang,
 * weil der Grossteil des Angebots verschwand. Ob gekauft oder zurueckgezogen
 * wurde, laesst sich nicht unterscheiden - beides hebt den Preis. Dazu, wie lange
 * der neue Preis hielt: das ist die Zeit, die ein Reset zum Verkaufen hatte.
 */

/** Der guenstigste Preis muss mindestens um diesen Faktor springen ... */
export const RESET_JUMP = 1.5
/** ... waehrend mindestens dieser Anteil der vorher angebotenen Stueck verschwindet. */
export const RESET_GONE = 0.5
/** Bei weniger Stueck hebt schon ein einzelner Verkauf den Preis: das ist kein Reset. */
export const RESET_MIN_UNITS = 5
/** Liegen zwei Staende weiter auseinander, laesst sich nicht sagen, was in einer Stunde geschah. */
const MAX_GAP = 3 * 3_600
/** Der Preis haelt, solange er nicht weiter als bis hierher unter den Preis nach dem Reset faellt. */
export const HOLD_AT = 0.8
export const HALVED_AT = 0.5

export interface Reset {
  /** Der Stand, in dem der Preis oben ankam, in Unix-Sekunden. */
  ts: number
  before: number
  after: number
  /** Wie viele Stueck verschwanden, und wie viele vorher angeboten waren. */
  gone: number
  listed: number
  /** Im selben Stand neu eingestellt - meist der, der aufgekauft hat. */
  restocked: number | null
  /** Stunden, bis der Preis mehr als 20 % unter den neuen fiel - oder bis zum Ende des Verlaufs. */
  heldHours: number
  /** Der Verlauf endet, bevor der Preis fiel: er haelt noch. */
  holding: boolean
  /** Stunden, bis der Preis nur noch die Haelfte des neuen war. Fehlt, wenn es nicht dazu kam. */
  halvedHours: number | null
  /** Stueck, die verschwanden, solange der Preis hielt. */
  soldWhileHeld: number
}

type Point = SeriesPoint & { min_price: number }

function isJump(previous: Point, point: Point): boolean {
  return (
    point.ts - previous.ts <= MAX_GAP &&
    point.min_price >= previous.min_price * RESET_JUMP &&
    previous.quantity >= RESET_MIN_UNITS &&
    (point.qty_sold ?? 0) >= previous.quantity * RESET_GONE
  )
}

/** Findet die Resets im Verlauf, die aeltesten zuerst. Ein Sprung ueber zwei Staende zaehlt einmal. */
export function findResets(series: readonly SeriesPoint[]): Reset[] {
  const points = series
    .filter((point): point is Point => point.min_price != null && point.min_price > 0)
    .sort((x, y) => x.ts - y.ts)
  const resets: Reset[] = []

  for (let i = 1; i < points.length; i++) {
    if (!isJump(points[i - 1], points[i])) continue
    const first = i
    // Springt der Preis im naechsten Stand gleich noch einmal, gehoert das zum selben Reset.
    while (i + 1 < points.length && isJump(points[i], points[i + 1])) i++
    const top = points[i]
    let gone = 0
    for (let j = first; j <= i; j++) gone += points[j].qty_sold ?? 0

    let heldHours = (points[points.length - 1].ts - top.ts) / 3_600
    let holding = true
    let halvedHours: number | null = null
    let soldWhileHeld = 0
    for (let j = i + 1; j < points.length; j++) {
      const hours = (points[j].ts - top.ts) / 3_600
      if (holding) {
        // Was bis zu diesem Stand verschwand, ging noch zum gehaltenen Preis weg.
        soldWhileHeld += points[j].qty_sold ?? 0
        if (points[j].min_price < top.min_price * HOLD_AT) {
          holding = false
          heldHours = hours
        }
      }
      if (points[j].min_price <= top.min_price * HALVED_AT) {
        halvedHours = hours
        break
      }
    }
    resets.push({
      ts: top.ts,
      before: points[first - 1].min_price,
      after: top.min_price,
      gone,
      listed: points[first - 1].quantity,
      restocked: top.qty_new,
      heldHours,
      holding,
      halvedHours,
      soldWhileHeld,
    })
  }
  return resets
}

/** Wie lange ein Reset bei diesem Item typischerweise hielt, in Stunden. */
export function typicalHold(resets: readonly Reset[]): number | null {
  return median(resets.map((reset) => reset.heldHours))
}
