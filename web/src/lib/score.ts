import { AH_KEEP, isDowntrend, MIN_PROFIT, plan, refillsFast, soldPerDay } from "./trade"
import type { Assumptions, ChurnLevels, Plan, Tier } from "./trade"
import type { MarketRow } from "./types"

/**
 * Der Kauf-Score: wie sehr es sich lohnt, ein Item jetzt zu kaufen und zum
 * ueblichen Preis wieder einzustellen. 0 bis 100, aus vier Teilen und zwei
 * Abzuegen, die jeder fuer sich lesbar sind:
 *
 *   Score = Wurzel(Marge x Gewinn) x Absatz x Frische x Abzuege
 *
 * Marge und Gewinn zaehlen gemeinsam: viel Rendite auf ein paar Kupfer ist so
 * wenig wert wie ein grosser Betrag mit hauchduenner Marge. Absatz, Frische und
 * die Abzuege sind Bedingungen - fehlt eine, hilft der Rest nicht.
 */

/** Ab dieser Rendite hat die Marge die volle Punktzahl: gekauft fuer weniger als die Haelfte des ueblichen Preises. */
export const FULL_RETURN = 1
/** Ab diesem Anteil am eigenen Gold hat der Gewinn die volle Punktzahl ... */
export const FULL_PROFIT_SHARE = 0.2
/** ... mindestens aber ab 10 Gold. */
export const FULL_PROFIT_MIN = 100_000
/** Kam der Preis in 24 Stunden nicht ueber diesen Anteil am ueblichen, steht der Markt schon laenger tief ... */
export const STALE_AT = 0.6
/** ... kam er so nah heran, ist der niedrige Preis frisch. */
export const FRESH_AT = 0.9
export const DOWNTREND_FACTOR = 0.25
export const REFILL_FACTOR = 0.8

/**
 * Warum es nichts zu bewerten gibt: keine Preisleiter, kein ueblicher Preis,
 * nichts guenstig genug, oder das Gold reicht nicht fuer ein Stueck.
 */
export type NoScore = "no-ladder" | "no-usual" | "not-cheap" | "no-gold"

export interface BuyScore {
  /** 0 bis 100. Fehlt, wo sich nichts messen laesst: ohne Preisleiter oder ueblichen Preis. */
  score: number | null
  why: NoScore | null
  /** Was dafuer gekauft wuerde. */
  plan: Plan | null
  /** Die vier Teile, je 0 bis 1. */
  margin: number
  profit: number
  demand: number
  fresh: number
  /** Ab welchem Gewinn es die volle Punktzahl gibt, in Kupfer. */
  fullProfit: number
  downtrend: boolean
  refillsFast: boolean
}

const clamp = (value: number) => Math.max(0, Math.min(1, value))

/**
 * Bewertet den Kauf von allem, was zum ueblichen Preis noch Gewinn bringt -
 * aber nicht mehr, als der eigene Anteil an den Verkaeufen im Zeitraum absetzt,
 * und nicht mehr, als das Gold hergibt.
 */
export function buyScore(
  row: MarketRow,
  tiers: readonly Tier[] | undefined,
  a: Assumptions,
  levels: ChurnLevels,
): BuyScore {
  const gold = Math.max(0, a.gold) * 10_000
  const fullProfit = Math.max(gold * FULL_PROFIT_SHARE, FULL_PROFIT_MIN)
  const flags = { downtrend: isDowntrend(row), refillsFast: refillsFast(row, levels) }
  const none = (why: NoScore, score: number | null): BuyScore => ({
    score,
    why,
    plan: null,
    margin: 0,
    profit: 0,
    demand: 0,
    fresh: 0,
    fullProfit,
    ...flags,
  })
  if (!tiers?.length) return none("no-ladder", null)
  const usual = row.usual_price
  if (usual == null) return none("no-usual", null)

  // Teurer lohnt nicht: so viel bleibt vom ueblichen Preis nach der Gebuehr.
  const limit = usual * AH_KEEP
  const sold = soldPerDay(row)
  const maxUnits = sold == null ? 1 : Math.max(1, Math.floor(sold * a.share * a.horizon))
  let k = -1
  let units = 0
  let cost = 0
  for (let i = 0; i < tiers.length; i++) {
    const [price, quantity] = tiers[i]
    if (price >= limit) break
    const take = Math.min(quantity, maxUnits - units, Math.floor((gold - cost) / price))
    if (take <= 0) break
    k = i
    units += take
    cost += take * price
  }
  if (k < 0) return none(tiers[0][0] >= limit ? "not-cheap" : "no-gold", 0)
  const p = plan(row, tiers, k, "usual", a, units)
  if (!p || p.profit <= 0) return none("not-cheap", 0)

  const margin = clamp(p.ret / FULL_RETURN)
  // Logarithmisch: zwischen 50 Silber und 100 Gold liegen gut zwei Groessenordnungen.
  const profit = p.profit <= MIN_PROFIT ? 0 : clamp(Math.log(p.profit / MIN_PROFIT) / Math.log(fullProfit / MIN_PROFIT))
  const demand = p.days == null ? 0 : clamp(a.horizon / p.days)
  // Ohne Stand aus den letzten 24 Stunden laesst sich die Frische nicht sagen: halbe Punktzahl.
  const fresh = row.high_24h == null ? 0.5 : clamp((row.high_24h / usual - STALE_AT) / (FRESH_AT - STALE_AT))
  const raw =
    Math.sqrt(margin * profit) *
    demand *
    fresh *
    (flags.downtrend ? DOWNTREND_FACTOR : 1) *
    (flags.refillsFast ? REFILL_FACTOR : 1)
  return { score: Math.round(raw * 100), why: null, plan: p, margin, profit, demand, fresh, fullProfit, ...flags }
}

export type ScoreLevel = "strong" | "decent" | "thin" | "skip"

/** Der Score in einem Wort. */
export function scoreLevel(score: number): ScoreLevel {
  if (score >= 70) return "strong"
  if (score >= 40) return "decent"
  return score >= 15 ? "thin" : "skip"
}
