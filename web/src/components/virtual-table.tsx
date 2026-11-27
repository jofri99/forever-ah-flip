import { useEffect, useRef } from "react"
import type { ReactNode } from "react"
import { useVirtualizer } from "@tanstack/react-virtual"
import { ArrowDown, ArrowUp } from "lucide-react"

import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

/** Feste Zeilenhoehe: nur so weiss die Liste ohne Messen, wo welche Zeile liegt. */
const ROW_HEIGHT = 37

export interface Column<T, K extends string = string> {
  key: K
  label: string
  numeric: boolean
  /** Ohne Breite nimmt die Spalte den Rest. */
  width?: number
  cell: (row: T) => ReactNode
}

interface VirtualTableProps<T, K extends string> {
  rows: T[]
  columns: Column<T, K>[]
  /** Was ein Klick auswaehlt. Mehrere Zeilen duerfen dasselbe auswaehlen. */
  getKey: (row: T) => string
  /** Eindeutig je Zeile, wo `getKey` es nicht ist - etwa zwei Rezepte fuer dasselbe Item. */
  getRowId?: (row: T) => string
  sort: { key: K; dir: 1 | -1 }
  selectedKey: string | null
  onSort: (key: K) => void
  /** `byKeyboard` sagt, dass mit den Pfeiltasten geblaettert wird. */
  onSelect: (key: string, byKeyboard: boolean) => void
  /** Doppelklick oder Enter auf der gewaehlten Zeile. */
  onOpen?: (key: string) => void
  /** Zeilen, die blasser erscheinen sollen. */
  isDim?: (row: T) => boolean
  /** Unter dieser Breite scrollt die Tabelle waagerecht, statt Spalten zu quetschen. */
  minWidth: number
  emptyText: string
}

/**
 * Eine sortierbare Tabelle, von deren Zeilen immer nur die sichtbaren im Dokument
 * stehen. Was in den Spalten steht, bestimmt der Aufrufer.
 */
export function VirtualTable<T, K extends string>({
  rows,
  columns,
  getKey,
  getRowId,
  sort,
  selectedKey,
  onSort,
  onSelect,
  onOpen,
  isDim,
  minWidth,
  emptyText,
}: VirtualTableProps<T, K>) {
  const scrollRef = useRef<HTMLDivElement>(null)

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  })

  // Neue Sortierung oder neuer Filter: wieder oben anfangen.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 })
  }, [rows])

  /** Mit den Pfeiltasten zur naechsten Zeile: auswaehlen, in Sicht holen, Fokus mitnehmen. */
  const step = (from: number, delta: number) => {
    const next = Math.min(rows.length - 1, Math.max(0, from + delta))
    if (next === from) return
    onSelect(getKey(rows[next]), true)
    virtualizer.scrollToIndex(next)
    requestAnimationFrame(() => {
      scrollRef.current?.querySelector<HTMLElement>(`[data-index="${next}"]`)?.focus()
    })
  }

  const items = virtualizer.getVirtualItems()
  const paddingTop = items.length ? items[0].start : 0
  const paddingBottom = items.length ? virtualizer.getTotalSize() - items[items.length - 1].end : 0

  return (
    <div ref={scrollRef} className="max-h-[70vh] overflow-auto rounded-lg border bg-card">
      <table className="w-full table-fixed caption-bottom text-sm" style={{ minWidth }}>
        <colgroup>
          {columns.map((column) => (
            <col key={column.key} style={column.width ? { width: column.width } : undefined} />
          ))}
        </colgroup>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {columns.map((column) => {
              const active = sort.key === column.key
              const Arrow = sort.dir === 1 ? ArrowUp : ArrowDown
              return (
                <TableHead
                  key={column.key}
                  aria-sort={active ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
                  className={`sticky top-0 z-10 bg-card px-3 shadow-[inset_0_-1px_0_var(--border)] ${column.numeric ? "text-right" : ""}`}
                >
                  <button
                    type="button"
                    onClick={() => onSort(column.key)}
                    className={`inline-flex items-center gap-1 text-xs tracking-wide uppercase hover:text-foreground ${active ? "text-foreground" : "text-muted-foreground"}`}
                  >
                    {column.label}
                    {active && <Arrow className="size-3" aria-hidden />}
                  </button>
                </TableHead>
              )
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {paddingTop > 0 && (
            <tr aria-hidden style={{ height: paddingTop }}>
              <td colSpan={columns.length} />
            </tr>
          )}
          {items.map((item) => {
            const row = rows[item.index]
            const key = getKey(row)
            return (
              <TableRow
                key={getRowId ? getRowId(row) : key}
                data-index={item.index}
                data-state={key === selectedKey ? "selected" : undefined}
                tabIndex={0}
                onClick={() => onSelect(key, false)}
                onDoubleClick={() => onOpen?.(key)}
                onKeyDown={(event) => {
                  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                    event.preventDefault()
                    step(item.index, event.key === "ArrowDown" ? 1 : -1)
                  } else if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault()
                    if (key === selectedKey && event.key === "Enter") onOpen?.(key)
                    else onSelect(key, false)
                  }
                }}
                className={`cursor-pointer outline-none focus-visible:bg-muted data-[state=selected]:shadow-[inset_2px_0_0_var(--foreground)] ${isDim?.(row) ? "opacity-50" : ""}`}
                style={{ height: ROW_HEIGHT }}
              >
                {columns.map((column) => (
                  <TableCell
                    key={column.key}
                    className={`overflow-hidden px-3 ${column.numeric ? "text-right" : ""}`}
                  >
                    {column.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            )
          })}
          {paddingBottom > 0 && (
            <tr aria-hidden style={{ height: paddingBottom }}>
              <td colSpan={columns.length} />
            </tr>
          )}
        </TableBody>
      </table>
      {rows.length === 0 && (
        <p className="p-6 text-center text-sm text-muted-foreground">{emptyText}</p>
      )}
    </div>
  )
}
