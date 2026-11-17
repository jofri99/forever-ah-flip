import {
  asyncBufferFromUrl,
  cachedAsyncBuffer,
  parquetMetadataAsync,
  parquetReadObjects,
} from "hyparquet"
import type { AsyncBuffer, FileMetaData } from "hyparquet"

import type { Kind, MarketRow, Meta, Names, SeriesPoint, VendorFlip } from "./types"

const DATA_URL = `${import.meta.env.BASE_URL}data/`

const SERIES_COLUMNS = [
  "item_id",
  "kind",
  "ts",
  "min_price",
  "median_price",
  "n_listings",
  "qty_sold",
]

/** Eine Zeilengruppe von hourly.parquet: welche Zeilen, welche Item-IDs. */
export interface RowGroupSpan {
  start: number
  end: number
  minItem: number
  maxItem: number
}

/**
 * Liest aus dem Verzeichnis am Dateiende, welche Zeilengruppe welche Item-IDs
 * enthaelt. Die Datei ist nach Item sortiert, also sind die Bereiche aufsteigend.
 */
export function buildGroupIndex(metadata: FileMetaData): RowGroupSpan[] {
  let start = 0
  return metadata.row_groups.map((group) => {
    const rows = Number(group.num_rows)
    const column = group.columns.find(
      (chunk) => chunk.meta_data?.path_in_schema[0] === "item_id",
    )
    const stats = column?.meta_data?.statistics
    if (stats?.min_value == null || stats?.max_value == null) {
      throw new Error("hourly.parquet hat keine Statistik fuer item_id")
    }
    const span: RowGroupSpan = {
      start,
      end: start + rows,
      minItem: Number(stats.min_value),
      maxItem: Number(stats.max_value),
    }
    start += rows
    return span
  })
}

/** Die Gruppen, in denen ein Item liegen kann - meist eine, an einer Gruppengrenze zwei. */
export function spansFor(itemId: number, groups: RowGroupSpan[]): RowGroupSpan[] {
  return groups.filter((group) => itemId >= group.minItem && itemId <= group.maxItem)
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(DATA_URL + path, { cache: "no-cache" })
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`)
  return (await response.json()) as T
}

/** Jeder Build bekommt eigene Adressen, damit nie Teile zweier Staende gemischt werden. */
function versioned(file: string, meta: Meta): string {
  return `${DATA_URL}${file}?v=${encodeURIComponent(meta.built_at)}`
}

export function loadMeta(): Promise<Meta> {
  return getJson<Meta>("meta.json")
}

export async function loadMarket(meta: Meta): Promise<MarketRow[]> {
  const response = await fetch(versioned("market.parquet", meta))
  if (!response.ok) throw new Error(`market.parquet: HTTP ${response.status}`)
  const rows = await parquetReadObjects({ file: await response.arrayBuffer() })
  return rows as MarketRow[]
}

/**
 * Haendler-Flips gibt es nur, wenn lokal ein Abzug der Haendler vorliegt.
 * meta.json nennt dann ihre Zahl; sonst kommt eine leere Liste zurueck.
 */
export async function loadVendorFlips(meta: Meta): Promise<VendorFlip[]> {
  if (meta.vendor_flips == null) return []
  const response = await fetch(versioned("vendor_flips.parquet", meta))
  if (!response.ok) return []
  const rows = await parquetReadObjects({ file: await response.arrayBuffer() })
  return rows as VendorFlip[]
}

/** Namen sind optional. meta.json sagt, ob es die Datei gibt. */
export async function loadNames(meta: Meta): Promise<Names> {
  if (!meta.names) return {}
  try {
    return await getJson<Names>("names.json")
  } catch {
    return {}
  }
}

interface Hourly {
  file: AsyncBuffer
  metadata: FileMetaData
  groups: RowGroupSpan[]
}

let hourly: { version: string; promise: Promise<Hourly> } | null = null

/** Oeffnet hourly.parquet einmal je Build und merkt sich das Verzeichnis. */
function openHourly(meta: Meta): Promise<Hourly> {
  if (hourly?.version !== meta.built_at) {
    const promise = (async () => {
      const file = cachedAsyncBuffer(
        await asyncBufferFromUrl({ url: versioned("hourly.parquet", meta) }),
      )
      const metadata = await parquetMetadataAsync(file)
      return { file, metadata, groups: buildGroupIndex(metadata) }
    })()
    // Schlaegt das Oeffnen fehl, soll der naechste Versuch neu beginnen.
    promise.catch(() => {
      if (hourly?.promise === promise) hourly = null
    })
    hourly = { version: meta.built_at, promise }
  }
  return hourly.promise
}

/**
 * Der Verlauf eines Items. Gelesen werden nur die Zeilengruppen, in deren
 * Bereich die ID faellt, und von denen nur die Spalten des Diagramms.
 */
export async function loadSeries(
  meta: Meta,
  itemId: number,
  kind: Kind,
): Promise<SeriesPoint[]> {
  const { file, metadata, groups } = await openHourly(meta)
  const series: SeriesPoint[] = []

  for (const group of spansFor(itemId, groups)) {
    const rows = (await parquetReadObjects({
      file,
      metadata,
      columns: SERIES_COLUMNS,
      rowStart: group.start,
      rowEnd: group.end,
    })) as SeriesPoint[]
    for (const row of rows) {
      if (row.item_id === itemId && row.kind === kind) series.push(row)
    }
  }
  return series.sort((a, b) => a.ts - b.ts)
}
