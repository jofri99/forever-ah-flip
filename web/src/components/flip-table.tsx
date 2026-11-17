import { useMemo } from "react"

import { Count, Money } from "@/components/money"
import { Badge } from "@/components/ui/badge"
import { VirtualTable } from "@/components/virtual-table"
import type { Column } from "@/components/virtual-table"
import { formatInt } from "@/lib/format"
import { itemName, rowKey } from "@/lib/rows"
import type { FlipSortKey, Names, Sort, VendorFlip } from "@/lib/types"

interface FlipTableProps {
  rows: VendorFlip[]
  names: Names
  sort: Sort<FlipSortKey>
  selectedKey: string | null
  onSort: (key: FlipSortKey) => void
  onSelect: (key: string) => void
}

/** Beim Haendler kaufen, im Auktionshaus verkaufen: eine Zeile je lohnendem Item. */
export function FlipTable({ rows, names, sort, selectedKey, onSort, onSelect }: FlipTableProps) {
  const columns = useMemo<Column<VendorFlip, FlipSortKey>[]>(
    () => [
      {
        key: "name",
        label: "Item",
        numeric: false,
        cell: (row) => (
          <span className="flex items-center gap-2">
            <span className="truncate">{itemName(row.item_id, names)}</span>
            {row.limited && (
              <Badge variant="outline" className="shrink-0 text-muted-foreground">
                {row.limited_stock != null ? `Limited · ${row.limited_stock}` : "Limited"}
              </Badge>
            )}
          </span>
        ),
      },
      { key: "vendor_price", label: "Vendor", numeric: true, width: 120, cell: (row) => <Money value={row.vendor_price} /> },
      { key: "ah_price", label: "AH lowest", numeric: true, width: 130, cell: (row) => <Money value={row.ah_price} /> },
      {
        key: "profit",
        label: "Profit",
        numeric: true,
        width: 130,
        cell: (row) => (
          <span className="text-up">
            <Money value={row.profit} />
          </span>
        ),
      },
      {
        key: "profit_pct",
        label: "Profit %",
        numeric: true,
        width: 100,
        cell: (row) => <span className="tabular-nums">{formatInt(row.profit_pct)}%</span>,
      },
      { key: "n_listings", label: "Listings", numeric: true, width: 100, cell: (row) => <Count value={row.n_listings} /> },
      { key: "qty_sold_24h", label: "Sold 24h", numeric: true, width: 100, cell: (row) => <Count value={row.qty_sold_24h} /> },
      {
        key: "vendor",
        label: "Sold by",
        numeric: false,
        width: 280,
        cell: (row) => (
          <span className="block truncate">
            {row.vendor}
            {row.zone && <span className="text-muted-foreground"> · {row.zone}</span>}
          </span>
        ),
      },
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
      minWidth={1180}
      emptyText="No vendor flip matches the filters."
    />
  )
}
