import { formatInt, formatPercent, splitCoins } from "@/lib/format"

const NONE = <span className="text-muted-foreground">–</span>

/** Ein Betrag in Kupfer als Gold, Silber, Kupfer. Ohne Wert steht ein Strich, keine Null. */
export function Money({ value }: { value: number | null | undefined }) {
  if (value == null) return NONE
  const { gold, silver, copper } = splitCoins(value)
  return (
    <span className="tabular-nums">
      {gold > 0 && <span className="text-coin-gold">{formatInt(gold)}g </span>}
      {(gold > 0 || silver > 0) && <span className="text-coin-silver">{silver}s </span>}
      <span className="text-coin-copper">{copper}c</span>
    </span>
  )
}

export function Count({ value }: { value: number | null | undefined }) {
  if (value == null) return NONE
  return <span className="tabular-nums">{formatInt(value)}</span>
}

export function Change({ value }: { value: number | null | undefined }) {
  if (value == null) return NONE
  const tone = value > 0 ? "text-up" : value < 0 ? "text-down" : "text-muted-foreground"
  return <span className={`tabular-nums ${tone}`}>{formatPercent(value)}</span>
}
