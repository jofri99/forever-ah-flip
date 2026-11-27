import { lazy, Suspense } from "react"

import { Skeleton } from "@/components/ui/skeleton"
import type { SeriesPoint } from "@/lib/types"

// Die Diagramm-Bibliothek ist der groesste Brocken der Seite. Sie wird erst geholt,
// wenn jemand ein Item oeffnet - die Listen stehen damit, bevor sie angefragt wurde.
const PriceChart = lazy(() =>
  import("@/components/price-chart").then((module) => ({ default: module.PriceChart })),
)

interface LazyChartProps {
  series: SeriesPoint[]
  height: number
  usual: number | null
  loading: boolean
  /** Zeitpunkte erkannter Resets, als Marken im Verlauf. */
  marks?: readonly number[]
}

export function LazyChart({ series, height, usual, loading, marks }: LazyChartProps) {
  return (
    <div className="relative" style={{ height }}>
      <Suspense fallback={<Skeleton className="absolute inset-0" />}>
        <PriceChart series={series} height={height} usual={usual} marks={marks} />
      </Suspense>
      {loading && <Skeleton className="absolute inset-0" />}
    </div>
  )
}
