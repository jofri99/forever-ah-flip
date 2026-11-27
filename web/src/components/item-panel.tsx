import { ExternalLink, Maximize2, X } from "lucide-react"

import { Hint, StarButton, Stat } from "@/components/bits"
import { CraftSection, ItemTags, TradeSection, UsedInSection, VendorsSection } from "@/components/item-sections"
import { Change, Count, Money } from "@/components/money"
import { LazyChart } from "@/components/lazy-chart"
import { Button } from "@/components/ui/button"
import { useApp } from "@/lib/app"
import { formatInt, moneyText } from "@/lib/format"
import { useSeries } from "@/lib/series"

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
