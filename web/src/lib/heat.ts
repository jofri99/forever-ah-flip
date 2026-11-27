import type { SeriesPoint } from "./types"

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const

/** Eine Stunde der Woche: was das Item dann ueblicherweise kostet und wie viel weggeht. */
export interface HeatCell {
  /** 0 = Montag. */
  day: number
  hour: number
  /** Median des guenstigsten Angebots in dieser Stunde. */
  price: number | null
  /** Verkaufte Menge je Stand, gemittelt. */
  sold: number
  samples: number
}

export function median(values: readonly number[]): number | null {
  if (!values.length) return null
  const sorted = [...values].sort((x, y) => x - y)
  const middle = sorted.length >> 1
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

/**
 * Sortiert den Verlauf in die 168 Stunden einer Woche, in der Ortszeit des
 * Betrachters. Der Schluessel ist Tag * 24 + Stunde.
 */
export function heatCells(series: readonly SeriesPoint[]): Map<number, HeatCell> {
  const buckets = new Map<number, { prices: number[]; sold: number; samples: number }>()
  for (const point of series) {
    const date = new Date(point.ts * 1000)
    const key = ((date.getDay() + 6) % 7) * 24 + date.getHours()
    let bucket = buckets.get(key)
    if (!bucket) buckets.set(key, (bucket = { prices: [], sold: 0, samples: 0 }))
    if (point.min_price != null) bucket.prices.push(point.min_price)
    bucket.sold += point.qty_sold ?? 0
    bucket.samples++
  }
  const cells = new Map<number, HeatCell>()
  for (const [key, bucket] of buckets) {
    cells.set(key, {
      day: Math.floor(key / 24),
      hour: key % 24,
      price: median(bucket.prices),
      sold: bucket.sold / bucket.samples,
      samples: bucket.samples,
    })
  }
  return cells
}

/** Fuenf Stufen von "deutlich guenstiger" bis "deutlich teurer" als der Vergleichspreis. */
export type PriceLevel = -2 | -1 | 0 | 1 | 2

export function priceLevel(price: number, base: number): PriceLevel {
  const deviation = (price - base) / base
  if (deviation <= -0.1) return -2
  if (deviation <= -0.03) return -1
  if (deviation < 0.03) return 0
  if (deviation < 0.1) return 1
  return 2
}

/** Fuenf Stufen fuer die Menge, 0 heisst: nichts verkauft. */
export function soldLevel(sold: number, max: number): 0 | 1 | 2 | 3 | 4 | 5 {
  if (sold <= 0 || max <= 0) return 0
  return Math.min(5, Math.max(1, Math.ceil((sold / max) * 5))) as 1 | 2 | 3 | 4 | 5
}
