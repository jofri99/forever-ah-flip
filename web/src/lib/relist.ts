import { AH_KEEP, soldPerDay, TARGET_CAP } from "./trade"
import type { Tier } from "./trade"
import type { MarketRow, SeriesPoint } from "./types"

/**
 * Wo ein Item am besten wieder eingestellt wird. Die Preisleiter sagt, wie viel
 * gerade guenstiger angeboten wird; der Verlauf sagt, wie oft der Markt einen Preis
 * von hier aus erreicht hat. Reine Funktionen - die Oberflaeche zeigt nur an.
 */

/** Eine Stunde gilt als vergleichbar, wenn der Preis hoechstens so weit vom heutigen entfernt lag. */
export const LEVEL_BAND = 0.1
/** Unter so vielen vergleichbaren Stunden sagt der Rueckblick nichts. */
export const MIN_STARTS = 12
/** Empfohlen wird nur ein Preis, den der Markt im Rueckblick mindestens so oft erreicht hat. */
export const MIN_REACHED = 0.5
/** Warten lohnt erst, wenn es im Rueckblick so viel mehr brachte als sofort zu verkaufen. */
export const MIN_EDGE = 0.03

/** Als Guenstigster, knapp unter einer Stufe der Leiter, oder zum ueblichen Preis. */
export type RelistKind = "first" | "step" | "usual"

export interface RelistOption {
  kind: RelistKind
  /** Preis je Stueck. */
  price: number
  /** Was nach dem Anteil des Auktionshauses bleibt. */
  keep: number
  /** Stueck, die jetzt guenstiger angeboten werden. */
  ahead: number
  /** So lange brauchen die heutigen Verkaeufe fuer diese Stueck. */
  clearDays: number | null
  /** Anteil der vergleichbaren Stunden, nach denen der Markt den Preis in der Frist erreichte. */
  reached: number | null
  /** Was im Rueckblick im Schnitt je Stueck blieb. */
  expected: number | null
}

/**
 * Der Rueckblick: von jeder vergleichbaren Stunde aus, wie hoch der guenstigste
 * Preis in der Frist stieg und wo er an ihrem Ende stand - beides im Verhaeltnis
 * zum Preis dieser Stunde. Als Hoch zaehlt nur ein Stand, nach dem auch verkauft
 * wurde: bei seltenen Stuecken springt der guenstigste Preis schon, wenn bloss das
 * billigste Angebot verschwindet, ohne dass dort oben jemand kauft.
 */
export interface Lookback {
  peaks: number[]
  ends: number[]
  /** Ob der Verlauf ueberhaupt lang genug ist, um von einer Stunde die ganze Frist zu sehen. */
  longEnough: boolean
  /** Wie viele Tage der Verlauf umfasst. */
  days: number
}

export function lookback(series: readonly SeriesPoint[], now: number, horizonDays: number): Lookback {
  const points: { ts: number; price: number; sold: number }[] = []
  for (const point of series) {
    if (point.min_price != null && point.min_price > 0) {
      points.push({ ts: point.ts, price: point.min_price, sold: point.qty_sold ?? 0 })
    }
  }
  points.sort((x, y) => x.ts - y.ts)
  const peaks: number[] = []
  const ends: number[] = []
  if (!points.length) return { peaks, ends, longEnough: false, days: 0 }

  const span = horizonDays * 86_400
  const last = points[points.length - 1].ts
  for (let i = 0; i < points.length; i++) {
    const start = points[i]
    if (start.ts + span > last) break // die Frist ragt ueber das Ende des Verlaufs hinaus
    if (Math.abs(start.price / now - 1) > LEVEL_BAND) continue
    let peak = 0
    let end = start.price
    for (let j = i + 1; j < points.length && points[j].ts <= start.ts + span; j++) {
      // Was bis zum naechsten Stand verkauft wurde, ging zu diesem Preis oder teurer weg.
      const next = points[j + 1]
      if (next && next.ts <= start.ts + span && next.sold > 0) peak = Math.max(peak, points[j].price)
      end = points[j].price
    }
    peaks.push(peak / start.price)
    ends.push(end / start.price)
  }
  return { peaks, ends, longEnough: points[0].ts + span <= last, days: (last - points[0].ts) / 86_400 }
}

/** Warum es keinen Rueckblick gibt: der Verlauf ist zu kurz, oder der Preis stand nie da, wo er heute steht. */
export type Untested = "short" | "level"

export interface Relist {
  /** Das guenstigste Angebot jetzt. */
  now: number
  horizon: number
  historyDays: number
  /** Zahl der vergleichbaren Stunden. */
  starts: number
  untested: Untested | null
  first: RelistOption
  /** Der uebliche Preis - nur wenn er ueber dem heutigen liegt. */
  usual: RelistOption | null
  /** Die Empfehlung: `first`, `usual` oder eine Stufe der Leiter. */
  best: RelistOption
}

/**
 * Ein Preis im Rueckblick: wurde er in der Frist erreicht, zaehlt er selbst;
 * sonst zaehlt, was der Markt am Ende der Frist hergab.
 */
function tested(option: RelistOption, now: number, look: Lookback): RelistOption {
  const ratio = option.price / now
  let hits = 0
  let sum = 0
  for (let i = 0; i < look.peaks.length; i++) {
    if (look.peaks[i] >= ratio) {
      hits++
      sum += option.price
    } else sum += look.ends[i] * now
  }
  const n = look.peaks.length
  return { ...option, reached: hits / n, expected: (sum / n) * AH_KEEP }
}

/**
 * Empfiehlt einen Preis zum Wiedereinstellen. Zur Wahl stehen: 1c unter dem
 * guenstigsten Angebot (verkauft sich zuerst), 1c unter jeder hoeheren Stufe der
 * Leiter bis TARGET_CAP ueber dem ueblichen Preis, und der uebliche Preis selbst.
 * Gewinner ist, was im Rueckblick am meisten brachte - wenn der Markt es oft genug
 * erreicht hat und es das Warten lohnt.
 */
export function relist(
  row: MarketRow,
  tiers: readonly Tier[] | undefined,
  series: readonly SeriesPoint[],
  horizon: number,
): Relist | null {
  if (!tiers?.length) return null
  const now = tiers[0][0]
  const sold = soldPerDay(row)
  const option = (kind: RelistKind, price: number, ahead: number): RelistOption => ({
    kind,
    price,
    keep: price * AH_KEEP,
    ahead,
    clearDays: sold == null ? null : ahead / sold,
    reached: null,
    expected: null,
  })

  const undercut = option("first", Math.max(1, now - 1), 0)
  const first: RelistOption = { ...undercut, reached: 1, expected: undercut.keep }
  const cap = row.usual_price != null ? row.usual_price * TARGET_CAP : Infinity
  const steps: RelistOption[] = []
  let ahead = 0
  for (let t = 0; t < tiers.length; t++) {
    const [price, quantity] = tiers[t]
    // Liegt die Stufe nur 1c ueber der vorigen, ist darunter kein Platz.
    if (t > 0 && price - 1 > tiers[t - 1][0] && price - 1 <= cap) steps.push(option("step", price - 1, ahead))
    ahead += quantity
  }
  let usual: RelistOption | null = null
  if (row.usual_price != null && row.usual_price > now) {
    const price = Math.round(row.usual_price)
    usual = option("usual", price, tiers.reduce((sum, [p, quantity]) => (p < price ? sum + quantity : sum), 0))
  }

  const look = lookback(series, now, horizon)
  const base = { now, horizon, historyDays: look.days, starts: look.peaks.length, first }
  if (look.peaks.length < MIN_STARTS) {
    return { ...base, untested: look.longEnough ? "level" : "short", usual, best: first }
  }

  usual = usual && tested(usual, now, look)
  let best = first
  for (const candidate of [...steps.map((step) => tested(step, now, look)), ...(usual ? [usual] : [])]) {
    if ((candidate.reached ?? 0) >= MIN_REACHED && (candidate.expected ?? 0) > (best.expected ?? 0)) best = candidate
  }
  if (best !== first && (best.expected ?? 0) < first.keep * (1 + MIN_EDGE)) best = first
  return { ...base, untested: null, usual, best }
}
