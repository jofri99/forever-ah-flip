import { useState } from "react"
import type { ReactNode } from "react"

import { Hint, Segmented, Swatch } from "@/components/bits"
import { GoldField } from "@/components/gold-field"
import { Line, Lines } from "@/components/item-sections"
import { Count, Money, Profit, Share } from "@/components/money"
import { useApp } from "@/lib/app"
import type { AppValue } from "@/lib/app"
import { formatDays, formatInt, formatRatio, moneyText } from "@/lib/format"
import { bestReset, churn, lowBuy, plan, verdict } from "@/lib/trade"
import type { Plan } from "@/lib/trade"
import type { MarketRow } from "@/lib/types"

type Mode = "reset" | "low"

function verdictText(p: Plan, row: MarketRow, app: AppValue): string {
  const ratio = churn(row)
  switch (verdict(p, row, app.a, app.levels)) {
    case "loss":
      return "This loses money even if every unit sells."
    case "too-expensive":
      return `This costs ${moneyText(p.cost)}, more than the ${formatInt(app.a.gold)}g you have.`
    case "falling":
      return (
        `Careful. The lowest listing fell ${Math.round(-(row.change_24h_pct ?? 0))}% in 24 hours` +
        (row.market_value && row.usual_price
          ? ` and the market value is now ${Math.round((row.market_value / row.usual_price) * 100)}% of the usual ${moneyText(row.usual_price)}.`
          : ".") +
        ` That usual price may no longer hold: this is a bet on the old price coming back, with ${formatInt(row.qty_new_24h ?? 0)} new units arriving per day.`
      )
    case "refills-fast":
      return (
        `Risky. For every unit that sells, ${formatRatio(ratio ?? 0)} new ones get listed. That puts this item in the ` +
        `fastest-refilling quarter of the market (typical is ${formatRatio(app.levels.typical)}). Expect to be undercut ` +
        `before ${formatInt(p.units)} units have sold.`
      )
    case "no-sales":
      return "No sales recorded in the last 24 hours, so there is no telling how long this takes to sell."
    case "slow":
      return `Slow. At current sales this takes ${formatDays(p.days ?? 0)} to sell, longer than the ${app.a.horizon} you allow.`
    case "workable":
      return (
        `Workable on these numbers: it sells in about ${formatDays(p.days ?? 0)}` +
        (ratio != null
          ? `, and ${formatRatio(ratio)} new units get listed per unit sold, which is ${ratio <= app.levels.typical ? "at or below" : "a little above"} the typical ${formatRatio(app.levels.typical)}`
          : "") +
        ". Check in game that the cheap listings are still there before you buy."
      )
  }
}

/**
 * Die Preisleiter eines Items und was ein Aufkauf kostet. Der Schieber waehlt, bis
 * zu welcher Stufe gekauft wird; darunter steht die ganze Rechnung.
 */
export function PriceLadder({ itemId, prefer }: { itemId: number; prefer?: Mode }) {
  const app = useApp()
  const row = app.rows.get(itemId)
  const tiers = app.ladder.get(itemId)

  const defaultK = (mode: Mode) =>
    (row && tiers ? (mode === "low" ? lowBuy(row, tiers, app.a) : bestReset(row, tiers, app.a)) : null)?.k ?? 0
  const [mode, setMode] = useState<Mode>(() => {
    if (!row || !tiers) return "reset"
    const low = lowBuy(row, tiers, app.a)
    if (prefer === "low" && low) return "low"
    return bestReset(row, tiers, app.a) ? "reset" : low ? "low" : "reset"
  })
  const [chosen, setChosen] = useState<number | null>(null)

  if (!row || !tiers?.length) {
    return (
      <Hint>
        {app.ladder.size === 0
          ? "No price ladder in this build. Run `python -m collector publish` with Blizzard credentials to fetch the current listings."
          : "Nothing is listed right now."}
      </Hint>
    )
  }

  const reset = mode === "reset"
  const maxK = Math.max(0, tiers.length - (reset ? 2 : 1))
  const k = Math.min(Math.max(0, chosen ?? defaultK(mode)), maxK)
  const p = plan(row, tiers, k, reset ? "reset" : "usual", app.a)
  const usual = row.usual_price
  const shown = Math.min(tiers.length, Math.max(12, k + 3))
  const visible = tiers.slice(0, shown)
  const maxQuantity = Math.max(...visible.map((tier) => tier[1]))
  // Die laufenden Kosten bis einschliesslich jeder Stufe.
  const running: number[] = []
  let sum = 0
  for (const [price, quantity] of visible) {
    sum += price * quantity
    running.push(sum)
  }

  const rule: ReactNode = !p
    ? null
    : p.rule === "next"
      ? `1c under the next listing at ${moneyText(p.next)}`
      : p.rule === "cap"
        ? `capped at 110% of the usual price; the next listing is ${p.next ? moneyText(p.next) : "none"}`
        : "the usual price"

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Segmented
          label="What to calculate"
          value={mode}
          onChange={(next) => {
            setMode(next)
            setChosen(null)
          }}
          options={[
            ["reset", "Market reset"],
            ["low", "Buy low"],
          ]}
        />
        <GoldField />
      </div>
      <label className="flex items-center gap-3 text-sm">
        <span className="whitespace-nowrap text-muted-foreground">Buy up to step</span>
        <input
          type="range"
          min={1}
          max={maxK + 1}
          value={k + 1}
          onChange={(event) => setChosen(Number(event.target.value) - 1)}
          className="min-w-24 flex-1 accent-(--viz)"
        />
        <span className="whitespace-nowrap tabular-nums">
          {k + 1} of {tiers.length} · {moneyText(tiers[k][0])}
        </span>
      </label>

      <table className="w-full text-sm tabular-nums">
        <thead>
          <tr className="text-[11px] tracking-wide text-muted-foreground uppercase">
            <th className="py-1 pr-2 text-right font-medium">Price</th>
            <th className="py-1 pr-2 text-right font-medium">Of usual</th>
            <th className="w-2/5 py-1 pr-2 text-left font-medium">Units listed</th>
            <th className="py-1 pr-2 text-right font-medium">Units</th>
            <th className="py-1 text-right font-medium">Running cost</th>
          </tr>
        </thead>
        <tbody>
          {visible.map(([price, quantity], index) => {
            const buy = index <= k
            const floor = reset && index === k + 1
            return (
              <tr
                key={price}
                className={`border-t ${floor ? "font-semibold" : ""}`}
                title={`${formatInt(quantity)} unit${quantity === 1 ? "" : "s"} at ${moneyText(price)}${buy ? " – you buy these" : floor ? " – stays, the new lowest listing" : ""}`}
              >
                <td className="py-1 pr-2 text-right"><Money value={price} precise /></td>
                <td className="py-1 pr-2 text-right text-muted-foreground">
                  {usual ? `${Math.round((price / usual) * 100)}%` : ""}
                </td>
                <td className="py-1 pr-2">
                  <span
                    className="block h-2.5 min-w-0.5 rounded-r-sm"
                    style={{
                      width: `${Math.max(2, (quantity / maxQuantity) * 100)}%`,
                      background: buy ? "var(--viz)" : "var(--border)",
                    }}
                  />
                </td>
                <td className="py-1 pr-2 text-right"><Count value={quantity} /></td>
                <td className="py-1 text-right">
                  {buy ? <Money value={running[index]} /> : floor ? <span className="font-normal text-muted-foreground">new floor</span> : null}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {tiers.length > shown && <Hint>and {formatInt(tiers.length - shown)} more price steps above</Hint>}
      <div className="flex flex-wrap gap-x-4 text-[11px] text-muted-foreground">
        <span><Swatch color="var(--viz)" />you buy</span>
        <span><Swatch color="var(--border)" />stays listed</span>
      </div>

      {!p ? (
        <Hint>
          No usual price yet for this item ({row.usual_points} snapshots), so there is nothing to aim for.
        </Hint>
      ) : (
        <>
          <Lines>
            <Line label="Units you buy"><Count value={p.units} /></Line>
            <Line label="Total cost" strong><Money value={p.cost} /></Line>
            <Line label="Average price per unit"><Money value={p.average} /></Line>
            <Line label="Share of your gold"><Share value={p.goldShare} /></Line>
            <div className="col-span-2 my-1 h-px bg-border" />
            <Line label="Relist every unit at" strong><Money value={p.target} precise /></Line>
            <Hint className="col-span-2">
              {reset ? "Rule" : "Target"}: {rule}
              {usual ? ` · that is ${Math.round((p.target / usual) * 100)}% of the usual ${moneyText(usual)}` : ""}.
            </Hint>
            <Line label="Sells for, if every unit sells"><Money value={p.gross} /></Line>
            <Line label="Auction house cut, 5%">−{moneyText(p.cut)}</Line>
            <Line label="What you paid">−{moneyText(p.cost)}</Line>
            <Line label="Profit" strong><Profit value={p.profit} /></Line>
            <Line label="Return on the gold spent"><Share value={p.ret} /></Line>
            <div className="col-span-2 my-1 h-px bg-border" />
            <Line label="Break-even">
              sell {formatInt(p.breakeven)} of {formatInt(p.units)} ({Math.round((p.breakeven / p.units) * 100)}%)
            </Line>
            <Line label={reset ? "Time to sell, at all current sales" : `Time to sell, at your ${app.a.share * 100}% share`}>
              {p.days == null ? "–" : formatDays(p.days)}
            </Line>
            <Line label="Market lists this many again in">{p.refill == null ? "–" : formatDays(p.refill)}</Line>
            <Line label={`New listings per unit sold (typical ${formatRatio(app.levels.typical)})`}>
              {churn(row) == null ? "–" : formatRatio(churn(row) as number)}
            </Line>
            <Line label="If the price falls back to the old low"><Profit value={p.worst} /></Line>
            {p.deposit != null && (
              <>
                <Line label="Deposit per relisting, estimated"><Money value={p.deposit} /></Line>
                <Hint className="col-span-2">
                  Refunded when a unit sells, lost when a listing expires. Classic formula for 24 hours; not
                  confirmed for Forever.
                </Hint>
              </>
            )}
          </Lines>
          <p className="rounded-lg bg-muted px-3 py-2 text-sm">{verdictText(p, row, app)}</p>
        </>
      )}
    </div>
  )
}
