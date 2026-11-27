import { Fragment, useMemo, useState } from "react"

import { Hint, Segmented, Swatch } from "@/components/bits"
import { formatDateTime, formatInt, moneyText } from "@/lib/format"
import { heatCells, median, priceLevel, soldLevel, WEEKDAYS } from "@/lib/heat"
import type { SeriesPoint } from "@/lib/types"

type Metric = "price" | "sold"

// Preis: zwei Pole mit grauer Mitte. Menge: eine Farbe von hell nach dunkel.
const PRICE_COLOR: Record<string, string> = {
  "-2": "var(--viz)",
  "-1": "color-mix(in oklab, var(--viz) 45%, var(--viz-mid))",
  "0": "var(--viz-mid)",
  "1": "color-mix(in oklab, var(--viz-warm) 45%, var(--viz-mid))",
  "2": "var(--viz-warm)",
}
const SOLD_COLOR = ["", "var(--viz-1)", "var(--viz-2)", "var(--viz-3)", "var(--viz-4)", "var(--viz-5)"]
const EMPTY = "shadow-[inset_0_0_0_1px_var(--border)]"

interface HeatmapProps {
  series: SeriesPoint[]
  /** Der Vergleichspreis. Ohne ihn dient der Median des Verlaufs. */
  usual: number | null
  firstSnapshot: string
}

/**
 * Wochentag mal Stunde, in der Ortszeit des Betrachters: wann das Item guenstig
 * ist und wann es sich verkauft. Jede Zelle traegt ihre Werte unter dem Zeiger.
 */
export function Heatmap({ series, usual, firstSnapshot }: HeatmapProps) {
  const [metric, setMetric] = useState<Metric>("price")
  const [tip, setTip] = useState<{ text: string; x: number; y: number } | null>(null)

  const { cells, base, maxSold } = useMemo(() => {
    const cells = heatCells(series)
    const prices = series.flatMap((point) => (point.min_price == null ? [] : [point.min_price]))
    return {
      cells,
      base: usual ?? median(prices),
      maxSold: Math.max(0, ...[...cells.values()].map((cell) => cell.sold)),
    }
  }, [series, usual])

  if (series.length < 2 || base == null) return <Hint>No history yet.</Hint>
  const price = metric === "price"

  return (
    <div>
      <div className="mb-2">
        <Segmented
          label="Heatmap shows"
          value={metric}
          onChange={setMetric}
          options={[
            ["price", "Price vs usual"],
            ["sold", "Quantity sold"],
          ]}
        />
      </div>
      <div
        role="img"
        aria-label={`${price ? "Lowest price compared with the usual price" : "Quantity sold"} by weekday and hour`}
        className="grid gap-0.5 text-[10px] text-muted-foreground"
        style={{ gridTemplateColumns: "30px repeat(24, minmax(0, 1fr))" }}
        onPointerMove={(event) => {
          const text = (event.target as HTMLElement).dataset?.tip
          setTip(text ? { text, x: event.clientX, y: event.clientY } : null)
        }}
        onPointerLeave={() => setTip(null)}
      >
        <span />
        {Array.from({ length: 24 }, (_, hour) => (
          <span key={hour} className="whitespace-nowrap">
            {hour % 3 === 0 ? String(hour).padStart(2, "0") : ""}
          </span>
        ))}
        {WEEKDAYS.map((day, d) => (
          <Fragment key={day}>
            <span className="flex items-center">{day}</span>
            {Array.from({ length: 24 }, (_, hour) => {
              const cell = cells.get(d * 24 + hour)
              const label = `${day} ${String(hour).padStart(2, "0")}:00`
              if (!cell || (price && cell.price == null)) {
                return <span key={hour} data-tip={`${label} · no data yet`} className={`h-[18px] rounded-[3px] ${EMPTY}`} />
              }
              const deviation = cell.price == null ? null : Math.round(((cell.price - base) / base) * 100)
              const color = price
                ? PRICE_COLOR[String(priceLevel(cell.price as number, base))]
                : SOLD_COLOR[soldLevel(cell.sold, maxSold)]
              const text =
                `${label} · lowest ${moneyText(cell.price)}` +
                (deviation == null ? "" : ` (${deviation > 0 ? "+" : ""}${deviation}% vs usual)`) +
                ` · ${formatInt(cell.sold)} sold per snapshot · ${cell.samples} snapshot${cell.samples === 1 ? "" : "s"}`
              return (
                <span
                  key={hour}
                  data-tip={text}
                  className={`h-[18px] rounded-[3px] ${color ? "" : EMPTY}`}
                  style={color ? { background: color } : undefined}
                />
              )
            })}
          </Fragment>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        {price ? (
          <>
            <span><Swatch color={PRICE_COLOR["-2"]} />10% cheaper or more</span>
            <span><Swatch color={PRICE_COLOR["-1"]} />3–10% cheaper</span>
            <span><Swatch color={PRICE_COLOR["0"]} />about usual</span>
            <span><Swatch color={PRICE_COLOR["1"]} />3–10% dearer</span>
            <span><Swatch color={PRICE_COLOR["2"]} />10% dearer or more</span>
            <span><Swatch />no data yet</span>
          </>
        ) : (
          <>
            <span>
              fewer <Swatch color={SOLD_COLOR[1]} /><Swatch color={SOLD_COLOR[2]} /><Swatch color={SOLD_COLOR[3]} />
              <Swatch color={SOLD_COLOR[4]} /><Swatch color={SOLD_COLOR[5]} />more sold per snapshot
            </span>
            <span><Swatch />none, or no data yet</span>
          </>
        )}
      </div>
      <Hint className="mt-2">
        {cells.size} of the 168 hours of a week have data ({series.length} snapshots since{" "}
        {formatDateTime(firstSnapshot)}, your local time). With fewer than two or three samples per hour, read
        it as a hint, not a pattern.
      </Hint>
      {tip && (
        <div
          role="tooltip"
          className="pointer-events-none fixed z-50 max-w-80 rounded-md border bg-card px-2 py-1 text-xs text-card-foreground shadow-lg"
          style={{ left: Math.min(tip.x + 12, window.innerWidth - 330), top: tip.y + 16 }}
        >
          {tip.text}
        </div>
      )}
    </div>
  )
}
