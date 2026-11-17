import type { Kind } from "./types"

// Englische Schreibweise, aber 24-Stunden-Zeit und Tag vor Monat.
export const LOCALE = "en-GB"

export interface Coins {
  gold: number
  silver: number
  copper: number
}

/** Kupfer in Gold, Silber, Kupfer zerlegen. 10.000 Kupfer sind ein Gold. */
export function splitCoins(copper: number): Coins {
  const total = Math.round(copper)
  return {
    gold: Math.floor(total / 10_000),
    silver: Math.floor((total % 10_000) / 100),
    copper: total % 100,
  }
}

/** Kurzform fuer die Achse des Diagramms: "20.49s", "1.5g", "24c". */
export function moneyShort(copper: number): string {
  const total = Math.round(copper)
  const compact = (value: number) =>
    value.toLocaleString(LOCALE, { maximumFractionDigits: 2 })
  if (Math.abs(total) >= 10_000) return `${compact(total / 10_000)}g`
  if (Math.abs(total) >= 100) return `${compact(total / 100)}s`
  return `${total}c`
}

export function formatInt(value: number): string {
  return Math.round(value).toLocaleString(LOCALE)
}

export function formatPercent(value: number): string {
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toLocaleString(LOCALE, { maximumFractionDigits: 1 })}%`
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(LOCALE, {
    dateStyle: "medium",
    timeStyle: "short",
  })
}

export function kindLabel(kind: Kind): string {
  return kind === "commodity" ? "Commodity" : "Single item"
}

/**
 * Das Diagramm rechnet in UTC. Fuer die Anzeige in Ortszeit wird jeder Zeitpunkt
 * um den Abstand zur UTC verschoben - der Weg, den die Doku der Bibliothek nennt.
 */
export function toLocalChartTime(utcSeconds: number): number {
  return utcSeconds - new Date(utcSeconds * 1000).getTimezoneOffset() * 60
}
