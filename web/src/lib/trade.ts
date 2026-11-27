import type { Craft, MarketRow, VendorFlip } from "./types"

/**
 * Die Rechnung hinter den Gelegenheiten: was ein Rezept, ein Haendler-Flip, ein
 * guenstiger Einkauf oder ein Market Reset bringt. Alles reine Funktionen - die
 * Oberflaeche zeigt nur an, was hier herauskommt.
 */

/** Was nach der Gebuehr des Auktionshauses vom Verkaufspreis bleibt. */
export const AH_KEEP = 0.95
/** Deutlich ueber dem ueblichen Preis verkauft sich kaum etwas. */
export const TARGET_CAP = 1.1
/** Ein Reset unter 20 % Rendite ist das Risiko nicht wert. */
export const MIN_RETURN = 0.2
/** 50 Silber: darunter lohnt der Aufwand nicht. */
export const MIN_PROFIT = 5_000
/** Einstellgebuehr fuer 24 Stunden als Anteil am Haendlerpreis - die Formel aus Classic. */
export const DEPOSIT_RATE = 0.3
/** Ab diesem Rueckgang in 24 Stunden gilt ein Preis als fallend. */
export const FALLING_PCT = -30
/** Ab diesem Anstieg in 24 Stunden gilt ein Preis als gerade hochgeschossen. */
export const SPIKE_PCT = 50

/** Eine Stufe der Preisleiter: Preis je Stueck und angebotene Menge. */
export type Tier = readonly [price: number, quantity: number]

export type Basis = "now" | "low"

/** Die Annahmen, die der Nutzer einstellt. Sie gelten ueberall. */
export interface Assumptions {
  /** Zu welchem Preis verkauft wird: guenstigstes Angebot jetzt oder Tief der letzten 24 Stunden. */
  basis: Basis
  /** Welchen Anteil der Tagesverkaeufe man sich zutraut. */
  share: number
  /** Verfuegbares Gold. */
  gold: number
  /** Wie viel davon hoechstens in einen einzelnen Reset fliesst. */
  perReset: number
  /** In wie vielen Tagen das Gekaufte wieder verkauft sein soll. */
  horizon: number
  /** Kaufgrenze fuer den guenstigen Einkauf, als Anteil am ueblichen Preis. */
  buyAt: number
}

export const DEFAULT_ASSUMPTIONS: Assumptions = {
  basis: "now",
  share: 0.1,
  gold: 500,
  perReset: 0.4,
  horizon: 3,
  buyAt: 0.8,
}

const goldCopper = (a: Assumptions) => Math.max(0, a.gold) * 10_000
const soldPerDay = (row: MarketRow) => (row.qty_sold_24h != null && row.qty_sold_24h > 0 ? row.qty_sold_24h : null)

/**
 * Zu welchem Preis verkauft wird. Das Tief der letzten 24 Stunden ist die
 * vorsichtige Wahl: ein frischer Preissprung taeuscht dann nicht.
 */
export function sellAt(row: MarketRow | undefined, basis: Basis): number | null {
  if (!row || row.min_price == null) return null
  return basis === "low" && row.low_24h != null ? Math.min(row.low_24h, row.min_price) : row.min_price
}

export function isSpiked(row: MarketRow | undefined, basis: Basis): boolean {
  return basis === "now" && row?.change_24h_pct != null && row.change_24h_pct >= SPIKE_PCT
}

/** Faellt der Preis gerade stark, ist der uebliche Preis vielleicht schon Geschichte. */
export function isFalling(row: MarketRow | undefined): boolean {
  return row?.change_24h_pct != null && row.change_24h_pct <= FALLING_PCT
}

export function craftProfit(craft: Craft, row: MarketRow | undefined, basis: Basis): number | null {
  const price = sellAt(row, basis)
  return craft.cost == null || price == null ? null : Math.round(price * craft.item_count * AH_KEEP - craft.cost)
}

/**
 * Was ein Rezept am Tag bringen kann: Gewinn je Stueck mal dem Anteil der
 * Tagesverkaeufe, den man sich zutraut - gedeckelt durch die Abklingzeit.
 */
export function craftPerDay(craft: Craft, row: MarketRow | undefined, a: Assumptions): number | null {
  const profit = craftProfit(craft, row, a.basis)
  const sold = row ? soldPerDay(row) : null
  if (profit == null || sold == null) return null
  let units = sold * a.share
  if (craft.cooldown_seconds) units = Math.min(units, (86_400 / craft.cooldown_seconds) * craft.item_count)
  return (profit / craft.item_count) * units
}

export function flipProfit(flip: VendorFlip, row: MarketRow | undefined, basis: Basis): number | null {
  const price = sellAt(row, basis)
  return price == null ? null : Math.round(price * AH_KEEP - flip.vendor_price)
}

export function flipPerDay(flip: VendorFlip, row: MarketRow | undefined, a: Assumptions): number | null {
  const profit = flipProfit(flip, row, a.basis)
  const sold = row ? soldPerDay(row) : null
  if (profit == null || sold == null) return null
  let units = sold * a.share
  if (flip.limited && flip.limited_stock) units = Math.min(units, flip.limited_stock)
  return profit * units
}

/** Was unter dem Haendlerpreis im Auktionshaus liegt: Stueckzahl und Gewinn beim Weiterverkauf. */
export interface BelowVendor {
  itemId: number
  each: number
  units: number
  total: number
}

export function belowVendor(row: MarketRow, tiers: readonly Tier[] | undefined): BelowVendor | null {
  const pays = row.vendor_sell
  // Unter einem Silber je Stueck lohnt der Weg zum Haendler nicht.
  if (pays == null || row.min_price == null || pays - row.min_price < 100) return null
  let units = 0
  let total = 0
  for (const [price, quantity] of tiers ?? [[row.min_price, 1]]) {
    if (price >= pays) break
    units += quantity
    total += (pays - price) * quantity
  }
  return { itemId: row.item_id, each: pays - row.min_price, units, total }
}

export type PlanMode = "reset" | "usual"

export interface PlanRow {
  price: number
  quantity: number
  /** Wie viel davon gekauft wird. */
  take: number
  /** Laufende Summen bis einschliesslich dieser Stufe. */
  units: number
  cost: number
}

/** Kaufen und wieder einstellen, komplett durchgerechnet. */
export interface Plan {
  itemId: number
  /** Die letzte gekaufte Preisstufe, von 0 gezaehlt. */
  k: number
  mode: PlanMode
  rows: PlanRow[]
  units: number
  cost: number
  average: number
  /** Das naechste Angebot, das stehen bleibt. */
  next: number | null
  target: number
  /** Woher der Zielpreis kommt. */
  rule: "usual" | "next" | "cap"
  gross: number
  cut: number
  profit: number
  /** Gewinn im Verhaeltnis zum eingesetzten Gold. */
  ret: number
  /** So viele Stueck muessen zum Zielpreis weg, bis das Gold wieder da ist. */
  breakeven: number
  /** Tage bis zum Abverkauf bei den heutigen Verkaeufen. */
  days: number | null
  /** Tage, bis der Markt so viele Stueck neu einstellt, wie gekauft wurden. */
  refill: number | null
  /** Ergebnis, wenn alles wieder zum alten Tiefstpreis weg muss. */
  worst: number
  /** Geschaetzte Einstellgebuehr fuer einmal neu einstellen. */
  deposit: number | null
  /** Anteil am verfuegbaren Gold. */
  goldShare: number | null
}

/**
 * Kauft die Preisstufen 0 bis k (hoechstens `maxUnits` Stueck) und stellt alles
 * zu einem Zielpreis wieder ein. "usual" zielt auf den ueblichen Preis. "reset"
 * zielt knapp unter das naechste Angebot, das stehen bleibt - aber nie weiter
 * als TARGET_CAP ueber den ueblichen Preis.
 */
export function plan(
  row: MarketRow,
  tiers: readonly Tier[],
  k: number,
  mode: PlanMode,
  a: Assumptions,
  maxUnits = Infinity,
): Plan | null {
  if (k < 0 || k >= tiers.length) return null
  let units = 0
  let cost = 0
  const rows: PlanRow[] = []
  for (let i = 0; i <= k && units < maxUnits; i++) {
    const [price, quantity] = tiers[i]
    const take = Math.min(quantity, maxUnits - units)
    units += take
    cost += take * price
    rows.push({ price, quantity, take, units, cost })
  }
  const usual = row.usual_price
  const next = tiers[k + 1]?.[0] ?? null
  let target: number | null = null
  let rule: Plan["rule"] = "usual"
  if (mode === "usual") target = usual
  else if (next != null && (usual == null || next - 1 <= usual * TARGET_CAP)) {
    target = next - 1
    rule = "next"
  } else if (usual != null) {
    target = Math.round(usual * TARGET_CAP)
    rule = "cap"
  }
  if (target == null || units <= 0 || cost <= 0) return null

  const gross = units * target
  const cut = gross * (1 - AH_KEEP)
  const profit = gross - cut - cost
  // Nach einem Reset ist man der Guenstigste und bekommt die Verkaeufe; beim
  // guenstigen Einkauf teilt man sie mit allen anderen.
  const sold = soldPerDay(row)
  const perDay = sold == null ? null : sold * (mode === "usual" ? a.share : 1)
  const gold = goldCopper(a)
  return {
    itemId: row.item_id,
    k,
    mode,
    rows,
    units,
    cost,
    average: cost / units,
    next,
    target,
    rule,
    gross,
    cut,
    profit,
    ret: profit / cost,
    breakeven: Math.min(units, Math.ceil(cost / (target * AH_KEEP))),
    days: perDay ? units / perDay : null,
    refill: row.qty_new_24h != null && row.qty_new_24h > 0 ? units / row.qty_new_24h : null,
    worst: units * tiers[0][0] * AH_KEEP - cost,
    deposit:
      row.vendor_sell != null && row.vendor_sell > 0
        ? Math.max(1, Math.round(row.vendor_sell * DEPOSIT_RATE)) * units
        : null,
    goldShare: gold > 0 ? cost / gold : null,
  }
}

/**
 * Der beste Reset, den das Gold hergibt: die Stufe mit dem meisten Gewinn, die
 * bezahlbar ist, sich im Zeitraum absetzen laesst und genug Rendite bringt.
 */
export function bestReset(row: MarketRow, tiers: readonly Tier[] | undefined, a: Assumptions): Plan | null {
  const usual = row.usual_price
  const sold = soldPerDay(row)
  if (!tiers || tiers.length < 2 || usual == null || sold == null) return null
  const maxCost = goldCopper(a) * a.perReset
  const maxUnits = sold * a.horizon
  let best = -1
  let bestProfit = 0
  let units = 0
  let cost = 0
  for (let k = 0; k < tiers.length - 1; k++) {
    units += tiers[k][1]
    cost += tiers[k][0] * tiers[k][1]
    if (cost > maxCost || units > maxUnits) break
    const target = Math.min(tiers[k + 1][0] - 1, Math.round(usual * TARGET_CAP))
    const profit = units * target * AH_KEEP - cost
    if (profit >= MIN_PROFIT && profit >= cost * MIN_RETURN && profit > bestProfit) {
      best = k
      bestProfit = profit
    }
  }
  return best < 0 ? null : plan(row, tiers, best, "reset", a)
}

/**
 * Guenstig einkaufen: alles bis zur Kaufgrenze, aber nicht mehr, als sich mit
 * dem eigenen Anteil an den Verkaeufen im Zeitraum wieder absetzen laesst.
 */
export function lowBuy(row: MarketRow, tiers: readonly Tier[] | undefined, a: Assumptions): Plan | null {
  const usual = row.usual_price
  const sold = soldPerDay(row)
  if (!tiers || usual == null || sold == null) return null
  const limit = usual * a.buyAt
  let k = -1
  while (k + 1 < tiers.length && tiers[k + 1][0] <= limit) k++
  if (k < 0) return null
  const result = plan(row, tiers, k, "usual", a, Math.max(1, Math.floor(sold * a.share * a.horizon)))
  return result && result.profit >= MIN_PROFIT ? result : null
}

/**
 * Wie viele Stueck neu eingestellt werden, waehrend eines verkauft wird. Weil
 * auch jedes erneute Einstellen zaehlt, liegt der Wert fast immer ueber 1.
 */
export function churn(row: MarketRow | undefined): number | null {
  if (!row || row.qty_new_24h == null) return null
  const sold = soldPerDay(row)
  return sold == null ? null : row.qty_new_24h / sold
}

export interface ChurnLevels {
  /** Die Mitte des Markts. */
  typical: number
  /** Ab hier gehoert ein Item zum Viertel mit dem schnellsten Nachschub. */
  fast: number
}

/** Auffaellig ist erst das oberste Viertel - gemessen am Markt, nicht an einer festen Zahl. */
export function churnLevels(rows: Iterable<MarketRow>): ChurnLevels {
  const values: number[] = []
  for (const row of rows) {
    const value = churn(row)
    if (value != null && (row.qty_sold_24h ?? 0) > 5) values.push(value)
  }
  values.sort((x, y) => x - y)
  if (!values.length) return { typical: 3, fast: 4 }
  return { typical: values[Math.floor(values.length * 0.5)], fast: values[Math.floor(values.length * 0.75)] }
}

export function refillsFast(row: MarketRow | undefined, levels: ChurnLevels): boolean {
  const value = churn(row)
  return value != null && value >= levels.fast
}

export interface Portfolio {
  picked: Set<number>
  used: number
  profit: number
}

/** Welche Resets zusammen ins Gold passen: die mit der besten Rendite zuerst. */
export function pickResets(plans: readonly Plan[], a: Assumptions): Portfolio {
  let left = goldCopper(a)
  let used = 0
  let profit = 0
  const picked = new Set<number>()
  for (const candidate of [...plans].sort((x, y) => y.ret - x.ret)) {
    if (candidate.cost > left) continue
    left -= candidate.cost
    used += candidate.cost
    profit += candidate.profit
    picked.add(candidate.itemId)
  }
  return { picked, used, profit }
}

export type Verdict = "loss" | "too-expensive" | "falling" | "refills-fast" | "slow" | "no-sales" | "workable"

/** Das Urteil ueber einen Plan - das Erste, was zutrifft, in der Reihenfolge der Schwere. */
export function verdict(p: Plan, row: MarketRow, a: Assumptions, levels: ChurnLevels): Verdict {
  if (p.profit <= 0) return "loss"
  if (p.goldShare != null && p.goldShare > 1) return "too-expensive"
  if (isFalling(row)) return "falling"
  if (refillsFast(row, levels)) return "refills-fast"
  if (p.days == null) return "no-sales"
  if (p.days > a.horizon) return "slow"
  return "workable"
}
