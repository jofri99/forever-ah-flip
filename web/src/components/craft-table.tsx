import { useMemo } from "react"

import { Count, Money } from "@/components/money"
import { Badge } from "@/components/ui/badge"
import { VirtualTable } from "@/components/virtual-table"
import type { Column } from "@/components/virtual-table"
import { formatInt } from "@/lib/format"
import { craftName, rowKey } from "@/lib/rows"
import type { Craft, CraftSortKey, Names, Sort } from "@/lib/types"

/** Vorzeichen als Farbe: Gewinn gruen, Verlust rot. */
export function Profit({ value }: { value: number | null }) {
  if (value == null) return <Money value={null} />
  return (
    <span className={value > 0 ? "text-up" : value < 0 ? "text-down" : undefined}>
      <Money value={value} />
    </span>
  )
}

interface CraftTableProps {
  rows: Craft[]
  names: Names
  sort: Sort<CraftSortKey>
  selectedKey: string | null
  onSort: (key: CraftSortKey) => void
  onSelect: (key: string) => void
}

/** Herstellen und im Auktionshaus verkaufen: eine Zeile je Rezept. */
export function CraftTable({ rows, names, sort, selectedKey, onSort, onSelect }: CraftTableProps) {
  const columns = useMemo<Column<Craft, CraftSortKey>[]>(
    () => [
      {
        key: "name",
        label: "Makes",
        numeric: false,
        cell: (row) => (
          <span className="flex items-center gap-2">
            <span className="truncate">{craftName(row, names)}</span>
            {row.item_count !== 1 && (
              <Badge variant="outline" className="shrink-0 text-muted-foreground">
                ×{formatInt(row.item_count)}
              </Badge>
            )}
          </span>
        ),
      },
      {
        key: "profession",
        label: "Profession",
        numeric: false,
        width: 150,
        cell: (row) => <span className="block truncate">{row.profession}</span>,
      },
      { key: "skill", label: "Skill", numeric: true, width: 80, cell: (row) => <Count value={row.skill} /> },
      {
        key: "cost",
        label: "Reagents",
        numeric: true,
        width: 130,
        cell: (row) =>
          row.cost != null ? (
            <Money value={row.cost} />
          ) : (
            <span className="text-muted-foreground">{row.unpriced} unpriced</span>
          ),
      },
      { key: "ah_price", label: "AH lowest", numeric: true, width: 130, cell: (row) => <Money value={row.ah_price} /> },
      { key: "profit", label: "Profit", numeric: true, width: 130, cell: (row) => <Profit value={row.profit} /> },
      {
        key: "profit_pct",
        label: "Profit %",
        numeric: true,
        width: 100,
        cell: (row) =>
          row.profit_pct != null ? (
            <span className="tabular-nums">{formatInt(row.profit_pct)}%</span>
          ) : (
            <Count value={null} />
          ),
      },
      { key: "n_listings", label: "Listings", numeric: true, width: 100, cell: (row) => <Count value={row.n_listings} /> },
      { key: "qty_sold_24h", label: "Sold 24h", numeric: true, width: 100, cell: (row) => <Count value={row.qty_sold_24h} /> },
    ],
    [names],
  )

  return (
    <VirtualTable
      rows={rows}
      columns={columns}
      getKey={rowKey}
      getRowId={(row) => String(row.recipe_id)}
      sort={sort}
      selectedKey={selectedKey}
      onSort={onSort}
      onSelect={onSelect}
      minWidth={1180}
      emptyText="No recipe matches the filters."
    />
  )
}
