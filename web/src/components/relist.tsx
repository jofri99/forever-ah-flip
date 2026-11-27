import { useMemo } from "react"

import { HorizonField } from "@/components/assumptions"
import { Hint, Tag } from "@/components/bits"
import { Line, Lines } from "@/components/item-sections"
import { Money, Share } from "@/components/money"
import { Skeleton } from "@/components/ui/skeleton"
import { useApp } from "@/lib/app"
import { formatDays, formatInt, formatRatio, moneyText } from "@/lib/format"
import { LEVEL_BAND, MIN_EDGE, relist } from "@/lib/relist"
import type { Relist, RelistOption } from "@/lib/relist"
import type { SeriesState } from "@/lib/series"
import { isDowntrend } from "@/lib/trade"
import type { MarketRow } from "@/lib/types"

const days = (count: number) => `${count} day${count === 1 ? "" : "s"}`
const BAND = Math.round(LEVEL_BAND * 100)
const SELL_FIRST = "1c under the lowest listing your units sell first"

function where(option: RelistOption, result: Relist): string {
  if (option.kind === "first") return `1c under the lowest listing at ${moneyText(result.now)}`
  if (option.kind === "usual") return "the usual price"
  return `1c under the listing at ${moneyText(option.price + 1)}`
}

const LABEL = { first: "Sell first", step: "Under a higher listing", usual: "Usual price" } as const

/** Wie viel gerade guenstiger angeboten wird, und wie lange der Absatz dafuer braucht. */
function queue(option: RelistOption): string {
  if (option.ahead === 0) return "none"
  return formatInt(option.ahead) + (option.clearDays == null ? "" : ` · ${formatDays(option.clearDays)} of sales`)
}

/** Die Empfehlung in Worten - mit dem, worauf sie beruht, und dem, was sie nicht weiss. */
function adviceText(result: Relist, row: MarketRow): string {
  const { best, first, usual, now, horizon, starts } = result
  const span = days(Math.max(1, Math.round(result.historyDays)))
  const falling = isDowntrend(row) ? formatRatio(-(row.trend_pct_day ?? 0)) : null
  const certain = `What is certain: ${SELL_FIRST} and keep ${moneyText(first.keep)} each.`
  const bet = falling ? ` The price has also been falling about ${falling}% a day, steadily: holding out for more is a bet on that turning.` : ""

  if (result.untested === "short") {
    return `There is only ${span} of history, not enough to follow any hour for ${days(horizon)}. ${certain}${bet}`
  }
  if (result.untested === "level") {
    return (
      `In the last ${span} the lowest listing was ${starts === 0 ? "never" : `only ${starts} hour${starts === 1 ? "" : "s"}`} ` +
      `within ${BAND}% of today's ${moneyText(now)} with ${days(horizon)} of history after it, so a higher price cannot be tested. ` +
      certain +
      (usual ? ` The usual ${moneyText(usual.price)} needs the price to climb ${Math.round((usual.price / now - 1) * 100)}% from here.` : "") +
      bet
    )
  }
  const compared = `In the ${formatInt(starts)} hours of the last ${span} when the lowest listing was within ${BAND}% of today's ${moneyText(now)}`
  if (best === first) {
    return (
      `Sell first. ${compared}, no higher price was both reached at least every second time within ${days(horizon)} ` +
      `and worth ${Math.round(MIN_EDGE * 100)}% more than selling now.${bet}`
    )
  }
  return (
    `List at ${moneyText(best.price)} and wait. ${compared}, it climbed to this price within ${days(horizon)} ` +
    `${Math.round((best.reached ?? 0) * 100)}% of the time. Counting a sale at the going price whenever it did not, that kept ` +
    `${moneyText(best.expected)} a unit on average, against ${moneyText(first.keep)} for selling first now.` +
    (falling ? ` Careful: the price is on a steady downtrend of about ${falling}% a day, and looking back flatters higher prices while a price falls.` : "")
  )
}

/**
 * Wo ein Item am besten wieder eingestellt wird: die Empfehlung, die Rechnung
 * dahinter, und zum Vergleich die anderen naheliegenden Preise.
 */
export function RelistAdvice({ itemId, loaded }: { itemId: number; loaded: SeriesState }) {
  const app = useApp()
  const row = app.rows.get(itemId)
  const tiers = app.ladder.get(itemId)
  const horizon = app.a.horizon
  const result = useMemo(
    () => (row ? relist(row, tiers, loaded.series, horizon) : null),
    [row, tiers, loaded.series, horizon],
  )

  if (!row || !result) {
    return (
      <Hint>
        {app.ladder.size === 0
          ? "No price ladder in this build. Run `python -m collector publish` with Blizzard credentials to fetch the current listings."
          : "Nothing is listed right now, so the price is yours to set."}
      </Hint>
    )
  }
  if (loaded.status === "loading") return <Skeleton className="h-40 w-full" />
  if (loaded.status === "error") return <Hint>Needs the price history, which could not be loaded.</Hint>

  const { best, first, usual } = result
  const options = [
    first,
    ...(best !== first && best !== usual ? [best] : []),
    // Liegt die Empfehlung genau auf dem ueblichen Preis, steht er nicht zweimal da.
    ...(usual && !(best !== usual && best.price === usual.price) ? [usual] : []),
  ].sort((x, y) => x.price - y.price)

  return (
    <div className="flex flex-col gap-3">
      <HorizonField />
      <Lines>
        <Line label="List every unit at" strong>
          <Money value={best.price} precise />
        </Line>
        <Hint className="col-span-2">
          That is {where(best, result)}
          {row.usual_price ? ` · ${Math.round((best.price / row.usual_price) * 100)}% of the usual ${moneyText(row.usual_price)}` : ""}.
        </Hint>
        <Line label="You keep per unit, after the 5% cut">
          <Money value={best.keep} />
        </Line>
        <Line label="Cheaper units listed right now">{queue(best)}</Line>
        {best !== first && (
          <>
            <Line label={`Reached within ${days(result.horizon)}, looking back`}>
              <Share value={best.reached} />
            </Line>
            <Line label="Kept per unit on average, looking back">
              <Money value={best.expected} />
            </Line>
            <Line label="Selling first now keeps">
              <Money value={first.keep} />
            </Line>
          </>
        )}
      </Lines>

      <table className="w-full text-sm tabular-nums">
        <thead>
          <tr className="text-[11px] tracking-wide text-muted-foreground uppercase">
            <th className="py-1 pr-2 text-left font-medium">Where</th>
            <th className="py-1 pr-2 text-right font-medium">List at</th>
            <th className="py-1 pr-2 text-right font-medium">Cheaper now</th>
            <th className="py-1 pr-2 text-right font-medium">Reached</th>
            <th className="py-1 text-right font-medium">Avg kept</th>
          </tr>
        </thead>
        <tbody>
          {options.map((option) => (
            <tr key={`${option.kind}:${option.price}`} className="border-t" title={`That is ${where(option, result)}`}>
              <td className="py-1 pr-2">
                <span className="flex flex-wrap items-center gap-1.5">
                  {LABEL[option.kind]}
                  {option === best && <Tag solid>{result.untested ? "Certain" : "Best"}</Tag>}
                </span>
              </td>
              <td className="py-1 pr-2 text-right">
                <Money value={option.price} precise />
              </td>
              <td className="py-1 pr-2 text-right text-muted-foreground">{queue(option)}</td>
              <td className="py-1 pr-2 text-right">
                {option.kind === "first" ? <span className="text-muted-foreground">at once</span> : <Share value={option.reached} />}
              </td>
              <td className="py-1 text-right">
                <Money value={option.expected} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="rounded-lg bg-muted px-3 py-2 text-sm">{adviceText(result, row)}</p>
      <Hint>
        A look back, not a forecast. Every stored hour when the lowest listing stood within {BAND}% of today's is a
        starting point. A price counts as reached when the lowest listing rose to it within the time you allow
        and units sold while it stood there: everything cheaper was gone by then. A price is only recommended
        if that happened at least every second time, it kept {Math.round(MIN_EDGE * 100)}% more than selling
        now, and it sits no more than 10% above the usual price. The hours overlap, so read the percentages
        as a guide.
      </Hint>
    </div>
  )
}
