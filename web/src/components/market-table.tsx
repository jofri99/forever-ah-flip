import { useEffect, useRef } from "react"
import type { ReactNode } from "react"
import { useVirtualizer } from "@tanstack/react-virtual"
import { ArrowDown, ArrowUp } from "lucide-react"

import { Change, Count, Money } from "@/components/money"
import { Badge } from "@/components/ui/badge"
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { itemName, rowKey } from "@/lib/rows"
import type { MarketRow, Names, Sort, SortKey } from "@/lib/types"

/** Feste Zeilenhoehe: nur so weiss die Liste ohne Messen, wo welche Zeile liegt. */
const ROW_HEIGHT = 37

interface Column {
  key: SortKey
  label: string
  numeric: boolean
  /** Ohne Breite nimmt die Spalte den Rest. */
  width?: number
  cell: (row: MarketRow, names: Names) => ReactNode
}

const COLUMNS: Column[] = [
  {
    key: "name",
    label: "Item",
    numeric: false,
    cell: (row, names) => (
      <span className="flex items-center gap-2">
        <span className="truncate">{itemName(row.item_id, names)}</span>
        {row.kind === "commodity" && (
          <Badge variant="outline" className="shrink-0 text-muted-foreground">
            Commodity
          </Badge>
        )}
      </span>
    ),
  },
  { key: "min_price", label: "Lowest", numeric: true, width: 140, cell: (row) => <Money value={row.min_price} /> },
  { key: "median_price", label: "Median", numeric: true, width: 140, cell: (row) => <Money value={row.median_price} /> },
  { key: "n_listings", label: "Listings", numeric: true, width: 110, cell: (row) => <Count value={row.n_listings} /> },
  { key: "quantity", label: "Quantity", numeric: true, width: 110, cell: (row) => <Count value={row.quantity} /> },
  { key: "change_24h_pct", label: "24h", numeric: true, width: 110, cell: (row) => <Change value={row.change_24h_pct} /> },
  { key: "qty_sold_24h", label: "Sold 24h", numeric: true, width: 130, cell: (row) => <Count value={row.qty_sold_24h} /> },
  { key: "value_sold_24h", label: "Value 24h", numeric: true, width: 150, cell: (row) => <Money value={row.value_sold_24h} /> },
]

interface MarketTableProps {
  rows: MarketRow[]
  names: Names
  sort: Sort
  selectedKey: string | null
  onSort: (key: SortKey) => void
  onSelect: (key: string) => void
}

export function MarketTable({ rows, names, sort, selectedKey, onSort, onSelect }: MarketTableProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  // Von 6.400 Zeilen stehen immer nur die sichtbaren im Dokument.
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

  const items = virtualizer.getVirtualItems()
  const paddingTop = items.length ? items[0].start : 0
  const paddingBottom = items.length ? virtualizer.getTotalSize() - items[items.length - 1].end : 0

  return (
    <div ref={scrollRef} className="max-h-[70vh] overflow-auto rounded-lg border bg-card">
      <table className="w-full min-w-[980px] table-fixed caption-bottom text-sm">
        <colgroup>
          {COLUMNS.map((column) => (
            <col key={column.key} style={column.width ? { width: column.width } : undefined} />
          ))}
        </colgroup>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {COLUMNS.map((column) => {
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
              <td colSpan={COLUMNS.length} />
            </tr>
          )}
          {items.map((item) => {
            const row = rows[item.index]
            const key = rowKey(row)
            return (
              <TableRow
                key={key}
                data-state={key === selectedKey ? "selected" : undefined}
                tabIndex={0}
                onClick={() => onSelect(key)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault()
                    onSelect(key)
                  }
                }}
                className="cursor-pointer outline-none focus-visible:bg-muted"
                style={{ height: ROW_HEIGHT }}
              >
                {COLUMNS.map((column) => (
                  <TableCell
                    key={column.key}
                    className={`overflow-hidden px-3 ${column.numeric ? "text-right" : ""}`}
                  >
                    {column.cell(row, names)}
                  </TableCell>
                ))}
              </TableRow>
            )
          })}
          {paddingBottom > 0 && (
            <tr aria-hidden style={{ height: paddingBottom }}>
              <td colSpan={COLUMNS.length} />
            </tr>
          )}
        </TableBody>
      </table>
      {rows.length === 0 && (
        <p className="p-6 text-center text-sm text-muted-foreground">No item matches the search.</p>
      )}
    </div>
  )
}
