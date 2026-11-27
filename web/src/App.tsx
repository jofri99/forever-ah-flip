import { useEffect, useMemo, useState } from "react"
import type { ReactNode } from "react"
import {
  ArrowDownToLine,
  ChartNoAxesColumn,
  FlaskConical,
  LayoutDashboard,
  Moon,
  RefreshCw,
  Search,
  ShoppingCart,
  Star,
  Store,
  Sun,
  User,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { Assume, Segmented } from "@/components/bits"
import { CommandPalette, ProfessionsDialog } from "@/components/dialogs"
import { ItemPanel } from "@/components/item-panel"
import { useTheme } from "@/components/theme-provider"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { AppProvider, deriveData, useApp } from "@/lib/app"
import type { AppData } from "@/lib/app"
import {
  loadCraftReagents,
  loadCrafts,
  loadItemVendors,
  loadLadder,
  loadMarket,
  loadMeta,
  loadNames,
  loadVendorFlips,
} from "@/lib/data"
import { formatDateTime, formatInt } from "@/lib/format"
import type { Page } from "@/lib/route"
import { craftProfit } from "@/lib/trade"
import { ItemPage } from "@/pages/item"
import { CraftingPage, FlipsPage, MarketPage, WatchlistPage } from "@/pages/lists"
import { OpportunitiesPage } from "@/pages/opportunities"
import { ShoppingPage } from "@/pages/shopping"
import { LowPage, ResetPage } from "@/pages/trade"

type Status = { state: "loading" } | { state: "error"; message: string } | { state: "ready"; data: AppData }

function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const dark =
    theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches)
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(dark ? "light" : "dark")}
      aria-label={dark ? "Light theme" : "Dark theme"}
      title={dark ? "Light theme" : "Dark theme"}
    >
      {dark ? <Sun /> : <Moon />}
    </Button>
  )
}

function NavButton({
  icon: Icon,
  label,
  active,
  count,
  sub,
  onClick,
}: {
  icon: LucideIcon
  label: string
  active?: boolean
  count?: number
  sub?: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-current={active ? "page" : undefined}
      className={`flex w-full items-center justify-center gap-2.5 rounded-md px-0 py-2 text-left text-sm focus-visible:outline-2 focus-visible:outline-ring lg:justify-start lg:px-2.5 lg:py-1.5 ${
        active ? "bg-muted font-medium text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground"
      }`}
    >
      <Icon className="size-4 shrink-0" aria-hidden />
      <span className="hidden min-w-0 flex-1 lg:block">
        <span className="block truncate">{label}</span>
        {sub && <span className="block truncate text-[11px] font-normal text-muted-foreground">{sub}</span>}
      </span>
      {count != null && count > 0 && (
        <span className="hidden text-[11px] text-muted-foreground tabular-nums lg:inline">{formatInt(count)}</span>
      )}
    </button>
  )
}

/** Der Rahmen: Navigation links, Annahmen oben, die Seite in der Mitte, das gewaehlte Item rechts. */
function Shell() {
  const app = useApp()
  const { route } = app
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [professionsOpen, setProfessionsOpen] = useState(false)

  // Von welcher Liste aus die Vollseite eines Items geoeffnet wurde.
  const [origin, setOrigin] = useState<Page>(route.page === "item" ? "opportunities" : route.page)
  if (route.page !== "item" && route.page !== origin) setOrigin(route.page)

  const profitable = useMemo(
    () =>
      app.crafts.filter((craft) => (craftProfit(craft, app.rows.get(craft.item_id), app.a.basis) ?? 0) > 0).length,
    [app.crafts, app.rows, app.a.basis],
  )

  const { back, select } = app
  const overlayOpen = paletteOpen || professionsOpen
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault()
        setPaletteOpen((open) => !open)
        return
      }
      if (overlayOpen) return
      const typing = event.target instanceof HTMLElement && /^(INPUT|SELECT|TEXTAREA)$/.test(event.target.tagName)
      if (event.key === "Escape") {
        if (route.page === "item") back()
        else if (route.id != null) select(null)
      } else if (event.key === "/" && !typing) {
        const field = document.querySelector<HTMLInputElement>('main input[type="search"]')
        if (field) {
          event.preventDefault()
          field.focus()
        }
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [overlayOpen, route.page, route.id, back, select])

  const hasLadder = app.ladder.size > 0
  const professions = Object.entries(app.professions)
  const pages: Record<Page, ReactNode> = {
    opportunities: <OpportunitiesPage onSetProfessions={() => setProfessionsOpen(true)} />,
    crafting: <CraftingPage />,
    flips: <FlipsPage />,
    low: <LowPage />,
    reset: <ResetPage />,
    market: <MarketPage />,
    watchlist: <WatchlistPage />,
    shopping: <ShoppingPage />,
    item: route.id != null ? <ItemPage key={route.id} itemId={route.id} origin={origin} /> : null,
  }
  const nav = (page: Page, label: string, icon: LucideIcon, count?: number) => (
    <NavButton icon={icon} label={label} count={count} active={route.page === page} onClick={() => app.go(page)} />
  )

  return (
    <div className="grid h-svh grid-cols-[auto_minmax(0,1fr)_auto] overflow-hidden bg-muted/40 text-sm">
      <nav aria-label="Sections" className="flex w-14 flex-col gap-0.5 border-r bg-card px-1.5 py-3 lg:w-52 lg:px-2">
        <div className="flex items-center justify-center gap-2 px-2.5 pb-3 text-[15px] font-semibold lg:justify-start">
          <i className="size-[18px] shrink-0 rounded-[5px] bg-price" aria-hidden />
          <span className="hidden lg:inline">Forever AH</span>
        </div>
        {nav("opportunities", "Opportunities", LayoutDashboard)}
        {app.crafts.length > 0 && nav("crafting", "Crafting", FlaskConical, profitable)}
        {app.flips.length > 0 && nav("flips", "Vendor flips", Store, app.flips.length)}
        {hasLadder && nav("low", "Buy low", ArrowDownToLine, app.trades.lowSteady.length)}
        {hasLadder && nav("reset", "Market reset", RefreshCw, app.trades.resets.length)}
        {nav("market", "Market", ChartNoAxesColumn)}
        <div className="mx-1.5 my-2 h-px bg-border" />
        {nav("watchlist", "Watchlist", Star, app.watch.length)}
        {nav("shopping", "Shopping list", ShoppingCart, app.cart.length)}
        <div className="mt-auto flex flex-col gap-1.5">
          {app.crafts.length > 0 && (
            <NavButton
              icon={User}
              label="My professions"
              sub={professions.length ? professions.map(([name, skill]) => `${name} ${skill}`).join(" · ") : "Not set"}
              onClick={() => setProfessionsOpen(true)}
            />
          )}
          <p className="hidden px-2.5 text-[11px] leading-snug text-muted-foreground lg:block">
            Horde · Normal ruleset
            <br />
            {app.meta.live_snapshot ? "Listings" : "Snapshot"} as of{" "}
            {formatDateTime(app.meta.live_snapshot ?? app.meta.last_snapshot)}
            <br />
            {formatInt(app.meta.snapshots)} snapshots in {app.meta.window_days} days
          </p>
        </div>
      </nav>

      <div className="flex min-w-0 flex-col">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b bg-card px-4 py-2.5">
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            className="flex min-w-48 flex-1 items-center gap-2 rounded-lg border bg-background px-2.5 py-1.5 text-left text-muted-foreground hover:border-ring focus-visible:outline-2 focus-visible:outline-ring sm:max-w-80"
          >
            <Search className="size-4" aria-hidden />
            <span className="truncate">Search items and recipes…</span>
            <kbd className="ml-auto rounded border bg-card px-1.5 font-mono text-[11px] whitespace-nowrap">Ctrl K</kbd>
          </button>
          <span className="flex-1" />
          <Assume label="Sell at">
            <Segmented
              label="Sell at"
              value={app.a.basis}
              onChange={(basis) => app.setA({ basis })}
              options={[
                ["now", "Lowest now"],
                ["low", "24h low"],
              ]}
            />
          </Assume>
          <Assume label="My share of sales">
            <Segmented
              label="My share of sales"
              value={app.a.share}
              onChange={(share) => app.setA({ share })}
              options={[
                [0.05, "5%"],
                [0.1, "10%"],
                [0.25, "25%"],
              ]}
            />
          </Assume>
          <Button variant="outline" onClick={() => app.go("shopping")}>
            <ShoppingCart aria-hidden />
            Shopping list
            {app.cart.length > 0 && (
              <span className="rounded-full bg-primary px-1.5 text-[11px] text-primary-foreground">{app.cart.length}</span>
            )}
          </Button>
          <ThemeToggle />
        </div>

        <main className="flex-1 overflow-auto px-5 pt-4 pb-6">
          {pages[route.page]}
          <footer className="mt-6 text-xs text-muted-foreground">
            Data: Blizzard Battle.net API, collected hourly. Prices per unit. Charts:{" "}
            <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
              TradingView Lightweight Charts
            </a>
            .
            {((app.meta.name_sources?.foreverdb ?? 0) > 0 || app.flips.length > 0 || app.crafts.length > 0) && (
              <>
                {" "}
                Some names and all vendor and recipe data from{" "}
                <a href="https://foreverdb.net" target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
                  ForeverDB.net
                </a>
                .
              </>
            )}
          </footer>
        </main>
      </div>

      {route.page !== "item" && route.id != null && <ItemPanel key={route.id} itemId={route.id} />}
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      <ProfessionsDialog open={professionsOpen} onOpenChange={setProfessionsOpen} />
    </div>
  )
}

export function App() {
  const [status, setStatus] = useState<Status>({ state: "loading" })

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const meta = await loadMeta()
        const [market, names, flips, crafts, reagents, ladder, vendors] = await Promise.all([
          loadMarket(meta),
          loadNames(meta),
          loadVendorFlips(meta),
          loadCrafts(meta),
          loadCraftReagents(meta),
          loadLadder(meta),
          loadItemVendors(meta),
        ])
        if (!cancelled) {
          setStatus({
            state: "ready",
            data: deriveData({ meta, market, names, flips, crafts, reagents, ladder, vendors }),
          })
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

  if (status.state === "loading") {
    return (
      <div className="flex h-svh flex-col gap-3 p-6">
        <Skeleton className="h-9 w-full max-w-md" />
        <Skeleton className="w-full flex-1" />
      </div>
    )
  }
  if (status.state === "error") {
    return (
      <p className="m-6 rounded-lg border border-destructive/40 p-4 text-sm text-destructive">
        The data could not be loaded ({status.message}). Locally, run <code>python -m collector publish</code> first.
      </p>
    )
  }
  return (
    <AppProvider data={status.data}>
      <Shell />
    </AppProvider>
  )
}

export default App
