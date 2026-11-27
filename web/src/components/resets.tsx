import { Hint } from "@/components/bits"
import { Money } from "@/components/money"
import { formatDateTime, formatHours, formatInt } from "@/lib/format"
import { HOLD_AT, RESET_GONE, RESET_JUMP, typicalHold } from "@/lib/resets"
import type { Reset } from "@/lib/resets"

const SLIP = Math.round((1 - HOLD_AT) * 100)
const days = (count: number) => `${count} day${count === 1 ? "" : "s"}`

/**
 * Die Resets, die der Verlauf eines Items zeigt: wann, von wo nach wo, wie viel
 * dabei verschwand und wie lange der neue Preis hielt.
 */
export function ResetList({ resets, historyDays }: { resets: readonly Reset[]; historyDays: number }) {
  const span = days(Math.max(1, Math.round(historyDays)))
  const rule =
    `Counted as a reset: within an hour the lowest listing rises to ${RESET_JUMP}× or more while at least ` +
    `${Math.round(RESET_GONE * 100)}% of the listed units disappear.`
  if (!resets.length) {
    return (
      <Hint>
        None in the {span} of stored history. {rule}
      </Hint>
    )
  }

  const typical = typicalHold(resets) ?? 0
  return (
    <div className="flex flex-col gap-2.5">
      <p className="text-sm">
        {resets.length} reset{resets.length === 1 ? "" : "s"} in the last {span}. The new price held for{" "}
        {resets.length === 1 ? "" : "a median of "}
        {formatHours(typical)} before it slipped more than {SLIP}%: that is how long a reset on this item has had
        to sell.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm tabular-nums">
          <thead>
            <tr className="text-[11px] tracking-wide whitespace-nowrap text-muted-foreground uppercase">
              <th className="py-1 pr-3 text-left font-medium">When</th>
              <th className="py-1 pr-3 text-right font-medium">Lowest listing</th>
              <th className="py-1 pr-3 text-right font-medium">Units gone</th>
              <th className="py-1 pr-3 text-right font-medium">Held</th>
              <th className="py-1 pr-3 text-right font-medium">Halved after</th>
              <th className="py-1 text-right font-medium">Sold meanwhile</th>
            </tr>
          </thead>
          <tbody>
            {[...resets].reverse().map((reset) => (
              <tr key={reset.ts} className="border-t whitespace-nowrap">
                <td className="py-1 pr-3">{formatDateTime(new Date(reset.ts * 1000).toISOString())}</td>
                <td className="py-1 pr-3 text-right">
                  <Money value={reset.before} /> → <Money value={reset.after} />{" "}
                  <span className="text-muted-foreground">×{formatInt(reset.after / reset.before)}</span>
                </td>
                <td
                  className="py-1 pr-3 text-right"
                  title={reset.restocked ? `${formatInt(reset.restocked)} new units were listed in the same hour` : undefined}
                >
                  {formatInt(reset.gone)} <span className="text-muted-foreground">of {formatInt(reset.listed)}</span>
                </td>
                <td
                  className="py-1 pr-3 text-right"
                  title={reset.holding ? "Still holding at the end of the stored history" : undefined}
                >
                  {formatHours(reset.heldHours)}
                  {reset.holding && "+"}
                </td>
                <td className="py-1 pr-3 text-right">
                  {reset.halvedHours == null ? <span className="text-muted-foreground">–</span> : formatHours(reset.halvedHours)}
                </td>
                <td className="py-1 text-right">{formatInt(reset.soldWhileHeld)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Hint>
        {rule} Bought out and cancelled look the same in the data. “Held” runs until the lowest listing fell more
        than {SLIP}% below the reset price; “sold meanwhile” is what left the auction house in that time. Resets
        are marked in the price history above.
      </Hint>
    </div>
  )
}
