import { useEffect, useState } from "react"
import type { ReactNode } from "react"
import { ExternalLink, X } from "lucide-react"

import { CraftBreakdown } from "@/components/craft-breakdown"
import { Change, Count, Money } from "@/components/money"
import { PriceChart } from "@/components/price-chart"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { loadSeries } from "@/lib/data"
import { kindLabel } from "@/lib/format"
import { itemName } from "@/lib/rows"
import type { Craft, CraftReagent, MarketRow, Meta, Names, SeriesPoint } from "@/lib/types"

function Tile({ label, children, note }: { label: string; children: ReactNode; note?: ReactNode }) {
  return (
    <div className="min-w-32 rounded-lg border px-3 py-2">
      <div className="text-xs tracking-wide text-muted-foreground uppercase">{label}</div>
      <div className="text-base font-semibold">{children}</div>
      {note && <div className="text-xs text-muted-foreground">{note}</div>}
    </div>
  )
}

function LegendLine({ className, children }: { className: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className={`inline-block w-4 ${className}`} aria-hidden />
      {children}
    </span>
  )
}

type Loaded =
  | { state: "loading" }
  | { state: "ready"; series: SeriesPoint[] }
  | { state: "error"; message: string }

interface ItemDetailProps {
  meta: Meta
  row: MarketRow
  names: Names
  /** Die Rezepte, die dieses Item herstellen, das lohnendste zuerst. Meist keins oder eins. */
  crafts: Craft[]
  /** Die Zutaten je Rezept. */
  reagents: Map<number, CraftReagent[]>
  /** Der Schluessel der Marktzeile eines Items, wenn es im Auktionshaus steht. */
  marketKey: (itemId: number) => string | null
  onSelect: (key: string) => void
  onClose: () => void
}

/**
 * Wird je Item neu eingehaengt (key in App.tsx). Darum beginnt der Zustand immer
 * bei "loading" und muss beim Wechsel nicht von Hand zurueckgesetzt werden.
 */
export function ItemDetail({
  meta,
  row,
  names,
  crafts,
  reagents,
  marketKey,
  onSelect,
  onClose,
}: ItemDetailProps) {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" })

  useEffect(() => {
    let cancelled = false
    loadSeries(meta, row.item_id, row.kind)
      .then((series) => {
        if (!cancelled) setLoaded({ state: "ready", series })
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setLoaded({ state: "error", message: error instanceof Error ? error.message : String(error) })
        }
      })
    // Wird inzwischen ein anderes Item gewaehlt, darf die alte Antwort nichts mehr setzen.
    return () => {
      cancelled = true
    }
  }, [meta, row.item_id, row.kind])

  const series = loaded.state === "ready" ? loaded.series : []
  const hasSales = series.some((point) => point.qty_sold != null)

  // Die Verkaufszahl stimmt nur fuer die Stunden, in denen verglichen wurde.
  const hours = row.sales_hours_24h
  const coverage =
    row.qty_sold_24h == null
      ? "no comparison yet"
      : hours != null && hours < 23
        ? `from ${Math.round(hours)} of 24 h`
        : undefined

  // Liegt das guenstigste Angebot unter dem, was ein Haendler zahlt, ist der
  // Weiterverkauf an den Haendler ein sicherer Gewinn.
  const belowVendor =
    row.vendor_sell != null && row.min_price != null && row.vendor_sell > 0 && row.min_price < row.vendor_sell

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-3 text-lg">
          {itemName(row.item_id, names)}
          <Badge variant="outline">{kindLabel(row.kind)}</Badge>
          {row.item_class && (
            <Badge variant="secondary">
              {row.item_class}
              {row.item_subclass && row.item_subclass !== row.item_class ? ` · ${row.item_subclass}` : ""}
            </Badge>
          )}
          <a
            href={`https://foreverdb.net/item/${row.item_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-sm font-normal text-muted-foreground hover:text-foreground"
          >
            ForeverDB <ExternalLink className="size-3" aria-hidden />
          </a>
        </CardTitle>
        <CardAction>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close">
            <X />
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-3">
          <Tile label="Lowest">
            <Money value={row.min_price} />
          </Tile>
          <Tile label="Median">
            <Money value={row.median_price} />
          </Tile>
          <Tile label="Listings" note={<><Count value={row.quantity} /> units</>}>
            <Count value={row.n_listings} />
          </Tile>
          <Tile label="24h low / high">
            <Money value={row.low_24h} /> / <Money value={row.high_24h} />
          </Tile>
          <Tile label="Change 24h">
            <Change value={row.change_24h_pct} />
          </Tile>
          <Tile label="Sold 24h" note={coverage}>
            <Count value={row.qty_sold_24h} />
          </Tile>
          <Tile label="Vendor pays" note={belowVendor ? "lowest listing is below this" : undefined}>
            <Money value={row.vendor_sell} />
          </Tile>
          <Tile label="Vendor list price" note="not every item is sold by a vendor">
            <Money value={row.vendor_buy} />
          </Tile>
        </div>

        {loaded.state === "error" ? (
          <p className="text-sm text-destructive">
            The price history could not be loaded: {loaded.message}
          </p>
        ) : (
          <div className="relative">
            <PriceChart series={series} />
            {loaded.state === "loading" && <Skeleton className="absolute inset-0" />}
          </div>
        )}

        <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
          <LegendLine className="border-t-2 border-price">lowest price</LegendLine>
          <LegendLine className="border-t border-dashed border-muted-foreground">median</LegendLine>
          <LegendLine className="h-2.5 bg-bars">
            {hasSales ? "quantity sold per snapshot" : "listings"}
          </LegendLine>
        </div>

        {loaded.state === "ready" && (series.length < 24 || !hasSales) && (
          <p className="text-xs text-muted-foreground">
            {series.length < 24 && `Only ${series.length} snapshots so far – the history fills in hourly. `}
            {!hasSales &&
              "Sales figures appear once two consecutive snapshots have been compared."}
          </p>
        )}

        {crafts.length > 0 && (
          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">
              Crafting <span className="font-normal text-muted-foreground">· reagents at their cheapest current price</span>
            </h3>
            {crafts.map((craft) => (
              <CraftBreakdown
                key={craft.recipe_id}
                craft={craft}
                reagents={reagents.get(craft.recipe_id) ?? []}
                names={names}
                marketKey={marketKey}
                onSelect={onSelect}
              />
            ))}
          </section>
        )}
      </CardContent>
    </Card>
  )
}
