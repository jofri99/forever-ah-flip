import { lazy, Suspense, useDeferredValue, useEffect, useMemo, useState } from "react"
import { Moon, Sun } from "lucide-react"

import { CraftTable } from "@/components/craft-table"
import { FlipTable } from "@/components/flip-table"
import { MarketTable } from "@/components/market-table"
import { useTheme } from "@/components/theme-provider"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useHashSelection } from "@/hooks/use-hash-selection"
import {
  loadCraftReagents,
  loadCrafts,
  loadMarket,
  loadMeta,
  loadNames,
  loadVendorFlips,
} from "@/lib/data"
import { formatDateTime, formatInt } from "@/lib/format"
import {
  ALL,
  categories,
  craftCategories,
  craftsByItem,
  filterCrafts,
  filterFlips,
  filterRows,
  groupReagents,
  nextSort,
  professions,
  rowKey,
  sortCrafts,
  sortFlips,
  sortRows,
  subcategories,
} from "@/lib/rows"
import type {
  Craft,
  CraftReagent,
  CraftSortKey,
  FlipSortKey,
  KindFilter,
  MarketRow,
  Meta,
  Names,
  Sort,
  SortKey,
  VendorFlip,
} from "@/lib/types"

// Das Diagramm wird erst geladen, wenn jemand ein Item oeffnet - die Tabelle
// steht damit, bevor die Diagramm-Bibliothek ueberhaupt angefragt wurde.
const ItemDetail = lazy(() =>
  import("@/components/item-detail").then((module) => ({ default: module.ItemDetail })),
)

type Status =
  | { state: "loading" }
  | { state: "error"; message: string }
  | {
      state: "ready"
      meta: Meta
      market: MarketRow[]
      names: Names
      flips: VendorFlip[]
      crafts: Craft[]
      reagents: CraftReagent[]
    }

type View = "market" | "flips" | "crafts"

const NO_CRAFTS: Craft[] = []

function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const dark =
    theme === "dark" ||
    (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches)
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(dark ? "light" : "dark")}
      aria-label={dark ? "Light theme" : "Dark theme"}
    >
      {dark ? <Sun /> : <Moon />}
    </Button>
  )
}

export function App() {
  const [status, setStatus] = useState<Status>({ state: "loading" })
  const [view, setView] = useState<View>("market")
  const [query, setQuery] = useState("")
  const [kind, setKind] = useState<KindFilter>("all")
  const [category, setCategory] = useState(ALL)
  const [subcategory, setSubcategory] = useState(ALL)
  const [sort, setSort] = useState<Sort>({ key: "n_listings", dir: -1 })
  const [flipSort, setFlipSort] = useState<Sort<FlipSortKey>>({ key: "profit", dir: -1 })
  const [craftSort, setCraftSort] = useState<Sort<CraftSortKey>>({ key: "profit", dir: -1 })
  const [unlimitedOnly, setUnlimitedOnly] = useState(false)
  const [soldOnly, setSoldOnly] = useState(false)
  const [profitableOnly, setProfitableOnly] = useState(true)
  const [selectedKey, select] = useHashSelection()
  const deferredQuery = useDeferredValue(query)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const meta = await loadMeta()
        const [market, names, flips, crafts, reagents] = await Promise.all([
          loadMarket(meta),
          loadNames(meta),
          loadVendorFlips(meta),
          loadCrafts(meta),
          loadCraftReagents(meta),
        ])
        if (!cancelled) {
          setStatus({ state: "ready", meta, market, names, flips, crafts, reagents })
        }
      } catch (error) {
        if (!cancelled) {
          setStatus({ state: "error", message: error instanceof Error ? error.message : String(error) })
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const ready = status.state === "ready" ? status : null
  // Haendler-Flips und Rezepte gibt es nur mit lokalem Abzug. Ohne sie bleibt es beim Markt.
  const hasFlips = (ready?.flips.length ?? 0) > 0
  const hasCrafts = (ready?.crafts.length ?? 0) > 0
  const showFlips = view === "flips" && hasFlips
  const showCrafts = view === "crafts" && hasCrafts

  const marketRows = useMemo(() => {
    if (!ready) return []
    return sortRows(
      filterRows(ready.market, deferredQuery, kind, ready.names, category, subcategory),
      sort,
      ready.names,
    )
  }, [ready, deferredQuery, kind, category, subcategory, sort])

  const flipRows = useMemo(() => {
    if (!ready) return []
    const filtered = filterRows(ready.flips, deferredQuery, "all", ready.names, category, subcategory)
    return sortFlips(filterFlips(filtered, { unlimitedOnly, soldOnly }), flipSort, ready.names)
  }, [ready, deferredQuery, category, subcategory, unlimitedOnly, soldOnly, flipSort])

  const craftRows = useMemo(() => {
    if (!ready) return []
    const filtered = filterCrafts(
      ready.crafts,
      { query: deferredQuery, profession: category, category: subcategory, profitableOnly, soldOnly },
      ready.names,
    )
    return sortCrafts(filtered, craftSort, ready.names)
  }, [ready, deferredQuery, category, subcategory, profitableOnly, soldOnly, craftSort])

  // Die Auswahl richtet sich nach der gezeigten Ansicht: Typ und Untertyp des Items,
  // bei den Rezepten Beruf und Gruppe.
  const source = ready ? (showFlips ? ready.flips : ready.market) : null
  const crafts = ready?.crafts ?? NO_CRAFTS
  const categoryOptions = useMemo(
    () => (showCrafts ? professions(crafts) : source ? categories(source) : []),
    [showCrafts, crafts, source],
  )
  const subcategoryOptions = useMemo(() => {
    if (category === ALL) return []
    if (showCrafts) return craftCategories(crafts, category)
    return source ? subcategories(source, category) : []
  }, [showCrafts, crafts, source, category])

  const selectedRow = useMemo(
    () => ready?.market.find((row) => rowKey(row) === selectedKey) ?? null,
    [ready, selectedKey],
  )

  // Fuer die Detailansicht: welche Rezepte stellen ein Item her, was brauchen sie,
  // und unter welchem Schluessel steht eine Zutat im Markt.
  const craftIndex = useMemo(() => craftsByItem(crafts), [crafts])
  const reagentIndex = useMemo(() => groupReagents(ready?.reagents ?? []), [ready])
  const marketKeys = useMemo(() => {
    const keys = new Map<number, string>()
    for (const row of ready?.market ?? []) {
      if (!keys.has(row.item_id)) keys.set(row.item_id, rowKey(row))
    }
    return keys
  }, [ready])

  const shown = showCrafts ? craftRows.length : showFlips ? flipRows.length : marketRows.length

  return (
    <div className="mx-auto flex min-h-svh max-w-7xl flex-col gap-4 p-4 md:p-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Forever AH – Horde, Normal ruleset</h1>
          <p className="text-sm text-muted-foreground">
            {ready
              ? `As of ${formatDateTime(ready.meta.last_snapshot)} · ${formatInt(ready.meta.items)} items · ` +
                `${ready.meta.snapshots} snapshots since ${formatDateTime(ready.meta.first_snapshot)}`
              : status.state === "loading"
                ? "Loading data …"
                : "No data"}
          </p>
        </div>
        <ThemeToggle />
      </header>

      {status.state === "error" && (
        <p className="rounded-lg border border-destructive/40 p-4 text-sm text-destructive">
          The data could not be loaded ({status.message}). Locally, run{" "}
          <code>python -m collector publish</code> first.
        </p>
      )}

      {status.state === "loading" && (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-9 w-full max-w-md" />
          <Skeleton className="h-96 w-full" />
        </div>
      )}

      {ready && (
        <>
          {selectedRow && (
            <Suspense fallback={<Skeleton className="h-[560px] w-full" />}>
              <ItemDetail
                key={rowKey(selectedRow)}
                meta={ready.meta}
                row={selectedRow}
                names={ready.names}
                crafts={craftIndex.get(selectedRow.item_id) ?? NO_CRAFTS}
                reagents={reagentIndex}
                marketKey={(itemId) => marketKeys.get(itemId) ?? null}
                onSelect={select}
                onClose={() => select(null)}
              />
            </Suspense>
          )}

          {(hasFlips || hasCrafts) && (
            <Tabs
              value={view}
              onValueChange={(value) => {
                setView(value as View)
                // Jede Ansicht kennt andere Typen.
                setCategory(ALL)
                setSubcategory(ALL)
              }}
            >
              <TabsList>
                <TabsTrigger value="market">Market</TabsTrigger>
                {hasFlips && (
                  <TabsTrigger value="flips">Vendor flips ({formatInt(ready.flips.length)})</TabsTrigger>
                )}
                {hasCrafts && (
                  <TabsTrigger value="crafts">Crafting ({formatInt(ready.crafts.length)})</TabsTrigger>
                )}
              </TabsList>
            </Tabs>
          )}

          {showFlips && (
            <p className="text-sm text-muted-foreground">
              Buy from a vendor, sell on the auction house. Profit is per unit, after the 5% auction
              house cut, against the lowest current listing. Vendor stock comes from ForeverDB and is
              not checked in game: a vendor may require reputation, and limited stock restocks slowly.
            </p>
          )}

          {showCrafts && (
            <p className="text-sm text-muted-foreground">
              Buy the reagents, craft, sell on the auction house. Every reagent is priced at its
              cheapest current source, auction house or vendor. Profit is per craft, after the 5%
              auction house cut, against the lowest current listing. Recipes come from ForeverDB;
              learning one costs extra and cooldowns are not considered.
            </p>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <Input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search item or ID …"
              aria-label="Search item or ID"
              className="max-w-sm"
            />
            {!showFlips && !showCrafts && (
              <Select value={kind} onValueChange={(value) => setKind(value as KindFilter)}>
                <SelectTrigger className="w-44" aria-label="Listing kind">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All listings</SelectItem>
                  <SelectItem value="auction">Single items</SelectItem>
                  <SelectItem value="commodity">Commodities</SelectItem>
                </SelectContent>
              </Select>
            )}
            {categoryOptions.length > 0 && (
              <Select
                value={category}
                onValueChange={(value) => {
                  setCategory(value)
                  setSubcategory(ALL)
                }}
              >
                <SelectTrigger className="w-52" aria-label={showCrafts ? "Profession" : "Category"}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>{showCrafts ? "All professions" : "All categories"}</SelectItem>
                  {categoryOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.value} ({formatInt(option.count)})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            {subcategoryOptions.length > 1 && (
              <Select value={subcategory} onValueChange={setSubcategory}>
                <SelectTrigger className="w-52" aria-label={showCrafts ? "Category" : "Subcategory"}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>{showCrafts ? "All categories" : "All subcategories"}</SelectItem>
                  {subcategoryOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.value} ({formatInt(option.count)})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            {showFlips && (
              <div className="flex items-center gap-2">
                <Switch id="unlimited" checked={unlimitedOnly} onCheckedChange={setUnlimitedOnly} />
                <Label htmlFor="unlimited">Unlimited stock only</Label>
              </div>
            )}
            {showCrafts && (
              <div className="flex items-center gap-2">
                <Switch id="profitable" checked={profitableOnly} onCheckedChange={setProfitableOnly} />
                <Label htmlFor="profitable">Profitable only</Label>
              </div>
            )}
            {(showFlips || showCrafts) && (
              <div className="flex items-center gap-2">
                <Switch id="sold" checked={soldOnly} onCheckedChange={setSoldOnly} />
                <Label htmlFor="sold">Sold in last 24h</Label>
              </div>
            )}
            <span className="text-sm text-muted-foreground">
              {formatInt(shown)} {showCrafts ? "recipe" : "item"}
              {shown === 1 ? "" : "s"}
            </span>
          </div>

          {showCrafts ? (
            <CraftTable
              rows={craftRows}
              names={ready.names}
              sort={craftSort}
              selectedKey={selectedKey}
              onSort={(key: CraftSortKey) => setCraftSort((current) => nextSort(current, key))}
              onSelect={select}
            />
          ) : showFlips ? (
            <FlipTable
              rows={flipRows}
              names={ready.names}
              sort={flipSort}
              selectedKey={selectedKey}
              onSort={(key: FlipSortKey) => setFlipSort((current) => nextSort(current, key))}
              onSelect={select}
            />
          ) : (
            <MarketTable
              rows={marketRows}
              names={ready.names}
              sort={sort}
              selectedKey={selectedKey}
              onSort={(key: SortKey) => setSort((current) => nextSort(current, key))}
              onSelect={select}
            />
          )}
        </>
      )}

      <footer className="mt-auto pt-4 text-xs text-muted-foreground">
        Data: Blizzard Battle.net API, collected hourly. Prices per unit. Charts:{" "}
        <a
          href="https://www.tradingview.com/"
          target="_blank"
          rel="noopener noreferrer"
          className="underline underline-offset-2"
        >
          TradingView Lightweight Charts
        </a>
        .
        {ready && ((ready.meta.name_sources?.foreverdb ?? 0) > 0 || hasFlips || hasCrafts) && (
          <>
            {" "}
            Some names and all vendor and recipe data from{" "}
            <a
              href="https://foreverdb.net"
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2"
            >
              ForeverDB.net
            </a>
            .
          </>
        )}
      </footer>
    </div>
  )
}

export default App
