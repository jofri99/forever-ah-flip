import { useEffect, useRef } from "react"
import {
  createChart,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
} from "lightweight-charts"
import type { IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts"

import { moneyShort, toLocalChartTime } from "@/lib/format"
import type { SeriesPoint } from "@/lib/types"

let probe: CanvasRenderingContext2D | null = null

/**
 * Die Farben des Themes stehen als oklch() in CSS-Variablen. Die Diagramm-
 * Bibliothek versteht das nicht sicher, ein Canvas schon - es rechnet in RGB um.
 */
function themeColor(variable: string): string {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(variable).trim()
  probe ??= document.createElement("canvas").getContext("2d", { willReadFrequently: true })
  if (!probe) return raw
  probe.clearRect(0, 0, 1, 1)
  probe.fillStyle = raw
  probe.fillRect(0, 0, 1, 1)
  const [r, g, b, a] = probe.getImageData(0, 0, 1, 1).data
  return a === 255 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${(a / 255).toFixed(3)})`
}

function themeOptions() {
  const border = themeColor("--border")
  return {
    layout: {
      background: { color: themeColor("--card") },
      textColor: themeColor("--muted-foreground"),
      fontFamily: getComputedStyle(document.body).fontFamily,
      panes: { separatorColor: border },
    },
    grid: { vertLines: { color: border }, horzLines: { color: border } },
    rightPriceScale: { borderColor: border },
    timeScale: { borderColor: border, timeVisible: true, secondsVisible: false },
  }
}

interface ChartParts {
  chart: IChartApi
  min: ISeriesApi<"Line">
  median: ISeriesApi<"Line">
  bars: ISeriesApi<"Histogram">
}

const chartTime = (ts: number) => toLocalChartTime(ts) as UTCTimestamp

/**
 * Oben guenstigster Preis und Median, darunter Balken: die verkaufte Menge je
 * Stand, oder die Zahl der Angebote, solange es keine Verkaufsdaten gibt.
 */
export function PriceChart({ series }: { series: SeriesPoint[] }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const partsRef = useRef<ChartParts | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const priceFormat = { type: "custom" as const, minMove: 1, formatter: moneyShort }
    const chart = createChart(container, {
      autoSize: true,
      ...themeOptions(),
      localization: { locale: "de-DE" },
      crosshair: { mode: CrosshairMode.Normal },
    })
    const min = chart.addSeries(LineSeries, {
      color: themeColor("--price"),
      lineWidth: 2,
      priceFormat,
    })
    const median = chart.addSeries(LineSeries, {
      color: themeColor("--muted-foreground"),
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      priceFormat,
    })
    const bars = chart.addSeries(
      HistogramSeries,
      { color: themeColor("--bars"), priceFormat: { type: "volume" } },
      1,
    )
    chart.panes()[1]?.setHeight(110)
    partsRef.current = { chart, min, median, bars }

    // Wechselt das Theme, zieht das Diagramm die Farben nach.
    const observer = new MutationObserver(() => {
      chart.applyOptions(themeOptions())
      min.applyOptions({ color: themeColor("--price") })
      median.applyOptions({ color: themeColor("--muted-foreground") })
      bars.applyOptions({ color: themeColor("--bars") })
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] })

    return () => {
      observer.disconnect()
      chart.remove()
      partsRef.current = null
    }
  }, [])

  useEffect(() => {
    const parts = partsRef.current
    if (!parts) return
    const { chart, min, median, bars } = parts

    // Bei wenigen Staenden einzelne Punkte zeigen, sonst sieht man zwei Werte kaum.
    min.applyOptions({ pointMarkersVisible: series.length < 30 })
    min.setData(
      series
        .filter((point) => point.min_price != null)
        .map((point) => ({ time: chartTime(point.ts), value: point.min_price as number })),
    )
    median.setData(
      series
        .filter((point) => point.median_price != null)
        .map((point) => ({ time: chartTime(point.ts), value: point.median_price as number })),
    )

    const sold = series.filter((point) => point.qty_sold != null)
    bars.setData(
      sold.length
        ? sold.map((point) => ({ time: chartTime(point.ts), value: point.qty_sold as number }))
        : series.map((point) => ({ time: chartTime(point.ts), value: point.n_listings })),
    )
    chart.timeScale().fitContent()
  }, [series])

  return <div ref={containerRef} className="h-[400px] w-full" />
}
