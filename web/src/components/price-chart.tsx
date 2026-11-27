import { useEffect, useMemo, useRef } from "react"
import {
  createChart,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  PriceScaleMode,
} from "lightweight-charts"
import type { IChartApi, IPriceLine, ISeriesApi, UTCTimestamp } from "lightweight-charts"

import { LOCALE, moneyShort, toLocalChartTime } from "@/lib/format"
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

/** Ab dieser Spanne zwischen tiefstem und hoechstem Preis wird die Achse logarithmisch. */
const LOG_FROM = 8

/**
 * Ein einzelner Ausschlag - etwa der Preis am ersten Tag eines neuen Items - drueckt auf
 * einer linearen Achse alles andere an den unteren Rand. Logarithmisch bleibt beides lesbar.
 */
function needsLogScale(series: readonly SeriesPoint[]): boolean {
  let low = Infinity
  let high = 0
  for (const point of series) {
    for (const price of [point.min_price, point.median_price]) {
      if (price != null && price > 0) {
        low = Math.min(low, price)
        high = Math.max(high, price)
      }
    }
  }
  return high / low >= LOG_FROM
}

interface PriceChartProps {
  series: SeriesPoint[]
  /** Hoehe in Pixeln: in der Seitenleiste klein, auf der Vollseite gross. */
  height?: number
  /** Der uebliche Preis als gestrichelte Linie quer durchs Diagramm. */
  usual?: number | null
}

/**
 * Oben guenstigster Preis und Median, darunter Balken: die verkaufte Menge je
 * Stand, oder die Zahl der Angebote, solange es keine Verkaufsdaten gibt.
 */
export function PriceChart({ series, height = 400, usual = null }: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const partsRef = useRef<ChartParts | null>(null)
  const usualRef = useRef<IPriceLine | null>(null)
  const log = useMemo(() => needsLogScale(series), [series])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const priceFormat = { type: "custom" as const, minMove: 1, formatter: moneyShort }
    const chart = createChart(container, {
      autoSize: true,
      ...themeOptions(),
      localization: { locale: LOCALE },
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
    chart.panes()[1]?.setHeight(height < 300 ? 60 : 110)
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
      usualRef.current = null
    }
    // Die Hoehe steht beim Einhaengen fest; das Diagramm wird je Item neu angelegt.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    min.priceScale().applyOptions({ mode: log ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal })
    chart.timeScale().fitContent()
  }, [series, log])

  useEffect(() => {
    const min = partsRef.current?.min
    if (!min) return
    if (usualRef.current) min.removePriceLine(usualRef.current)
    usualRef.current =
      usual == null
        ? null
        : min.createPriceLine({
            price: usual,
            color: themeColor("--muted-foreground"),
            lineWidth: 1,
            lineStyle: LineStyle.LargeDashed,
            axisLabelVisible: true,
            title: "usual",
          })
  }, [usual])

  return (
    <div className="relative w-full" style={{ height }}>
      <div ref={containerRef} className="size-full" />
      {log && (
        <span
          className="pointer-events-none absolute top-1 left-1 z-10 rounded bg-card/80 px-1 text-[10px] text-muted-foreground"
          title="The prices span a wide range, so the axis is logarithmic: equal distances are equal ratios"
        >
          log scale
        </span>
      )}
    </div>
  )
}
