import { useMemo, useState } from "react"

import { Tag } from "@/components/bits"
import { Money } from "@/components/money"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { useApp } from "@/lib/app"
import type { AppValue } from "@/lib/app"
import type { Professions } from "@/lib/types"

const MAX_RESULTS = 10

/** Sucht in allen bekannten Namen: genauer Treffer vor Anfang vor irgendwo, dann nach Absatz. */
function search(app: AppValue, query: string): number[] {
  const needle = query.trim().toLowerCase()
  if (!needle) return app.watch.slice(0, 8)
  const hits: [rank: number, sold: number, itemId: number][] = []
  for (const [id, name] of Object.entries(app.names)) {
    const text = name.toLowerCase()
    const rank = text === needle || id === needle ? 0 : text.startsWith(needle) ? 1 : text.includes(needle) ? 2 : -1
    if (rank >= 0) hits.push([rank, app.rows.get(Number(id))?.qty_sold_24h ?? 0, Number(id)])
  }
  return hits
    .sort((x, y) => x[0] - y[0] || y[1] - x[1])
    .slice(0, MAX_RESULTS)
    .map((hit) => hit[2])
}

/** Die Suche ueber alles (Strg+K): Enter oeffnet das Item in der Seitenleiste, Umschalt+Enter seine Vollseite. */
export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-describedby={undefined}>
        <DialogTitle className="sr-only">Search items and recipes</DialogTitle>
        {/* Der Inhalt wird bei jedem Oeffnen neu eingehaengt und beginnt leer. */}
        <PaletteBody close={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}

function PaletteBody({ close }: { close: () => void }) {
  const app = useApp()
  const [query, setQuery] = useState("")
  const [active, setActive] = useState(0)
  const results = useMemo(() => search(app, query), [app, query])

  const pick = (itemId: number, full: boolean) => {
    close()
    if (full) app.open(itemId)
    else app.select(itemId)
  }

  return (
    <>
      <input
        autoFocus
        value={query}
        onChange={(event) => {
          setQuery(event.target.value)
          setActive(0)
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") setActive((index) => Math.min(results.length - 1, index + 1))
          else if (event.key === "ArrowUp") setActive((index) => Math.max(0, index - 1))
          else if (event.key === "Enter" && results[active] != null) pick(results[active], event.shiftKey)
          else return
          event.preventDefault()
        }}
        placeholder="Search items and recipes…"
        aria-label="Search items and recipes"
        autoComplete="off"
        className="border-b bg-transparent px-4 py-3.5 text-[15px] outline-none placeholder:text-muted-foreground"
      />
      <div className="overflow-auto">
        {results.map((itemId, index) => {
          const row = app.rows.get(itemId)
          return (
            <button
              key={itemId}
              type="button"
              onClick={(event) => pick(itemId, event.shiftKey)}
              onPointerMove={() => setActive(index)}
              className={`flex w-full items-center gap-2.5 px-4 py-2 text-left text-sm ${index === active ? "bg-muted" : ""}`}
            >
              <span className="truncate">{app.name(itemId)}</span>
              {app.craftsByItem.has(itemId) && <Tag>Craftable</Tag>}
              <span className="ml-auto text-muted-foreground">
                {row?.min_price != null ? <Money value={row.min_price} /> : "not listed"}
              </span>
            </button>
          )
        })}
        {results.length === 0 && (
          <p className="px-4 py-6 text-center text-sm text-muted-foreground">
            {query ? "No item with that name." : "Type a name. Your starred items show up here."}
          </p>
        )}
      </div>
      <p className="border-t px-4 py-2 text-xs text-muted-foreground">
        Enter opens the item beside the list · Shift+Enter opens its full page
      </p>
    </>
  )
}

/** Welche Berufe der Nutzer hat und wie weit: danach richten sich Crafting und Opportunities. */
export function ProfessionsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <div className="px-4 pt-4 pb-1">
          <DialogTitle>My professions</DialogTitle>
          <DialogDescription className="mt-1">
            Tick what your characters can do and how far. Recipes beyond that are greyed out, and Opportunities
            can be limited to them.
          </DialogDescription>
        </div>
        <ProfessionsForm close={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}

function ProfessionsForm({ close }: { close: () => void }) {
  const app = useApp()
  const names = useMemo(() => [...new Set(app.crafts.map((craft) => craft.profession))].sort(), [app.crafts])
  const [draft, setDraft] = useState<Professions>(app.professions)
  // Der Skill bleibt stehen, auch wenn der Haken kurz weg ist.
  const [skills, setSkills] = useState<Professions>(app.professions)

  return (
    <>
      <div className="overflow-auto px-4 py-2">
        {names.map((name) => {
          const checked = draft[name] != null
          const skill = skills[name] ?? 300
          return (
            <label key={name} className="grid grid-cols-[auto_1fr_5rem] items-center gap-2.5 border-t py-1.5 text-sm first:border-t-0">
              <input
                type="checkbox"
                checked={checked}
                onChange={(event) =>
                  setDraft((current) => {
                    const next = { ...current }
                    if (event.target.checked) next[name] = skill
                    else delete next[name]
                    return next
                  })
                }
                className="size-4 accent-primary"
              />
              <span>{name}</span>
              <input
                type="number"
                min={1}
                max={300}
                value={skill}
                aria-label={`${name} skill`}
                onChange={(event) => {
                  const value = Math.min(300, Math.max(1, Number(event.target.value) || 1))
                  setSkills((current) => ({ ...current, [name]: value }))
                  setDraft((current) => (current[name] != null ? { ...current, [name]: value } : current))
                }}
                className="h-7 rounded-md border bg-transparent px-2 text-right tabular-nums"
              />
            </label>
          )
        })}
      </div>
      <div className="flex justify-end gap-2 border-t px-4 py-2.5">
        <Button variant="outline" onClick={close}>
          Cancel
        </Button>
        <Button
          onClick={() => {
            app.setProfessions(draft)
            close()
          }}
        >
          Save
        </Button>
      </div>
    </>
  )
}
