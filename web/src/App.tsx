import { lazy, Suspense, useDeferredValue, useEffect, useMemo, useState } from "react"
import { Moon, Sun } from "lucide-react"

import { MarketTable } from "@/components/market-table"
import { useTheme } from "@/components/theme-provider"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { useHashSelection } from "@/hooks/use-hash-selection"
import { loadMarket, loadMeta, loadNames } from "@/lib/data"
import { formatDateTime, formatInt } from "@/lib/format"
import { ALL, categories, filterRows, nextSort, rowKey, sortRows, subcategories } from "@/lib/rows"
import type { KindFilter, MarketRow, Meta, Names, Sort, SortKey } from "@/lib/types"

// Das Diagramm wird erst geladen, wenn jemand ein Item oeffnet - die Tabelle
// steht damit, bevor die Diagramm-Bibliothek ueberhaupt angefragt wurde.
const ItemDetail = lazy(() =>
  import("@/components/item-detail").then((module) => ({ default: module.ItemDetail })),
)

type Status =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; meta: Meta; market: MarketRow[]; names: Names }

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
  const [query, setQuery] = useState("")
  const [kind, setKind] = useState<KindFilter>("all")
  const [category, setCategory] = useState(ALL)
  const [subcategory, setSubcategory] = useState(ALL)
  const [sort, setSort] = useState<Sort>({ key: "n_listings", dir: -1 })
  const [selectedKey, select] = useHashSelection()
  const deferredQuery = useDeferredValue(query)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const meta = await loadMeta()
        const [market, names] = await Promise.all([loadMarket(meta), loadNames(meta)])
        if (!cancelled) setStatus({ state: "ready", meta, market, names })
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

  const rows = useMemo(() => {
    if (!ready) return []
    return sortRows(
      filterRows(ready.market, deferredQuery, kind, ready.names, category, subcategory),
      sort,
      ready.names,
    )
  }, [ready, deferredQuery, kind, category, subcategory, sort])

  const categoryOptions = useMemo(() => (ready ? categories(ready.market) : []), [ready])
  const subcategoryOptions = useMemo(
    () => (ready && category !== ALL ? subcategories(ready.market, category) : []),
    [ready, category],
  )

  const selectedRow = useMemo(
    () => ready?.market.find((row) => rowKey(row) === selectedKey) ?? null,
    [ready, selectedKey],
  )

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
                onClose={() => select(null)}
              />
            </Suspense>
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
            {categoryOptions.length > 0 && (
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
                <SelectTrigger className="w-52" aria-label="Subcategory">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All subcategories</SelectItem>
                  {subcategoryOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.value} ({formatInt(option.count)})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <span className="text-sm text-muted-foreground">
              {formatInt(rows.length)} {rows.length === 1 ? "item" : "items"}
            </span>
          </div>

          <MarketTable
            rows={rows}
            names={ready.names}
            sort={sort}
            selectedKey={selectedKey}
            onSort={(key: SortKey) => setSort((current) => nextSort(current, key))}
            onSelect={select}
          />
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
        {ready?.meta.name_sources && ready.meta.name_sources.foreverdb > 0 && (
          <>
            {" "}
            Some names from{" "}
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
