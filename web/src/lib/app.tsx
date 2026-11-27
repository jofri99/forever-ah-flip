import { createContext, useCallback, useContext, useMemo } from "react"
import type { ReactNode } from "react"

import { cheapestRows, craftsByItem, groupReagents, usedIn } from "./rows"
import { useRoute } from "./route"
import type { Page, Route } from "./route"
import { usePersistent } from "./settings"
import { bestReset, churnLevels, DEFAULT_ASSUMPTIONS, lowBuy, pickResets } from "./trade"
import type { Assumptions, ChurnLevels, Plan, Portfolio, Tier } from "./trade"
import type {
  CartLine,
  Craft,
  CraftReagent,
  ItemVendor,
  MarketRow,
  Meta,
  Names,
  Professions,
  VendorFlip,
} from "./types"

/** Was geladen wird. */
export interface Loaded {
  meta: Meta
  market: MarketRow[]
  names: Names
  crafts: Craft[]
  reagents: CraftReagent[]
  flips: VendorFlip[]
  ladder: Map<number, Tier[]>
  vendors: Map<number, ItemVendor[]>
}

/** Die geladenen Daten samt allem, was sich einmal daraus ableiten laesst. */
export interface AppData {
  meta: Meta
  market: MarketRow[]
  names: Names
  crafts: Craft[]
  flips: VendorFlip[]
  /** Die Preisleiter je Item. Leer, wenn beim Bauen kein aktueller Stand geholt wurde. */
  ladder: Map<number, Tier[]>
  vendors: Map<number, ItemVendor[]>
  /** Je Item die guenstigere Marktzeile. */
  rows: Map<number, MarketRow>
  reagents: Map<number, CraftReagent[]>
  craftsByItem: Map<number, Craft[]>
  craftById: Map<number, Craft>
  usedIn: Map<number, Craft[]>
  flipByItem: Map<number, VendorFlip>
  levels: ChurnLevels
}

export function deriveData(loaded: Loaded): AppData {
  // Zutaten, die es nur beim Haendler gibt, stehen nicht in names.json.
  const names = { ...loaded.names }
  for (const reagent of loaded.reagents) names[String(reagent.item_id)] ??= reagent.name
  const rows = cheapestRows(loaded.market)
  const reagents = groupReagents(loaded.reagents)
  return {
    meta: loaded.meta,
    market: loaded.market,
    names,
    crafts: loaded.crafts,
    flips: loaded.flips,
    ladder: loaded.ladder,
    vendors: loaded.vendors,
    rows,
    reagents,
    craftsByItem: craftsByItem(loaded.crafts),
    craftById: new Map(loaded.crafts.map((craft) => [craft.recipe_id, craft])),
    usedIn: usedIn(loaded.crafts, reagents),
    flipByItem: new Map(loaded.flips.map((flip) => [flip.item_id, flip])),
    levels: churnLevels(rows.values()),
  }
}

/** Guenstige Einkaeufe und Resets, wie die Annahmen sie gerade ergeben. */
export interface Trades {
  low: Plan[]
  resets: Plan[]
  portfolio: Portfolio
}

export interface AppValue extends AppData {
  a: Assumptions
  setA: (patch: Partial<Assumptions>) => void
  professions: Professions
  setProfessions: (next: Professions) => void
  hasProfessions: boolean
  watch: number[]
  toggleWatch: (itemId: number) => void
  cart: CartLine[]
  setCartQuantity: (recipeId: number, quantity: number) => void
  clearCart: () => void
  trades: Trades
  route: Route
  /** Wechselt die Seite. Das Item in der Seitenleiste bleibt offen. */
  go: (page: Page) => void
  /** Waehlt ein Item fuer die Seitenleiste - auf der Vollseite wechselt es das Item. */
  select: (itemId: number | null, replace?: boolean) => void
  /** Oeffnet die Vollseite eines Items. */
  open: (itemId: number) => void
  back: () => void
  name: (itemId: number) => string
}

const Context = createContext<AppValue | null>(null)

export function useApp(): AppValue {
  const value = useContext(Context)
  if (!value) throw new Error("useApp ausserhalb von AppProvider")
  return value
}

export function AppProvider({ data, children }: { data: AppData; children: ReactNode }) {
  const [stored, setStored] = usePersistent<Partial<Assumptions>>("assumptions", {})
  const [professions, setProfessions] = usePersistent<Professions>("professions", {})
  const [watch, setWatch] = usePersistent<number[]>("watch", [])
  const [cart, setCart] = usePersistent<CartLine[]>("cart", [])
  const { route, navigate, back } = useRoute()

  // Aeltere gespeicherte Annahmen kennen neuere Felder nicht.
  const a = useMemo<Assumptions>(() => ({ ...DEFAULT_ASSUMPTIONS, ...stored }), [stored])
  const setA = useCallback(
    (patch: Partial<Assumptions>) => setStored((current) => ({ ...current, ...patch })),
    [setStored],
  )

  const toggleWatch = useCallback(
    (itemId: number) =>
      setWatch((current) =>
        current.includes(itemId) ? current.filter((id) => id !== itemId) : [...current, itemId],
      ),
    [setWatch],
  )
  const setCartQuantity = useCallback(
    (recipeId: number, quantity: number) =>
      setCart((current) => {
        const rest = current.filter((line) => line.recipeId !== recipeId)
        if (quantity <= 0) return rest
        return current.some((line) => line.recipeId === recipeId)
          ? current.map((line) => (line.recipeId === recipeId ? { recipeId, quantity } : line))
          : [...rest, { recipeId, quantity }]
      }),
    [setCart],
  )
  const clearCart = useCallback(() => setCart([]), [setCart])

  const trades = useMemo<Trades>(() => {
    const low: Plan[] = []
    const resets: Plan[] = []
    for (const row of data.rows.values()) {
      const tiers = data.ladder.get(row.item_id)
      if (!tiers) continue
      const cheap = lowBuy(row, tiers, a)
      if (cheap) low.push(cheap)
      const reset = bestReset(row, tiers, a)
      if (reset) resets.push(reset)
    }
    return { low, resets, portfolio: pickResets(resets, a) }
  }, [data, a])

  const go = useCallback(
    (page: Page) => navigate({ page, id: route.page === "item" ? null : route.id }),
    [navigate, route],
  )
  const select = useCallback(
    (itemId: number | null, replace = false) => {
      if (route.page === "item") {
        if (itemId != null) navigate({ page: "item", id: itemId })
      } else navigate({ page: route.page, id: itemId }, replace)
    },
    [navigate, route.page],
  )
  const open = useCallback((itemId: number) => navigate({ page: "item", id: itemId }), [navigate])
  const name = useCallback(
    (itemId: number) => data.names[String(itemId)] ?? `Item ${itemId}`,
    [data.names],
  )

  const value = useMemo<AppValue>(
    () => ({
      ...data,
      a,
      setA,
      professions,
      setProfessions,
      hasProfessions: Object.keys(professions).length > 0,
      watch,
      toggleWatch,
      cart,
      setCartQuantity,
      clearCart,
      trades,
      route,
      go,
      select,
      open,
      back,
      name,
    }),
    [data, a, setA, professions, setProfessions, watch, toggleWatch, cart, setCartQuantity, clearCart, trades, route, go, select, open, back, name],
  )
  return <Context.Provider value={value}>{children}</Context.Provider>
}
