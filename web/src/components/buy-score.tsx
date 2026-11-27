import type { ReactNode } from "react"

import { Hint, ScoreMeter, Tag } from "@/components/bits"
import { useApp } from "@/lib/app"
import { formatDays, formatInt, moneyText } from "@/lib/format"
import {
  DOWNTREND_FACTOR,
  FRESH_AT,
  FULL_PROFIT_MIN,
  FULL_PROFIT_SHARE,
  FULL_RETURN,
  REFILL_FACTOR,
  scoreLevel,
  STALE_AT,
} from "@/lib/score"
import type { BuyScore, ScoreLevel } from "@/lib/score"
import { AH_KEEP, MIN_PROFIT } from "@/lib/trade"

export const LEVEL_LABEL: Record<ScoreLevel, string> = {
  strong: "Strong",
  decent: "Decent",
  thin: "Thin",
  skip: "Skip",
}

const pct = (value: number) => Math.round(value * 100)

/** Ein Teil des Scores: Balken, Punktzahl und darunter, woraus sie sich ergibt. */
function Part({ label, value, children }: { label: string; value: number; children: ReactNode }) {
  return (
    <>
      <span>{label}</span>
      <span className="flex items-center gap-2">
        <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-border" aria-hidden>
          <span className="block h-full rounded-full bg-(--viz)" style={{ width: `${pct(value)}%` }} />
        </span>
        <span className="w-7 text-right tabular-nums">{pct(value)}</span>
      </span>
      <Hint className="col-span-2 -mt-0.5 mb-1.5">{children}</Hint>
    </>
  )
}

/** Warum es keinen Score gibt oder er null ist. */
function NoScore({ result, itemId }: { result: BuyScore; itemId: number }) {
  const app = useApp()
  const row = app.rows.get(itemId)
  const lowest = app.ladder.get(itemId)?.[0]?.[0]
  switch (result.why) {
    case "no-ladder":
      return (
        <Hint>
          {app.ladder.size === 0
            ? "No price ladder in this build. Run `python -m collector publish` with Blizzard credentials to fetch the current listings."
            : "Nothing is listed right now."}
        </Hint>
      )
    case "no-usual":
      return (
        <Hint>
          Not enough history yet for a usual price ({row?.usual_points ?? 0} snapshots), so there is nothing to
          measure a bargain against.
        </Hint>
      )
    case "no-gold":
      return (
        <Hint>
          The cheapest listing costs {moneyText(lowest)}, more than the {formatInt(app.a.gold)}g you have.
        </Hint>
      )
    default:
      return (
        <Hint>
          Nothing is listed below {moneyText((row?.usual_price ?? 0) * AH_KEEP)}, which is what the usual{" "}
          {moneyText(row?.usual_price)} leaves after the 5% cut. Bought now and relisted at the usual price, it
          cannot pay off.
        </Hint>
      )
  }
}

/**
 * Der Kauf-Score eines Items, aufgeschluesselt: die Zahl, ihre vier Teile, die
 * Abzuege und der Kauf, auf dem alles beruht.
 */
export function BuyScorePanel({ itemId }: { itemId: number }) {
  const app = useApp()
  const result = app.scores.get(itemId)
  const row = app.rows.get(itemId)
  if (!result || !row) return null

  const p = result.plan
  if (result.score == null || !p) {
    return (
      <div className="flex flex-col gap-2">
        {result.score != null && (
          <div className="flex items-baseline gap-2">
            <span className="text-3xl leading-none font-semibold tabular-nums">0</span>
            <span className="text-sm text-muted-foreground">of 100 · {LEVEL_LABEL.skip}</span>
          </div>
        )}
        <NoScore result={result} itemId={itemId} />
      </div>
    )
  }

  const usual = row.usual_price ?? 0
  const deductions = [
    result.downtrend && `Downtrend ×${DOWNTREND_FACTOR}`,
    result.refillsFast && `Refills fast ×${REFILL_FACTOR}`,
  ].filter((text): text is string => Boolean(text))

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <span className="text-3xl leading-none font-semibold tabular-nums">{result.score}</span>
        <span className="text-sm text-muted-foreground">of 100 · {LEVEL_LABEL[scoreLevel(result.score)]}</span>
        <span className="ml-auto">
          <ScoreMeter value={result.score} wide bare />
        </span>
      </div>
      <p className="text-sm">
        Buy {formatInt(p.units)} for {moneyText(p.cost)}, relist at the usual {moneyText(usual)}: {moneyText(p.profit)}{" "}
        profit if every unit sells.
      </p>

      <div className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1 text-sm">
        <Part label="Margin" value={result.margin}>
          {pct(p.ret)}% return: {moneyText(p.average)} a unit on average against {moneyText(usual * AH_KEEP)} left
          of the usual price after the 5% cut. {pct(FULL_RETURN)}% or more scores full.
        </Part>
        <Part label="Profit" value={result.profit}>
          {moneyText(p.profit)} in total. {moneyText(MIN_PROFIT)} scores nothing, {moneyText(result.fullProfit)} scores
          full: {pct(FULL_PROFIT_SHARE)}% of your gold, at least {moneyText(FULL_PROFIT_MIN)}.
        </Part>
        <Part label="Demand" value={result.demand}>
          {p.days == null
            ? "No sales recorded in the last 24 hours."
            : `Your ${pct(app.a.share)}% share of sales moves ${formatInt(p.units)} unit${p.units === 1 ? "" : "s"} in ${formatDays(p.days)}; you allow ${app.a.horizon} d.`}
        </Part>
        <Part label="Fresh low" value={result.fresh}>
          {row.high_24h == null
            ? "No stored snapshot from the last 24 hours, so this counts half."
            : `In the last 24 hours the lowest listing got up to ${moneyText(row.high_24h)}, ${pct(row.high_24h / usual)}% of usual. From ${pct(FRESH_AT)}% the low price is fresh; at ${pct(STALE_AT)}% or less the market has been sitting there.`}
        </Part>
        <span>Deductions</span>
        <span className="flex flex-wrap justify-end gap-1">
          {deductions.length ? deductions.map((text) => <Tag key={text}>{text}</Tag>) : <span className="text-muted-foreground">none</span>}
        </span>
      </div>

      <Hint>
        Score = √(margin × profit) × demand × fresh low × deductions. It assumes you buy every listing that still
        pays at the usual price, but no more than your share of sales moves in the time you allow, and no more than
        your gold. It changes with the assumptions in the bar above.
      </Hint>
    </div>
  )
}
