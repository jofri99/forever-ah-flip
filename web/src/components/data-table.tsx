import { useMemo, useState } from "react"
import type { ReactNode } from "react"

import { VirtualTable } from "@/components/virtual-table"
import { useApp } from "@/lib/app"
import { nextSort, sortBy } from "@/lib/rows"
import type { Sort } from "@/lib/types"

export interface DataColumn<T> {
  key: string
  label: string
  numeric?: boolean
  /** Text sortiert beim ersten Klick aufsteigend, Zahlen absteigend. */
  text?: boolean
  /** Ohne Breite nimmt die Spalte den Rest. */
  width?: number
  /** Wonach sortiert wird. Ohne Wert steht die Zeile immer am Ende. */
  value: (row: T) => number | string | null | undefined
  cell: (row: T) => ReactNode
}

interface DataTableProps<T> {
  rows: T[]
  columns: DataColumn<T>[]
  /** Das Item, das eine Zeile auswaehlt. */
  itemOf: (row: T) => number
  /** Eindeutig je Zeile, wo mehrere Zeilen dasselbe Item zeigen. */
  rowId?: (row: T) => string
  initialSort: Sort
  minWidth: number
  emptyText: string
  isDim?: (row: T) => boolean
}

/**
 * Die Tabelle aller Listenseiten: sortierbar, mit Auswahl fuer die Seitenleiste.
 * Ein Klick waehlt das Item, Doppelklick oder Enter oeffnet seine Vollseite, die
 * Pfeiltasten blaettern.
 */
export function DataTable<T>({
  rows,
  columns,
  itemOf,
  rowId,
  initialSort,
  minWidth,
  emptyText,
  isDim,
}: DataTableProps<T>) {
  const { route, select, open } = useApp()
  const [sort, setSort] = useState<Sort>(initialSort)

  const sorted = useMemo(() => {
    const column = columns.find((candidate) => candidate.key === sort.key) ?? columns[0]
    return sortBy(rows, column.value, sort.dir)
  }, [rows, columns, sort])

  const tableColumns = useMemo(
    () =>
      columns.map((column) => ({
        key: column.key,
        label: column.label,
        numeric: column.numeric ?? false,
        width: column.width,
        cell: column.cell,
      })),
    [columns],
  )

  return (
    <VirtualTable
      rows={sorted}
      columns={tableColumns}
      getKey={(row) => String(itemOf(row))}
      getRowId={rowId}
      sort={sort}
      selectedKey={route.id != null ? String(route.id) : null}
      onSort={(key) =>
        setSort((current) =>
          nextSort(current, key, columns.find((column) => column.key === key)?.text ?? false),
        )
      }
      onSelect={(key, byKeyboard) => select(Number(key), byKeyboard)}
      onOpen={(key) => open(Number(key))}
      isDim={isDim}
      minWidth={minWidth}
      emptyText={emptyText}
    />
  )
}
