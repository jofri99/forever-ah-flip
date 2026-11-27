import { useMemo, useState } from "react"

import { Assume, FallBadge, Hint, NameCell, Segmented, Stat, Tag, Toggle, WarnBadge } from "@/components/bits"
import { DataTable } from "@/components/data-table"
import type { DataColumn } from "@/components/data-table"
import { Count, Dash, Money, Profit, Share } from "@/components/money"
import { CountNote, Empty, FilterBar, PageHeader, SearchInput } from "@/components/page"
import { GoldField } from "@/components/gold-field"
import { useApp } from "@/lib/app"
import { formatDays, formatInt } from "@/lib/format"
import { matches } from "@/lib/rows"
import { isFalling, refillsFast } from "@/lib/trade"
import type { Plan } from "@/lib/trade"

const HORIZONS = [
  [1, "1 day"],
  [3, "3 days"],
  [7, "7 days"],
] as const

const Days = ({ value }: { value: number | null }) => (value == null ? <Dash /> : <>{formatDays(value)}</>)

function NoLadder() {
  return (
    <div className="rounded-xl border bg-card">
      <Empty>
        This needs the current listings. Run <code>python -m collector publish</code> with Blizzard credentials in{" "}
        <code>.env</code> to fetch them.
      </Empty>
    </div>
  )
}

/** Angebote deutlich unter dem ueblichen Preis: kaufen, zum ueblichen Preis wieder einstellen. */
export function LowPage() {
  const app = useApp()
  const [query, setQuery] = useState("")
  const [fits, setFits] = useState(false)
  const [steady, setSteady] = useState(false)
  const gold = app.a.gold * 10_000

  const rows = useMemo(
    () =>
      app.trades.low.filter(
        (p) =>
          (!fits || p.cost <= gold) &&
          (!steady || !isFalling(app.rows.get(p.itemId))) &&
          matches(query, app.name(p.itemId)),
      ),
    [app, fits, steady, gold, query],
  )

  const columns = useMemo<DataColumn<Plan>[]>(
    () => [
      {
        key: "name",
        label: "Item",
        text: true,
        value: (p) => app.name(p.itemId),
        cell: (p) => (
          <NameCell name={app.name(p.itemId)}>
            <FallBadge row={app.rows.get(p.itemId)} />
          </NameCell>
        ),
      },
      { key: "min", label: "Cheapest", numeric: true, width: 110, value: (p) => p.rows[0].price, cell: (p) => <Money value={p.rows[0].price} /> },
      { key: "usual", label: "Usual", numeric: true, width: 110, value: (p) => p.target, cell: (p) => <Money value={p.target} /> },
      { key: "pct", label: "Of usual", numeric: true, width: 90, value: (p) => p.rows[0].price / p.target, cell: (p) => <Share value={p.rows[0].price / p.target} /> },
      { key: "units", label: "Buy", numeric: true, width: 80, value: (p) => p.units, cell: (p) => <Count value={p.units} /> },
      { key: "cost", label: "Cost", numeric: true, width: 110, value: (p) => p.cost, cell: (p) => <Money value={p.cost} /> },
      { key: "profit", label: "Profit", numeric: true, width: 110, value: (p) => p.profit, cell: (p) => <Profit value={p.profit} /> },
      { key: "ret", label: "Return", numeric: true, width: 90, value: (p) => p.ret, cell: (p) => <Share value={p.ret} /> },
      { key: "days", label: "Sells in", numeric: true, width: 90, value: (p) => p.days, cell: (p) => <Days value={p.days} /> },
    ],
    [app],
  )

  if (app.ladder.size === 0) {
    return (
      <>
        <PageHeader title="Buy low" />
        <NoLadder />
      </>
    )
  }
  return (
    <>
      <PageHeader title="Buy low">
        Listings well below what the item usually costs. The usual price is the median of the lowest listing over
        the {formatInt(app.meta.snapshots)} snapshots of the last {app.meta.window_days} days. You buy no more than
        your share of sales can move in the time you allow; profit assumes you relist at the usual price, after
        the 5% cut.
      </PageHeader>
      <FilterBar>
        <SearchInput value={query} onChange={setQuery} placeholder="Filter items…" />
        <Assume label="Buy at or below" after="of usual">
          <Segmented
            label="Buy at or below"
            value={app.a.buyAt}
            onChange={(buyAt) => app.setA({ buyAt })}
            options={[
              [0.7, "70%"],
              [0.8, "80%"],
              [0.9, "90%"],
            ]}
          />
        </Assume>
        <Assume label="Sell within">
          <Segmented label="Sell within" value={app.a.horizon} onChange={(horizon) => app.setA({ horizon })} options={HORIZONS} />
        </Assume>
        <GoldField />
        <Toggle id="low-fits" label="Fits my gold" checked={fits} onChange={setFits} />
        <Toggle id="low-steady" label="Hide falling prices" checked={steady} onChange={setSteady} />
        <CountNote count={rows.length} noun="item" />
      </FilterBar>
      <DataTable
        rows={rows}
        columns={columns}
        itemOf={(p) => p.itemId}
        initialSort={{ key: "profit", dir: -1 }}
        minWidth={1080}
        emptyText="Nothing is listed that far below its usual price."
      />
      <Hint className="mt-2">Double-click a row for the full breakdown.</Hint>
    </>
  )
}

/** Alle Angebote bis zu einer Luecke aufkaufen und knapp unter dem naechsten wieder einstellen. */
export function ResetPage() {
  const app = useApp()
  const [query, setQuery] = useState("")
  const [holds, setHolds] = useState(false)
  const [steady, setSteady] = useState(false)
  const { resets, portfolio } = app.trades

  const rows = useMemo(
    () =>
      resets.filter((p) => {
        const row = app.rows.get(p.itemId)
        return (!holds || !refillsFast(row, app.levels)) && (!steady || !isFalling(row)) && matches(query, app.name(p.itemId))
      }),
    [app, resets, holds, steady, query],
  )

  const columns = useMemo<DataColumn<Plan>[]>(
    () => [
      {
        key: "name",
        label: "Item",
        text: true,
        value: (p) => app.name(p.itemId),
        cell: (p) => {
          const row = app.rows.get(p.itemId)
          return (
            <NameCell name={app.name(p.itemId)}>
              {portfolio.picked.has(p.itemId) && <Tag solid>In plan</Tag>}
              {refillsFast(row, app.levels) && <WarnBadge>Refills fast</WarnBadge>}
              <FallBadge row={row} />
            </NameCell>
          )
        },
      },
      { key: "units", label: "Buy", numeric: true, width: 80, value: (p) => p.units, cell: (p) => <Count value={p.units} /> },
      { key: "cost", label: "Cost", numeric: true, width: 110, value: (p) => p.cost, cell: (p) => <Money value={p.cost} /> },
      { key: "average", label: "Avg price", numeric: true, width: 110, value: (p) => p.average, cell: (p) => <Money value={p.average} /> },
      { key: "target", label: "Relist at", numeric: true, width: 110, value: (p) => p.target, cell: (p) => <Money value={p.target} /> },
      { key: "profit", label: "Profit", numeric: true, width: 110, value: (p) => p.profit, cell: (p) => <Profit value={p.profit} /> },
      { key: "ret", label: "Return", numeric: true, width: 90, value: (p) => p.ret, cell: (p) => <Share value={p.ret} /> },
      { key: "days", label: "Sells in", numeric: true, width: 90, value: (p) => p.days, cell: (p) => <Days value={p.days} /> },
      { key: "refill", label: "Refills in", numeric: true, width: 100, value: (p) => p.refill, cell: (p) => <Days value={p.refill} /> },
    ],
    [app, portfolio],
  )

  if (app.ladder.size === 0) {
    return (
      <>
        <PageHeader title="Market reset" />
        <NoLadder />
      </>
    )
  }
  return (
    <>
      <PageHeader title="Market reset">
        Buy every listing up to a gap in the price ladder and relist just under the next one, never more than 10%
        above the usual price. Shown per item is the most profitable reset your gold allows that sells within the
        time you give it and returns at least 20%. “Refills fast” marks the quarter of items where most new units
        arrive per unit sold; a falling arrow marks a price that fell 30% or more in a day.
      </PageHeader>
      <FilterBar>
        <GoldField />
        <Assume label="Per reset at most" after="of it">
          <Segmented
            label="Per reset at most"
            value={app.a.perReset}
            onChange={(perReset) => app.setA({ perReset })}
            options={[
              [0.25, "25%"],
              [0.4, "40%"],
              [1, "100%"],
            ]}
          />
        </Assume>
        <Assume label="Sell within">
          <Segmented label="Sell within" value={app.a.horizon} onChange={(horizon) => app.setA({ horizon })} options={HORIZONS} />
        </Assume>
        <Toggle id="reset-holds" label="Hide fast refills" checked={holds} onChange={setHolds} />
        <Toggle id="reset-steady" label="Hide falling prices" checked={steady} onChange={setSteady} />
      </FilterBar>
      <div className="mb-3 grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-2">
        <Stat label="Resets that fit together" sub={`of ${formatInt(resets.length)} possible`}>
          {formatInt(portfolio.picked.size)}
        </Stat>
        <Stat label="Gold they use" sub={`of ${formatInt(app.a.gold)}g`}>
          <Money value={portfolio.used} />
        </Stat>
        <Stat label="Profit if everything sells" sub="before any relisting deposits">
          <Profit value={portfolio.profit} />
        </Stat>
      </div>
      <FilterBar>
        <SearchInput value={query} onChange={setQuery} placeholder="Filter items…" />
        <CountNote count={rows.length} noun="item" />
      </FilterBar>
      <DataTable
        rows={rows}
        columns={columns}
        itemOf={(p) => p.itemId}
        initialSort={{ key: "profit", dir: -1 }}
        minWidth={1120}
        emptyText="No reset fits these settings."
      />
      <Hint className="mt-2">
        “In plan” marks the resets picked for your gold, best return first. Double-click a row for the full
        breakdown.
      </Hint>
    </>
  )
}
