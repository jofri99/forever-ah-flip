import { useCallback, useEffect, useState } from "react"

function readHash(): string | null {
  const value = decodeURIComponent(window.location.hash.slice(1))
  return value || null
}

/**
 * Das gewaehlte Item steht in der Adresse (#12359:commodity). So laesst sich ein
 * Verlauf verlinken, und Vor/Zurueck im Browser tun, was man erwartet.
 */
export function useHashSelection(): [string | null, (key: string | null) => void] {
  const [selected, setSelected] = useState<string | null>(readHash)

  useEffect(() => {
    const onHashChange = () => setSelected(readHash())
    window.addEventListener("hashchange", onHashChange)
    return () => window.removeEventListener("hashchange", onHashChange)
  }, [])

  const select = useCallback((key: string | null) => {
    const url = key
      ? `#${key}`
      : window.location.pathname + window.location.search
    window.history.pushState(null, "", url)
    setSelected(key)
  }, [])

  return [selected, select]
}
