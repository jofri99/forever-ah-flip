import { useMemo } from "react"

import { Change, Count, Money } from "@/components/money"
import { Badge } from "@/components/ui/badge"
import { VirtualTable } from "@/components/virtual-table"
import type { Column } from "@/components/virtual-table"
import { itemName, rowKey } from "@/lib/rows"
import type { MarketRow, Names, Sort, SortKey } from "@/lib/types"

interface MarketTableProps {
  rows: MarketRow[]
  names: Names
  sort: Sort
  selectedKey: string | null
  onSort: (key: SortKey) => void
  onSelect: (key: string) => void
}

/** Der Markt: eine Zeile je Item mit Preisen, Angebot und Verkaeufen. */
export function MarketTable({ rows, names, sort, selectedKey, onSort, onSelect }: MarketTableProps) {
  const columns = useMemo<Column<MarketRow, SortKey>[]>(
    () => [
      {
        key: "name",
        label: "Item",
        numeric: false,
        cell: (row) => (
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
    ],
    [names],
  )

  return (
    <VirtualTable
      rows={rows}
      columns={columns}
      getKey={rowKey}
      sort={sort}
      selectedKey={selectedKey}
      onSort={onSort}
      onSelect={onSelect}
      minWidth={980}
      emptyText="No item matches the search."
    />
  )
}
