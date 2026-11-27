import { ArrowLeft, ExternalLink } from "lucide-react"

import { Hint, StarButton, Stat, Tag } from "@/components/bits"
import { BuyScorePanel, LEVEL_LABEL } from "@/components/buy-score"
import { Heatmap } from "@/components/heatmap"
import { CraftSection, ItemTags, UsedInSection, VendorsSection } from "@/components/item-sections"
import { Change, Count, Dash, Money } from "@/components/money"
import { PageHeader, Panel } from "@/components/page"
import { LazyChart } from "@/components/lazy-chart"
import { PriceLadder } from "@/components/price-ladder"
import { RelistAdvice } from "@/components/relist"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useApp } from "@/lib/app"
import { formatInt, formatPercent, formatRatio, moneyText } from "@/lib/format"
import type { Page } from "@/lib/route"
import { scoreLevel } from "@/lib/score"
import { useSeries } from "@/lib/series"
import { churn, isDowntrend, TREND_FIT } from "@/lib/trade"
import type { MarketRow } from "@/lib/types"

/** Was der Trend bedeutet: ohne genug Geschichte nichts, sonst ob der Verlauf ihm wirklich folgt. */
function trendNote(row: MarketRow): string {
  if (row.trend_pct_day == null || row.trend_fit == null) return "needs 3 days of history"
  return row.trend_fit >= TREND_FIT ? "steady across the history" : "no steady direction"
}

/**
 * Alles ueber ein Item auf einer Seite: Kennzahlen, Verlauf, Heatmap, Preisleiter
 * mit Rechner, Preis zum Wiedereinstellen, Herstellung, Verwendung und Haendler.
 * Wird je Item neu eingehaengt.
 */
export function ItemPage({ itemId, origin }: { itemId: number; origin: Page }) {
  const app = useApp()
  const row = app.rows.get(itemId)
  const loaded = useSeries(row)
  const known = row != null || app.names[String(itemId)] != null

  if (!known) {
    return (
      <>
        <PageHeader title="Unknown item">Item {itemId} is not part of the current data.</PageHeader>
        <Button variant="outline" onClick={app.back}>
          <ArrowLeft aria-hidden />
          Back
        </Button>
      </>
    )
  }

  const ratio = churn(row)
  const score = app.scores.get(itemId)?.score
  const tiers = app.ladder.get(itemId)
  const hasCrafting = app.craftsByItem.has(itemId) || app.usedIn.has(itemId)
  const hasVendors = (app.vendors.get(itemId)?.length ?? 0) > 0 || (row?.vendor_sell ?? 0) > 0

  return (
    <>
      <div className="mb-3.5 flex flex-wrap items-start gap-2.5">
        <Button variant="outline" onClick={app.back}>
          <ArrowLeft aria-hidden />
          Back
        </Button>
        <div className="min-w-0 flex-1">
          <h1 className="text-xl leading-tight font-semibold tracking-tight">{app.name(itemId)}</h1>
          <div className="mt-1.5 flex flex-wrap gap-1">
            <ItemTags itemId={itemId} />
            <Tag>Item {itemId}</Tag>
          </div>
        </div>
        <StarButton active={app.watch.includes(itemId)} onToggle={() => app.toggleWatch(itemId)} />
        <Button variant="outline" asChild>
          <a href={`https://foreverdb.net/item/${itemId}`} target="_blank" rel="noopener noreferrer">
            <ExternalLink aria-hidden />
            ForeverDB
          </a>
        </Button>
      </div>

      {row && (
        <div className="mb-3.5 grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-2">
          <Stat label="Buy score" sub={score == null ? "nothing to measure" : `of 100 · ${LEVEL_LABEL[scoreLevel(score)]}`}>
            {score == null ? <Dash /> : score}
          </Stat>
          <Stat
            label="Lowest now"
            sub={row.usual_price && row.min_price != null ? `${Math.round((row.min_price / row.usual_price) * 100)}% of usual` : undefined}
          >
            <Money value={row.min_price} />
          </Stat>
          <Stat
            label="Usual price"
            sub={
              row.usual_price != null
                ? `median of the last ${app.meta.usual_days ?? 7} days`
                : `only ${row.usual_points} snapshots in ${app.meta.usual_days ?? 7} days`
            }
          >
            <Money value={row.usual_price} />
          </Stat>
          <Stat label="Market value now" sub="cheapest 30%, outliers removed">
            <Money value={row.market_value} />
          </Stat>
          <Stat label="Median listing"><Money value={row.median_price} /></Stat>
          <Stat label="Change 24h" sub={`${moneyText(row.low_24h)} – ${moneyText(row.high_24h)}`}>
            <Change value={row.change_24h_pct} />
          </Stat>
          <Stat label="Trend" sub={trendNote(row)}>
            {row.trend_pct_day == null ? (
              <Dash />
            ) : (
              <span className={isDowntrend(row) ? "text-down" : undefined}>{formatPercent(row.trend_pct_day)} a day</span>
            )}
          </Stat>
          <Stat label="Sold per day" sub="upper bound: cancels count too">
            <Count value={row.qty_sold_24h} />
          </Stat>
          <Stat label="New per day" sub={ratio != null ? `${formatRatio(ratio)}× what sells` : undefined}>
            <Count value={row.qty_new_24h} />
          </Stat>
          <Stat
            label="On the auction house"
            sub={`${formatInt(row.n_listings)} listing${row.n_listings === 1 ? "" : "s"}${tiers ? ` · ${formatInt(tiers.length)} price steps` : ""}`}
          >
            {formatInt(row.quantity)} units
          </Stat>
          <Stat label="A vendor pays">
            <Money value={row.vendor_sell != null && row.vendor_sell > 0 ? row.vendor_sell : null} />
          </Stat>
        </div>
      )}

      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(460px,100%),1fr))] items-start gap-3.5">
        <div className="flex min-w-0 flex-col gap-3.5">
          {row && (
            <Panel title="Price history" padded>
              {loaded.status === "error" ? (
                <p className="text-sm text-destructive">The price history could not be loaded: {loaded.message}</p>
              ) : (
                <LazyChart series={loaded.series} height={340} usual={row.usual_price} loading={loaded.status === "loading"} />
              )}
              <Hint className="mt-2">
                Lowest price (solid), median listing (dashed) and below them the quantity sold per snapshot. Times
                are local.
              </Hint>
            </Panel>
          )}
          {row && (
            <Panel title="When it is cheap, when it sells" padded>
              {loaded.status === "loading" ? (
                <Skeleton className="h-40 w-full" />
              ) : (
                <Heatmap series={loaded.series} usual={row.usual_price} firstSnapshot={app.meta.first_snapshot} />
              )}
            </Panel>
          )}
          {hasCrafting && (
            <Panel title="Crafting" padded>
              <div className="flex flex-col gap-4">
                <CraftSection itemId={itemId} />
                <UsedInSection itemId={itemId} />
              </div>
            </Panel>
          )}
        </div>
        <div className="flex min-w-0 flex-col gap-3.5">
          {row && (
            <Panel title="Is it worth buying?" padded>
              <BuyScorePanel itemId={itemId} />
            </Panel>
          )}
          {row && (
            <Panel title="Price ladder and what a buy-out costs" padded>
              <PriceLadder itemId={itemId} prefer={origin === "low" ? "low" : "reset"} />
            </Panel>
          )}
          {row && (
            <Panel title="Where to relist" padded>
              <RelistAdvice itemId={itemId} loaded={loaded} />
            </Panel>
          )}
          {hasVendors && (
            <Panel title="Vendors" padded>
              <VendorsSection itemId={itemId} bare />
            </Panel>
          )}
        </div>
      </div>
    </>
  )
}
