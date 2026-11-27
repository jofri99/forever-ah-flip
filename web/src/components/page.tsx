import type { ReactNode } from "react"

import { Input } from "@/components/ui/input"
import { formatInt } from "@/lib/format"

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header className="mb-3.5">
      <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
      {children && <p className="mt-0.5 max-w-[78ch] text-sm text-muted-foreground">{children}</p>}
    </header>
  )
}

/** Die Zeile mit Suche, Auswahl und Schaltern ueber einer Tabelle. */
export function FilterBar({ children }: { children: ReactNode }) {
  return <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">{children}</div>
}

export function SearchInput({
  value,
  onChange,
  placeholder,
}: {
  value: string
  onChange: (value: string) => void
  placeholder: string
}) {
  return (
    <Input
      type="search"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      aria-label={placeholder}
      className="w-56"
    />
  )
}

export function CountNote({ count, noun }: { count: number; noun: string }) {
  return (
    <span className="ml-auto text-sm text-muted-foreground">
      {formatInt(count)} {noun}
      {count === 1 ? "" : "s"}
    </span>
  )
}

/** Eine Karte mit Kopfzeile, wie auf der Startseite und der Item-Seite. */
export function Panel({
  title,
  count,
  action,
  sub,
  children,
  padded,
}: {
  title: string
  count?: number
  action?: ReactNode
  sub?: ReactNode
  children: ReactNode
  padded?: boolean
}) {
  return (
    <section className="overflow-hidden rounded-xl border bg-card">
      <div className="flex items-baseline gap-2 px-3.5 pt-3 pb-1">
        <h2 className="text-sm font-semibold">{title}</h2>
        {count != null && <span className="text-xs text-muted-foreground">{formatInt(count)}</span>}
        {action && <span className="ml-auto text-xs">{action}</span>}
      </div>
      {sub && <p className="px-3.5 pb-2 text-xs text-muted-foreground">{sub}</p>}
      <div className={padded ? "px-3.5 pt-1 pb-3.5" : ""}>{children}</div>
    </section>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="border-t px-3.5 py-5 text-center text-sm text-muted-foreground">{children}</div>
}

export function LinkButton({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" onClick={onClick} className="text-muted-foreground hover:text-foreground hover:underline">
      {children}
    </button>
  )
}
