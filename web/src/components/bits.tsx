import type { ReactNode } from "react"
import { Star, Timer, TrendingDown, TrendingUp } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { formatDuration, formatInt } from "@/lib/format"
import { hasCooldown } from "@/lib/rows"
import { isFalling, isSpiked } from "@/lib/trade"
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

/** Der Name eines Items mit Marken dahinter. Der Name darf gekuerzt werden, die Marken nicht. */
export function NameCell({ name, children }: { name: string; children?: ReactNode }) {
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <span className="truncate">{name}</span>
      {children}
    </span>
  )
}
