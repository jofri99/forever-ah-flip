import { useCallback, useEffect, useState } from "react"

export const PAGES = [
  "opportunities",
  "crafting",
  "flips",
  "low",
  "reset",
  "market",
  "watchlist",
  "shopping",
  "item",
] as const

export type Page = (typeof PAGES)[number]

/**
 * Wo man ist. Auf den Listenseiten ist `id` das Item in der Seitenleiste, auf
 * der Seite "item" das Item, dem die ganze Seite gehoert.
 */
export interface Route {
  page: Page
  id: number | null
}

export const HOME: Route = { page: "opportunities", id: null }

/** Liest die Adresse: #crafting, #crafting/3826, #item/3826 - und die alte Form #3826:commodity. */
export function parseHash(hash: string): Route {
  const text = decodeURIComponent(hash.replace(/^#/, ""))
  const legacy = /^(\d+):(auction|commodity)$/.exec(text)
  if (legacy) return { page: "market", id: Number(legacy[1]) }
  const [page, id] = text.split("/")
  if (!(PAGES as readonly string[]).includes(page)) return HOME
  const item = id != null && /^\d+$/.test(id) ? Number(id) : null
  if (page === "item" && item == null) return HOME
  return { page: page as Page, id: item }
}

export function toHash(route: Route): string {
  return `#${route.page}${route.id != null ? `/${route.id}` : ""}`
}

/**
 * Seite und Item stehen in der Adresse. So laesst sich jede Ansicht verlinken,
 * und Vor und Zurueck im Browser tun, was man erwartet.
 */
export function useRoute() {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash))

  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash))
    window.addEventListener("hashchange", onChange)
    window.addEventListener("popstate", onChange)
    return () => {
      window.removeEventListener("hashchange", onChange)
      window.removeEventListener("popstate", onChange)
    }
  }, [])

  /** `replace` ersetzt den Eintrag, statt einen neuen anzulegen - fuers Blaettern mit den Pfeiltasten. */
  const navigate = useCallback((next: Route, replace = false) => {
    const hash = toHash(next)
    if (hash !== window.location.hash) {
      if (replace) window.history.replaceState(window.history.state, "", hash)
      else window.history.pushState({ fah: true }, "", hash)
    }
    setRoute(next)
  }, [])

  /** Zurueck, wenn es ein Zurueck innerhalb der App gibt - sonst zur Startseite. */
  const back = useCallback(() => {
    if ((window.history.state as { fah?: boolean } | null)?.fah) window.history.back()
    else navigate(HOME)
  }, [navigate])

  return { route, navigate, back }
}
