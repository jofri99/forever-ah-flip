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
import { filterRows, nextSort, rowKey, sortRows } from "@/lib/rows"
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
      aria-label={dark ? "Helles Design" : "Dunkles Design"}
    >
      {dark ? <Sun /> : <Moon />}
    </Button>
  )
}

export function App() {
  const [status, setStatus] = useState<Status>({ state: "loading" })
  const [query, setQuery] = useState("")
  const [kind, setKind] = useState<KindFilter>("all")
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
    return sortRows(filterRows(ready.market, deferredQuery, kind, ready.names), sort, ready.names)
  }, [ready, deferredQuery, kind, sort])

  const selectedRow = useMemo(
    () => ready?.market.find((row) => rowKey(row) === selectedKey) ?? null,
    [ready, selectedKey],
  )

  return (
    <div className="mx-auto flex min-h-svh max-w-7xl flex-col gap-4 p-4 md:p-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Forever AH – Horde, Ruleset Normal</h1>
          <p className="text-sm text-muted-foreground">
            {ready
              ? `Stand ${formatDateTime(ready.meta.last_snapshot)} · ${formatInt(ready.meta.items)} Items · ` +
                `${ready.meta.snapshots} Stände seit ${formatDateTime(ready.meta.first_snapshot)}`
              : status.state === "loading"
                ? "Lade Daten …"
                : "Keine Daten"}
          </p>
        </div>
        <ThemeToggle />
      </header>

      {status.state === "error" && (
        <p className="rounded-lg border border-destructive/40 p-4 text-sm text-destructive">
          Die Daten konnten nicht geladen werden ({status.message}). Lokal zuerst{" "}
          <code>python -m collector publish</code> ausführen.
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
              placeholder="Item oder ID suchen …"
              aria-label="Item oder ID suchen"
              className="max-w-sm"
            />
            <Select value={kind} onValueChange={(value) => setKind(value as KindFilter)}>
              <SelectTrigger className="w-44" aria-label="Art">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Alle Arten</SelectItem>
                <SelectItem value="auction">Einzelstücke</SelectItem>
                <SelectItem value="commodity">Stapelware</SelectItem>
              </SelectContent>
            </Select>
            <span className="text-sm text-muted-foreground">{formatInt(rows.length)} Items</span>
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
        Daten: Battle.net-API von Blizzard, stündlich gesammelt. Preise je Stück. Diagramme:{" "}
        <a
          href="https://www.tradingview.com/"
          target="_blank"
          rel="noopener noreferrer"
          className="underline underline-offset-2"
        >
          TradingView Lightweight Charts
        </a>
        .
      </footer>
    </div>
  )
}

export default App
