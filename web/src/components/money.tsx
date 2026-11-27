import { formatInt, formatPercent, LOCALE, splitCoins } from "@/lib/format"

const NONE = <span className="text-muted-foreground">–</span>

/**
 * Ein Betrag in Kupfer. Zwei Einheiten genuegen zum Vergleichen: ab einem Gold
 * faellt das Kupfer weg, ab tausend Gold auch das Silber. Ohne Wert steht ein
 * Strich, keine Null. Ein Verlust bekommt ein Minus davor.
 *
 * `precise` zeigt immer alle Einheiten - in der Preisleiter unterscheiden sich
 * Angebote oft nur um ein paar Kupfer.
 */
export function Money({ value, precise }: { value: number | null | undefined; precise?: boolean }) {
  if (value == null || Number.isNaN(value)) return NONE
  const { gold, silver, copper } = splitCoins(Math.abs(value))
  if (precise) {
    return (
      <span className="whitespace-nowrap tabular-nums">
        {Math.round(value) < 0 && "−"}
        {gold > 0 && <span className="text-coin-gold">{gold.toLocaleString(LOCALE)}g </span>}
        {(gold > 0 || silver > 0) && <span className="text-coin-silver">{silver}s </span>}
        <span className="text-coin-copper">{copper}c</span>
      </span>
    )
  }
  return (
    <span className="whitespace-nowrap tabular-nums">
      {Math.round(value) < 0 && "−"}
      {gold > 0 && <span className="text-coin-gold">{gold.toLocaleString(LOCALE)}g</span>}
      {gold > 0 && gold < 1000 && <span className="text-coin-silver"> {silver}s</span>}
      {gold === 0 && silver > 0 && <span className="text-coin-silver">{silver}s </span>}
      {gold === 0 && <span className="text-coin-copper">{copper}c</span>}
    </span>
  )
}

/** Ein Betrag, gruen als Gewinn und rot als Verlust. */
export function Profit({ value }: { value: number | null | undefined }) {
  if (value == null) return NONE
  return (
    <span className={value > 0 ? "text-up" : value < 0 ? "text-down" : undefined}>
      <Money value={value} />
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

/** Ein Anteil als ganze Prozentzahl: 0.8 -> "80%". */
export function Share({ value }: { value: number | null | undefined }) {
  if (value == null) return NONE
  return <span className="tabular-nums">{Math.round(value * 100)}%</span>
}

export function Dash() {
  return NONE
}
