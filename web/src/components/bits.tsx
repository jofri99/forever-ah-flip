import type { ReactNode } from "react"
import { Minus, Plus, Star, Timer, TrendingDown, TrendingUp } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { formatDuration, formatInt, formatRatio } from "@/lib/format"
import { hasCooldown } from "@/lib/rows"
import { isDowntrend, isFalling, isSpiked } from "@/lib/trade"
import type { Basis } from "@/lib/trade"
import type { Craft, MarketRow } from "@/lib/types"

/** Eine Auswahl aus wenigen festen Werten, als Reihe von Knoepfen. */
export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  label,
}: {
  value: T
  options: readonly (readonly [T, string])[]
  onChange: (value: T) => void
  label: string
}) {
  return (
    <span role="group" aria-label={label} className="inline-flex overflow-hidden rounded-lg border bg-card">
      {options.map(([option, text]) => (
        <button
          key={String(option)}
          type="button"
          aria-pressed={option === value}
          onClick={() => onChange(option)}
          className={`border-l px-2.5 py-1 text-sm first:border-l-0 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring ${
            option === value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {text}
        </button>
      ))}
    </span>
  )
}

/** Ein Schalter mit seiner Beschriftung. */
export function Toggle({
  id,
  label,
  checked,
  onChange,
  disabled,
}: {
  id: string
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
}) {
  return (
    <span className="inline-flex items-center gap-2">
      <Switch id={id} checked={checked} onCheckedChange={onChange} disabled={disabled} />
      <Label htmlFor={id}>{label}</Label>
    </span>
  )
}

/** Eine Annahme mit ihrer Beschriftung davor, z. B. "Sell within [1 day][3 days]". */
export function Assume({ label, after, children }: { label: string; after?: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-sm whitespace-nowrap text-muted-foreground">
      {label}
      {children}
      {after}
    </span>
  )
}

/** Eine Kennzahl mit Beschriftung und optionaler Zeile darunter. */
export function Stat({ label, children, sub }: { label: string; children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="min-w-0 rounded-lg border bg-card px-3 py-2">
      <div className="truncate text-[11px] tracking-wide text-muted-foreground uppercase">{label}</div>
      <div className="truncate font-semibold">{children}</div>
      {sub && <div className="truncate text-xs text-muted-foreground">{sub}</div>}
    </div>
  )
}

export function Hint({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <p className={`text-xs text-muted-foreground ${className}`}>{children}</p>
}

const tag = "shrink-0 font-normal text-muted-foreground"
const warn = "shrink-0 border-current font-normal text-down"

export function CountBadge({ craft }: { craft: Pick<Craft, "item_count"> }) {
  if (craft.item_count === 1) return null
  return (
    <Badge variant="outline" className={tag}>
      ×{formatInt(craft.item_count)}
    </Badge>
  )
}

/** Kennzeichnet ein Rezept, das sich nur alle paar Stunden oder Tage wirken laesst. */
export function CooldownBadge({ craft }: { craft: Pick<Craft, "cooldown_seconds"> }) {
  if (!hasCooldown(craft) || craft.cooldown_seconds == null) return null
  const duration = formatDuration(craft.cooldown_seconds)
  return (
    <Badge variant="outline" className={tag} title={`Cooldown ${duration}: one craft, then wait`}>
      <Timer aria-hidden />
      <span className="sr-only">Cooldown </span>
      {duration}
    </Badge>
  )
}

/** Das guenstigste Angebot ist in 24 Stunden stark gestiegen: die Marge haelt vielleicht nicht. */
export function SpikeBadge({ row, basis }: { row: MarketRow | undefined; basis: Basis }) {
  if (!row || !isSpiked(row, basis) || row.change_24h_pct == null) return null
  const pct = Math.round(row.change_24h_pct)
  return (
    <Badge
      variant="outline"
      className={warn}
      title={`The lowest listing is up ${pct}% in 24h – this margin may not hold`}
    >
      <TrendingUp aria-hidden />
      {pct}%
    </Badge>
  )
}

/** Der Preis ist in 24 Stunden stark gefallen: der uebliche Preis gilt vielleicht nicht mehr. */
export function FallBadge({ row }: { row: MarketRow | undefined }) {
  if (!row || !isFalling(row) || row.change_24h_pct == null) return null
  const pct = Math.round(-row.change_24h_pct)
  return (
    <Badge
      variant="outline"
      className={warn}
      title={`The lowest listing fell ${pct}% in 24h – the usual price may no longer hold`}
    >
      <TrendingDown aria-hidden />
      {pct}%
    </Badge>
  )
}

/** Der Preis faellt seit Tagen gleichmaessig: ein Trend, kein Ausreisser nach unten. */
export function TrendBadge({ row }: { row: MarketRow | undefined }) {
  if (!row || !isDowntrend(row) || row.trend_pct_day == null) return null
  return (
    <Badge
      variant="outline"
      className={warn}
      title={`Falling about ${formatRatio(-row.trend_pct_day)}% a day across the whole history – a trend, not a dip. The usual price is likely out of date.`}
    >
      Downtrend
    </Badge>
  )
}

export function WarnBadge({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <Badge variant="outline" className={warn} title={title}>
      {children}
    </Badge>
  )
}

export function Tag({ children, solid, title }: { children: ReactNode; solid?: boolean; title?: string }) {
  return (
    <Badge variant={solid ? "secondary" : "outline"} className="shrink-0 font-normal" title={title}>
      {children}
    </Badge>
  )
}

/** Der Stern der Merkliste. */
export function StarButton({ active, onToggle }: { active: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={(event) => {
        event.stopPropagation()
        onToggle()
      }}
      title={active ? "Remove from watchlist" : "Add to watchlist"}
      aria-label={active ? "Remove from watchlist" : "Add to watchlist"}
      aria-pressed={active}
      className={`inline-flex rounded-md p-1.5 hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring ${
        active ? "text-price" : "text-muted-foreground"
      }`}
    >
      <Star className="size-4" fill={active ? "currentColor" : "none"} aria-hidden />
    </button>
  )
}

/**
 * Der Kauf-Score: 0 bis 100 mit einem Balken, damit sich eine Spalte auf einen Blick
 * lesen laesst. `bare` zeigt nur den Balken. Ohne Wert steht ein Strich.
 */
export function ScoreMeter({ value, wide, bare }: { value: number | null | undefined; wide?: boolean; bare?: boolean }) {
  if (value == null) return <span className="text-muted-foreground">–</span>
  return (
    <span className="inline-flex items-center gap-1.5 tabular-nums" title={`Buy score ${value} of 100`}>
      <span className={`h-1.5 ${wide ? "w-24" : "w-8"} overflow-hidden rounded-full bg-border`} aria-hidden>
        <span className="block h-full rounded-full bg-(--viz)" style={{ width: `${value}%` }} />
      </span>
      {!bare && <span className="w-6 text-right">{value}</span>}
    </span>
  )
}

/** Eine Menge mit Minus und Plus. `small` passt in eine Tabellenzeile; mit `min` 0 entfernt das Minus die Zeile. */
export function Stepper({
  value,
  onChange,
  min = 1,
  small,
}: {
  value: number
  onChange: (value: number) => void
  min?: number
  small?: boolean
}) {
  const button = `grid ${small ? "size-7" : "size-8"} place-items-center hover:bg-muted`
  return (
    <span className="inline-flex items-center overflow-hidden rounded-lg border">
      <button type="button" aria-label="Fewer" onClick={() => onChange(Math.max(min, value - 1))} className={button}>
        <Minus className="size-3.5" aria-hidden />
      </button>
      <input
        value={value}
        inputMode="numeric"
        aria-label="Quantity"
        onChange={(event) => onChange(Math.max(1, parseInt(event.target.value, 10) || 1))}
        className={`${small ? "h-7 w-10" : "h-8 w-11"} border-x bg-transparent text-center text-sm outline-none`}
      />
      <button type="button" aria-label="More" onClick={() => onChange(value + 1)} className={button}>
        <Plus className="size-3.5" aria-hidden />
      </button>
    </span>
  )
}

/** Eine Farbprobe fuer die Legende eines Diagramms. Ohne Farbe: ein leerer Rahmen. */
export function Swatch({ color }: { color?: string }) {
  return (
    <i
      className={`mr-1 inline-block h-2.5 w-3.5 rounded-xs align-[-1px] ${color ? "" : "shadow-[inset_0_0_0_1px_var(--border)]"}`}
      style={color ? { background: color } : undefined}
    />
  )
}

/** Der Name eines Items mit Marken dahinter. Der Name darf gekuerzt werden, die Marken nicht. */
export function NameCell({ name, children }: { name: string; children?: ReactNode }) {
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <span className="truncate">{name}</span>
      {children}
    </span>
  )
}
