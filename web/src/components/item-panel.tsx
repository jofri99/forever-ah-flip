import { useEffect, useState } from "react"
import { ExternalLink, Maximize2, X } from "lucide-react"

import { Hint, StarButton, Stat, Tag } from "@/components/bits"
import { CraftSection, TradeSection, UsedInSection, VendorsSection } from "@/components/item-sections"
import { Change, Count, Money } from "@/components/money"
import { LazyChart } from "@/components/lazy-chart"
import { Button } from "@/components/ui/button"
import { useApp } from "@/lib/app"
import { loadSeries } from "@/lib/data"
import { formatInt, kindLabel, moneyText } from "@/lib/format"
import type { MarketRow, SeriesPoint } from "@/lib/types"

export type SeriesState =
  | { status: "loading"; series: SeriesPoint[] }
  | { status: "ready"; series: SeriesPoint[] }
  | { status: "error"; series: SeriesPoint[]; message: string }

/**
 * Der Verlauf eines Items. Wer ihn benutzt, wird je Item neu eingehaengt (key) -
 * darum beginnt der Zustand immer bei "loading".
 */
export function useSeries(row: MarketRow | undefined): SeriesState {
  const { meta } = useApp()
  const [state, setState] = useState<SeriesState>({ status: "loading", series: [] })
  const itemId = row?.item_id
  const kind = row?.kind

  useEffect(() => {
    if (itemId == null || kind == null) return
    let cancelled = false
    loadSeries(meta, itemId, kind)
      .then((series) => {
        if (!cancelled) setState({ status: "ready", series })
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({ status: "error", series: [], message: error instanceof Error ? error.message : String(error) })
        }
      })
    // Wird inzwischen ein anderes Item gewaehlt, darf die alte Antwort nichts mehr setzen.
    return () => {
      cancelled = true
    }
  }, [meta, itemId, kind])

  return state
}

export function ItemTags({ itemId }: { itemId: number }) {
  const row = useApp().rows.get(itemId)
  return (
    <>
      {row && <Tag>{kindLabel(row.kind)}</Tag>}
      {row?.item_class && (
        <Tag solid>
          {row.item_class}
          {row.item_subclass && row.item_subclass !== row.item_class ? ` · ${row.item_subclass}` : ""}
        </Tag>
      )}
      {!row && <Tag>Not on the auction house</Tag>}
    </>
  )
}

/**
 * Die Seitenleiste: das gewaehlte Item bleibt offen, waehrend man durch die Liste
 * blaettert. Wird je Item neu eingehaengt (key in App.tsx).
 */
export function ItemPanel({ itemId }: { itemId: number }) {
  const app = useApp()
  const row = app.rows.get(itemId)
  const loaded = useSeries(row)

  return (
    <aside
      aria-label="Item details"
      className="fixed inset-y-0 right-0 z-20 flex w-[min(408px,100vw)] flex-col border-l bg-card shadow-xl xl:static xl:z-auto xl:shadow-none"
    >
      <div className="flex items-start gap-1 border-b px-4 pt-3.5 pb-2.5">
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] leading-tight font-semibold">{app.name(itemId)}</h2>
          <div className="mt-1.5 flex flex-wrap gap-1"><ItemTags itemId={itemId} /></div>
        </div>
        <StarButton active={app.watch.includes(itemId)} onToggle={() => app.toggleWatch(itemId)} />
        <Button variant="ghost" size="icon" onClick={() => app.open(itemId)} title="Full page" aria-label="Full page">
          <Maximize2 />
        </Button>
        <Button variant="ghost" size="icon" asChild title="Open on ForeverDB">
          <a href={`https://foreverdb.net/item/${itemId}`} target="_blank" rel="noopener noreferrer" aria-label="Open on ForeverDB">
            <ExternalLink />
          </a>
        </Button>
        <Button variant="ghost" size="icon" onClick={() => app.select(null)} title="Close (Esc)" aria-label="Close">
          <X />
        </Button>
      </div>

      <div className="flex flex-1 flex-col gap-4 overflow-auto px-4 pt-3.5 pb-6">
        {row && (
          <>
            <div className="grid grid-cols-4 gap-2">
              <Stat label="Lowest"><Money value={row.min_price} /></Stat>
              <Stat label="Median"><Money value={row.median_price} /></Stat>
              <Stat label="24h"><Change value={row.change_24h_pct} /></Stat>
              <Stat label="Sold/day"><Count value={row.qty_sold_24h} /></Stat>
            </div>
            {loaded.status === "error" ? (
              <p className="text-sm text-destructive">The price history could not be loaded: {loaded.message}</p>
            ) : (
              <LazyChart series={loaded.series} height={220} usual={row.usual_price} loading={loaded.status === "loading"} />
            )}
            <Hint>
              {formatInt(row.n_listings)} listing{row.n_listings === 1 ? "" : "s"}, {formatInt(row.quantity)} units ·
              24h range {moneyText(row.low_24h)} – {moneyText(row.high_24h)}
            </Hint>
          </>
        )}
        <TradeSection itemId={itemId} />
        <CraftSection itemId={itemId} />
        <UsedInSection itemId={itemId} />
        <VendorsSection itemId={itemId} />
      </div>
    </aside>
  )
}
