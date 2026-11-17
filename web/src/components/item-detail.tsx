import { useEffect, useState } from "react"
import type { ReactNode } from "react"
import { ExternalLink, X } from "lucide-react"

import { Change, Count, Money } from "@/components/money"
import { PriceChart } from "@/components/price-chart"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { loadSeries } from "@/lib/data"
import { kindLabel } from "@/lib/format"
import { itemName } from "@/lib/rows"
import type { MarketRow, Meta, Names, SeriesPoint } from "@/lib/types"

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
  onClose: () => void
}

/**
 * Wird je Item neu eingehaengt (key in App.tsx). Darum beginnt der Zustand immer
 * bei "loading" und muss beim Wechsel nicht von Hand zurueckgesetzt werden.
 */
export function ItemDetail({ meta, row, names, onClose }: ItemDetailProps) {
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
      ? "noch kein Vergleich"
      : hours != null && hours < 23
        ? `aus ${Math.round(hours)} von 24 h`
        : undefined

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-3 text-lg">
          {itemName(row.item_id, names)}
          <Badge variant="outline">{kindLabel(row.kind)}</Badge>
          <a
            href={`https://www.wowhead.com/classic/de/item=${row.item_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-sm font-normal text-muted-foreground hover:text-foreground"
          >
            Wowhead <ExternalLink className="size-3" aria-hidden />
          </a>
        </CardTitle>
        <CardAction>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Schließen">
            <X />
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-3">
          <Tile label="Günstigster">
            <Money value={row.min_price} />
          </Tile>
          <Tile label="Median">
            <Money value={row.median_price} />
          </Tile>
          <Tile label="Angebote" note={<><Count value={row.quantity} /> Stück</>}>
            <Count value={row.n_listings} />
          </Tile>
          <Tile label="24 h Tief / Hoch">
            <Money value={row.low_24h} /> / <Money value={row.high_24h} />
          </Tile>
          <Tile label="Veränderung 24 h">
            <Change value={row.change_24h_pct} />
          </Tile>
          <Tile label="Verkauft 24 h" note={coverage}>
            <Count value={row.qty_sold_24h} />
          </Tile>
        </div>

        {loaded.state === "error" ? (
          <p className="text-sm text-destructive">
            Der Verlauf konnte nicht geladen werden: {loaded.message}
          </p>
        ) : (
          <div className="relative">
            <PriceChart series={series} />
            {loaded.state === "loading" && <Skeleton className="absolute inset-0" />}
          </div>
        )}

        <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
          <LegendLine className="border-t-2 border-price">günstigster Preis</LegendLine>
          <LegendLine className="border-t border-dashed border-muted-foreground">Median</LegendLine>
          <LegendLine className="h-2.5 bg-bars">
            {hasSales ? "verkaufte Menge je Stand" : "Angebote"}
          </LegendLine>
        </div>

        {loaded.state === "ready" && (series.length < 24 || !hasSales) && (
          <p className="text-xs text-muted-foreground">
            {series.length < 24 && `Erst ${series.length} Stände – der Verlauf füllt sich stündlich. `}
            {!hasSales &&
              "Verkaufszahlen erscheinen, sobald zwei aufeinanderfolgende Stände verglichen wurden."}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
