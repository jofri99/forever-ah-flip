import { useMemo, useState } from "react"

import { CooldownBadge, CountBadge, Hint, NameCell, SpikeBadge, Tag, Toggle } from "@/components/bits"
import { DataTable } from "@/components/data-table"
import type { DataColumn } from "@/components/data-table"
import { Change, Count, Money, Profit } from "@/components/money"
import { CountNote, Empty, FilterBar, PageHeader, SearchInput } from "@/components/page"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useApp } from "@/lib/app"
import { formatInt } from "@/lib/format"
import { ALL, canCraft, matches, rowKey, tally } from "@/lib/rows"
import { belowVendor, craftPerDay, craftProfit, flipPerDay, flipProfit, sellAt } from "@/lib/trade"
import type { Craft, MarketRow, VendorFlip } from "@/lib/types"

const MINE = "mine"

interface CraftLine {
  craft: Craft
  row: MarketRow | undefined
  name: string
  sells: number | null
  profit: number | null
  day: number | null
}

/** Jedes Rezept, dessen Ergebnis im Auktionshaus steht. */
export function CraftingPage() {
  const app = useApp()
  const [query, setQuery] = useState("")
  const [profession, setProfession] = useState(ALL)
  const [profitable, setProfitable] = useState(true)
  const [sold, setSold] = useState(true)
  const [noCooldown, setNoCooldown] = useState(false)

  const professions = useMemo(() => tally(app.crafts.map((craft) => craft.profession)), [app.crafts])

  const lines = useMemo<CraftLine[]>(
    () =>
      app.crafts.map((craft) => {
        const row = app.rows.get(craft.item_id)
        const price = sellAt(row, app.a.basis)
        return {
          craft,
          row,
          name: app.name(craft.item_id),
          sells: price == null ? null : price * craft.item_count,
          profit: craftProfit(craft, row, app.a.basis),
          day: craftPerDay(craft, row, app.a),
        }
      }),
    [app],
  )

  const rows = useMemo(
    () =>
      lines.filter(
        ({ craft, row, name, profit }) =>
          (profession === ALL ||
            (profession === MINE ? app.professions[craft.profession] != null : craft.profession === profession)) &&
          (!profitable || (profit != null && profit > 0)) &&
          (!sold || (row?.qty_sold_24h ?? 0) > 0) &&
          (!noCooldown || !craft.cooldown_seconds) &&
          matches(query, name, craft.name),
      ),
    [lines, app.professions, profession, profitable, sold, noCooldown, query],
  )

  const columns = useMemo<DataColumn<CraftLine>[]>(
    () => [
      {
        key: "name",
        label: "Makes",
        text: true,
        value: (line) => line.name,
        cell: ({ craft, row, name }) => (
          <NameCell name={name}>
            <CountBadge craft={craft} />
            <CooldownBadge craft={craft} />
            <SpikeBadge row={row} basis={app.a.basis} />
          </NameCell>
        ),
      },
      {
        key: "profession",
        label: "Profession",
        text: true,
        width: 160,
        value: ({ craft }) => craft.profession,
        cell: ({ craft }) => (
          <span className="block truncate">
            {craft.profession}
            {craft.skill != null && <span className="text-muted-foreground"> {craft.skill}</span>}
          </span>
        ),
      },
      {
        key: "cost",
        label: "Reagents",
        numeric: true,
        width: 120,
        value: ({ craft }) => craft.cost,
        cell: ({ craft }) =>
          craft.cost != null ? (
            <Money value={craft.cost} />
          ) : (
            <span className="text-muted-foreground">{craft.unpriced} unpriced</span>
          ),
      },
      { key: "sells", label: "Sells for", numeric: true, width: 120, value: (line) => line.sells, cell: (line) => <Money value={line.sells} /> },
      { key: "profit", label: "Profit", numeric: true, width: 120, value: (line) => line.profit, cell: (line) => <Profit value={line.profit} /> },
      { key: "sold", label: "Sold/day", numeric: true, width: 100, value: ({ row }) => row?.qty_sold_24h, cell: ({ row }) => <Count value={row?.qty_sold_24h} /> },
      { key: "day", label: "Est./day", numeric: true, width: 120, value: (line) => line.day, cell: (line) => <Profit value={line.day} /> },
    ],
    [app.a.basis],
  )

  return (
    <>
      <PageHeader title="Crafting">
        Every recipe whose result is on the auction house. Reagents are priced at their cheapest current source;
        profit is per craft after the 5% cut.
      </PageHeader>
      <FilterBar>
        <SearchInput value={query} onChange={setQuery} placeholder="Filter recipes…" />
        <Select value={profession} onValueChange={setProfession}>
          <SelectTrigger className="w-48" aria-label="Profession">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All professions</SelectItem>
            {app.hasProfessions && <SelectItem value={MINE}>My professions</SelectItem>}
            {professions.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.value} ({formatInt(option.count)})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Toggle id="craft-profitable" label="Profitable" checked={profitable} onChange={setProfitable} />
        <Toggle id="craft-sold" label="Sold in 24h" checked={sold} onChange={setSold} />
        <Toggle id="craft-nocd" label="No cooldown" checked={noCooldown} onChange={setNoCooldown} />
        <CountNote count={rows.length} noun="recipe" />
      </FilterBar>
      <DataTable
        rows={rows}
        columns={columns}
        itemOf={(line) => line.craft.item_id}
        rowId={(line) => String(line.craft.recipe_id)}
        initialSort={{ key: "day", dir: -1 }}
        minWidth={980}
        emptyText="No recipe matches the filters."
        isDim={app.hasProfessions ? (line) => !canCraft(line.craft, app.professions) : undefined}
      />
      {app.hasProfessions && <Hint className="mt-2">Greyed out: above your skill or not one of your professions.</Hint>}
    </>
  )
}

interface FlipLine {
  flip: VendorFlip
  row: MarketRow | undefined
  name: string
  sells: number | null
  profit: number | null
  day: number | null
}

/** Was ein Haendler guenstiger verkauft als das guenstigste Angebot im Auktionshaus. */
export function FlipsPage() {
  const app = useApp()
  const [query, setQuery] = useState("")
  const [profitable, setProfitable] = useState(true)
  const [unlimited, setUnlimited] = useState(false)
  const [sold, setSold] = useState(true)

  const lines = useMemo<FlipLine[]>(
    () =>
      app.flips.map((flip) => {
        const row = app.rows.get(flip.item_id)
        return {
          flip,
          row,
          name: app.name(flip.item_id),
          sells: sellAt(row, app.a.basis),
          profit: flipProfit(flip, row, app.a.basis),
          day: flipPerDay(flip, row, app.a),
        }
      }),
    [app],
  )
  const rows = useMemo(
    () =>
      lines.filter(
        ({ flip, row, name, profit }) =>
          (!profitable || (profit != null && profit > 0)) &&
          (!unlimited || !flip.limited) &&
          (!sold || (row?.qty_sold_24h ?? 0) > 0) &&
          matches(query, name, flip.vendor, flip.zone),
      ),
    [lines, profitable, unlimited, sold, query],
  )

  const columns = useMemo<DataColumn<FlipLine>[]>(
    () => [
      {
        key: "name",
        label: "Item",
        text: true,
        value: (line) => line.name,
        cell: ({ flip, row, name }) => (
          <NameCell name={name}>
            {flip.limited && <Tag>Limited{flip.limited_stock ? ` · ${flip.limited_stock}` : ""}</Tag>}
            <SpikeBadge row={row} basis={app.a.basis} />
          </NameCell>
        ),
      },
      { key: "vendor_price", label: "Vendor", numeric: true, width: 110, value: ({ flip }) => flip.vendor_price, cell: ({ flip }) => <Money value={flip.vendor_price} /> },
      { key: "sells", label: "Sells for", numeric: true, width: 120, value: (line) => line.sells, cell: (line) => <Money value={line.sells} /> },
      { key: "profit", label: "Profit", numeric: true, width: 120, value: (line) => line.profit, cell: (line) => <Profit value={line.profit} /> },
      { key: "sold", label: "Sold/day", numeric: true, width: 100, value: ({ row }) => row?.qty_sold_24h, cell: ({ row }) => <Count value={row?.qty_sold_24h} /> },
      { key: "day", label: "Est./day", numeric: true, width: 120, value: (line) => line.day, cell: (line) => <Profit value={line.day} /> },
      {
        key: "vendor",
        label: "Sold by",
        text: true,
        width: 250,
        value: ({ flip }) => flip.vendor,
        cell: ({ flip }) => (
          <span className="block truncate">
            {flip.vendor}
            {flip.zone && <span className="text-muted-foreground"> · {flip.zone}</span>}
          </span>
        ),
      },
    ],
    [app.a.basis],
  )

  return (
    <>
      <PageHeader title="Vendor flips">
        Items a vendor sells for less than the lowest auction house listing. Vendor stock is not checked in game:
        a vendor may require reputation, and limited stock restocks slowly.
      </PageHeader>
      <FilterBar>
        <SearchInput value={query} onChange={setQuery} placeholder="Filter items, vendors, zones…" />
        <Toggle id="flip-profitable" label="Profitable" checked={profitable} onChange={setProfitable} />
        <Toggle id="flip-unlimited" label="Unlimited stock" checked={unlimited} onChange={setUnlimited} />
        <Toggle id="flip-sold" label="Sold in 24h" checked={sold} onChange={setSold} />
        <CountNote count={rows.length} noun="item" />
      </FilterBar>
      <DataTable
        rows={rows}
        columns={columns}
        itemOf={(line) => line.flip.item_id}
        initialSort={{ key: "day", dir: -1 }}
        minWidth={1080}
        emptyText="No vendor flip matches the filters."
      />
    </>
  )
}

function useMarketColumns(): DataColumn<MarketRow>[] {
  const app = useApp()
  return useMemo<DataColumn<MarketRow>[]>(
    () => [
      {
        key: "name",
        label: "Item",
        text: true,
        value: (row) => app.name(row.item_id),
        cell: (row) => (
          <NameCell name={app.name(row.item_id)}>
            {row.kind === "commodity" && <Tag>Commodity</Tag>}
            {app.craftsByItem.has(row.item_id) && <Tag>Craftable</Tag>}
            {belowVendor(row, undefined) && <Tag solid>Below vendor</Tag>}
          </NameCell>
        ),
      },
      { key: "min_price", label: "Lowest", numeric: true, width: 120, value: (row) => row.min_price, cell: (row) => <Money value={row.min_price} /> },
      { key: "usual_price", label: "Usual", numeric: true, width: 120, value: (row) => row.usual_price, cell: (row) => <Money value={row.usual_price} /> },
      { key: "change_24h_pct", label: "24h", numeric: true, width: 100, value: (row) => row.change_24h_pct, cell: (row) => <Change value={row.change_24h_pct} /> },
      { key: "n_listings", label: "Listings", numeric: true, width: 100, value: (row) => row.n_listings, cell: (row) => <Count value={row.n_listings} /> },
      { key: "quantity", label: "Units", numeric: true, width: 110, value: (row) => row.quantity, cell: (row) => <Count value={row.quantity} /> },
      { key: "qty_sold_24h", label: "Sold/day", numeric: true, width: 110, value: (row) => row.qty_sold_24h, cell: (row) => <Count value={row.qty_sold_24h} /> },
    ],
    [app],
  )
}

/** Der juengste Stand des Auktionshauses, eine Zeile je Item. */
export function MarketPage() {
  const app = useApp()
  const [query, setQuery] = useState("")
  const [category, setCategory] = useState(ALL)
  const [subcategory, setSubcategory] = useState(ALL)
  const columns = useMarketColumns()

  const categories = useMemo(() => tally(app.market.map((row) => row.item_class)), [app.market])
  const subcategories = useMemo(
    () =>
      category === ALL
        ? []
        : tally(app.market.filter((row) => row.item_class === category).map((row) => row.item_subclass)),
    [app.market, category],
  )
  const rows = useMemo(
    () =>
      app.market.filter(
        (row) =>
          (category === ALL || row.item_class === category) &&
          (subcategory === ALL || row.item_subclass === subcategory) &&
          (matches(query, app.name(row.item_id)) || String(row.item_id) === query.trim()),
      ),
    [app, category, subcategory, query],
  )

  return (
    <>
      <PageHeader title="Market">
        The latest snapshot of the auction house, one row per item. Click a row for its history, double-click for
        everything about it.
      </PageHeader>
      <FilterBar>
        <SearchInput value={query} onChange={setQuery} placeholder="Filter items or enter an ID…" />
        <Select
          value={category}
          onValueChange={(value) => {
            setCategory(value)
            setSubcategory(ALL)
          }}
        >
          <SelectTrigger className="w-52" aria-label="Category">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All categories</SelectItem>
            {categories.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.value} ({formatInt(option.count)})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {subcategories.length > 1 && (
          <Select value={subcategory} onValueChange={setSubcategory}>
            <SelectTrigger className="w-52" aria-label="Subcategory">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All subcategories</SelectItem>
              {subcategories.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.value} ({formatInt(option.count)})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <CountNote count={rows.length} noun="item" />
      </FilterBar>
      <DataTable
        rows={rows}
        columns={columns}
        itemOf={(row) => row.item_id}
        rowId={rowKey}
        initialSort={{ key: "qty_sold_24h", dir: -1 }}
        minWidth={980}
        emptyText="No item matches the search."
      />
    </>
  )
}

/** Die Items, die der Nutzer mit dem Stern markiert hat. */
export function WatchlistPage() {
  const app = useApp()
  const columns = useMarketColumns()
  const rows = useMemo(
    () => app.watch.flatMap((itemId) => (app.rows.has(itemId) ? [app.rows.get(itemId) as MarketRow] : [])),
    [app.watch, app.rows],
  )
  const gone = app.watch.length - rows.length
  return (
    <>
      <PageHeader title="Watchlist">Items you starred, kept in this browser.</PageHeader>
      {rows.length === 0 ? (
        <div className="rounded-xl border bg-card">
          <Empty>Nothing here yet. Open an item and press the star to keep an eye on it.</Empty>
        </div>
      ) : (
        <DataTable
          rows={rows}
          columns={columns}
          itemOf={(row) => row.item_id}
          initialSort={{ key: "name", dir: 1 }}
          minWidth={980}
          emptyText=""
        />
      )}
      {gone > 0 && (
        <Hint className="mt-2">
          {gone} starred item{gone === 1 ? " is" : "s are"} not on the auction house right now.
        </Hint>
      )}
    </>
  )
}
