import { useEffect, useState } from "react"

import { useApp } from "./app"
import { loadSeries } from "./data"
import type { MarketRow, SeriesPoint } from "./types"

export type SeriesState =
  | { status: "loading"; series: SeriesPoint[] }
  | { status: "ready"; series: SeriesPoint[] }
  | { status: "error"; series: SeriesPoint[]; message: string }

/**
 * Der Verlauf eines Items. Wer ihn benutzt, wird je Item neu eingehaengt (key) -
 * darum beginnt der Zustand immer bei "loading".
 */
export function useSeries(row: MarketRow | undefined): SeriesState {
  const { meta } = useApp()
  const [state, setState] = useState<SeriesState>({ status: "loading", series: [] })
  const itemId = row?.item_id
  const kind = row?.kind

  useEffect(() => {
    if (itemId == null || kind == null) return
    let cancelled = false
    loadSeries(meta, itemId, kind)
      .then((series) => {
        if (!cancelled) setState({ status: "ready", series })
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({ status: "error", series: [], message: error instanceof Error ? error.message : String(error) })
        }
      })
    // Wird inzwischen ein anderes Item gewaehlt, darf die alte Antwort nichts mehr setzen.
    return () => {
      cancelled = true
    }
  }, [meta, itemId, kind])

  return state
}
