import { Cooldown, Profit } from "@/components/craft-table"
import { Count, Money } from "@/components/money"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatInt } from "@/lib/format"
import type { Craft, CraftReagent, Learned, Names } from "@/lib/types"

const LEARNED: Record<Learned, string> = {
  automatic: "Known from the start",
  trainer: "Taught by a trainer",
  recipe: "Learned from a recipe item",
  unknown: "Source unknown",
}

/** Wie man das Rezept lernt, und was das einmalig kostet. */
function LearnedFrom({ craft }: { craft: Craft }) {
  const price = craft.learned === "trainer" ? craft.trainer_cost : craft.recipe_price
  return (
    <span className="text-muted-foreground">
      {LEARNED[craft.learned]}
      {price != null && craft.learned !== "automatic" && (
        <>
          {" · "}
          <Money value={price} />
          {craft.learned === "recipe" && craft.recipe_source === "ah" && " on the auction house"}
          {craft.learned === "recipe" && craft.recipe_source === "vendor" && " from a vendor"}
        </>
      )}
    </span>
  )
}

interface CraftBreakdownProps {
  craft: Craft
  reagents: CraftReagent[]
  names: Names
  /** Der Schluessel der Marktzeile einer Zutat, wenn sie im Auktionshaus steht. */
  marketKey: (itemId: number) => string | null
  onSelect: (key: string) => void
}

function Source({ reagent }: { reagent: CraftReagent }) {
  if (reagent.source === "ah") return <>Auction house</>
  if (reagent.source === "vendor") {
    return (
      <span className="block truncate">
        Vendor
        {reagent.vendor && (
          <span className="text-muted-foreground">
            {" · "}
            {reagent.vendor}
            {reagent.zone ? `, ${reagent.zone}` : ""}
            {reagent.n_vendors != null && reagent.n_vendors > 1
              ? ` (+${formatInt(reagent.n_vendors - 1)} more)`
              : ""}
          </span>
        )}
      </span>
    )
  }
  return <span className="text-muted-foreground">not for sale right now</span>
}

/** Ein Rezept aufgeschluesselt: jede Zutat mit Preis und Bezugsquelle, darunter die Rechnung. */
export function CraftBreakdown({ craft, reagents, names, marketKey, onSelect }: CraftBreakdownProps) {
  const revenue = craft.ah_price * craft.item_count

  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span className="font-medium">{craft.name}</span>
        <Badge variant="secondary">
          {craft.profession}
          {craft.skill != null ? ` · ${craft.skill}` : ""}
        </Badge>
        {craft.new_in_forever && <Badge variant="outline">New in Forever</Badge>}
        <Cooldown craft={craft} />
        <LearnedFrom craft={craft} />
      </div>

      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Reagent</TableHead>
            <TableHead className="text-right">Qty</TableHead>
            <TableHead className="text-right">Each</TableHead>
            <TableHead className="text-right">Total</TableHead>
            <TableHead>Cheapest at</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {reagents.map((reagent) => {
            const key = marketKey(reagent.item_id)
            const name = names[String(reagent.item_id)] ?? reagent.name
            return (
              <TableRow key={reagent.item_id} className="hover:bg-transparent">
                <TableCell>
                  {key ? (
                    <button
                      type="button"
                      onClick={() => onSelect(key)}
                      className="underline decoration-dotted underline-offset-4 hover:decoration-solid"
                    >
                      {name}
                    </button>
                  ) : (
                    name
                  )}
                </TableCell>
                <TableCell className="text-right">
                  <Count value={reagent.count} />
                </TableCell>
                <TableCell className="text-right">
                  <Money value={reagent.unit_price} />
                </TableCell>
                <TableCell className="text-right">
                  <Money value={reagent.unit_price == null ? null : reagent.unit_price * reagent.count} />
                </TableCell>
                <TableCell>
                  <Source reagent={reagent} />
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>

      <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
        <span>
          <span className="text-muted-foreground">Reagents </span>
          {craft.cost != null ? (
            <Money value={craft.cost} />
          ) : (
            <>
              <Money value={craft.cost_known} />
              <span className="text-muted-foreground"> + {craft.unpriced} unpriced</span>
            </>
          )}
        </span>
        <span>
          <span className="text-muted-foreground">
            Sells for{craft.item_count !== 1 ? ` (×${formatInt(craft.item_count)})` : ""}{" "}
          </span>
          <Money value={revenue} />
        </span>
        <span>
          <span className="text-muted-foreground">Profit after 5% cut </span>
          <Profit value={craft.profit} />
          {craft.profit_pct != null && (
            <span className="text-muted-foreground"> ({formatInt(craft.profit_pct)}%)</span>
          )}
        </span>
      </div>
    </div>
  )
}
