import { useMemo, useState } from "react"
import { Copy, Minus, Plus, X } from "lucide-react"

import { CooldownBadge, CountBadge, Hint, NameCell, Stat } from "@/components/bits"
import { Money, Profit } from "@/components/money"
import { Empty, LinkButton, PageHeader, Panel } from "@/components/page"
import { Button } from "@/components/ui/button"
import { useApp } from "@/lib/app"
import type { AppValue } from "@/lib/app"
import { formatInt, moneyText } from "@/lib/format"
import { AH_KEEP, craftProfit, sellAt } from "@/lib/trade"
import type { CraftReagent } from "@/lib/types"

interface Need {
  reagent: CraftReagent
  count: number
}

/** Was fuer die geplanten Rezepte zu kaufen ist, nach Bezugsquelle gebuendelt. */
function shoppingList(app: AppValue) {
  const needs = new Map<number, Need>()
  let revenue = 0
  for (const line of app.cart) {
    const craft = app.craftById.get(line.recipeId)
    if (!craft) continue
    revenue += (sellAt(app.rows.get(craft.item_id), app.a.basis) ?? 0) * craft.item_count * line.quantity * AH_KEEP
    for (const reagent of app.reagents.get(craft.recipe_id) ?? []) {
      const need = needs.get(reagent.item_id)
      if (need) need.count += reagent.count * line.quantity
      else needs.set(reagent.item_id, { reagent, count: reagent.count * line.quantity })
    }
  }
  const groups = new Map<string, Need[]>()
  for (const need of needs.values()) {
    const { source, vendor, zone, n_vendors } = need.reagent
    const key =
      source === "vendor"
        ? `Vendor · ${vendor}${zone ? `, ${zone}` : ""}${n_vendors && n_vendors > 1 ? ` (+${n_vendors - 1} more)` : ""}`
        : source === "ah"
          ? "Auction house"
          : "Not for sale right now"
    const group = groups.get(key)
    if (group) group.push(need)
    else groups.set(key, [need])
  }
  const all = [...needs.values()]
  return {
    groups,
    revenue,
    cost: all.reduce((sum, need) => sum + (need.reagent.unit_price ?? 0) * need.count, 0),
    unpriced: all.filter((need) => need.reagent.unit_price == null).length,
  }
}

/** Eine Sitzung planen: Rezepte und Mengen waehlen, eine Liste bekommen, was wo zu kaufen ist. */
export function ShoppingPage() {
  const app = useApp()
  const [copied, setCopied] = useState<string | null>(null)
  const list = useMemo(() => shoppingList(app), [app])
  const lines = app.cart.filter((line) => app.craftById.has(line.recipeId))

  if (lines.length === 0) {
    return (
      <>
        <PageHeader title="Shopping list">
          Plan a crafting session: pick recipes and quantities, get one list of what to buy and where.
        </PageHeader>
        <div className="rounded-xl border bg-card">
          <Empty>Empty. Open a craftable item and choose “Add to shopping list”.</Empty>
        </div>
      </>
    )
  }

  const copy = () => {
    const text =
      [...list.groups]
        .map(([group, needs]) =>
          [group, ...needs.map((need) => `  ${need.count} x ${app.name(need.reagent.item_id)}  (${moneyText(need.reagent.unit_price)} each)`)].join("\n"),
        )
        .join("\n\n") + `\n\nTo spend: ${moneyText(list.cost)}\nSells for, after cut: ${moneyText(list.revenue)}`
    if (!navigator.clipboard?.writeText) return setCopied("Copying is not available here")
    navigator.clipboard.writeText(text).then(
      () => setCopied("Copied"),
      () => setCopied("Copying is blocked in this view"),
    )
  }

  return (
    <>
      <PageHeader title="Shopping list">
        One list for the whole session. Prices are the current lowest listing; buying larger quantities will cost
        more as the cheap listings run out.
      </PageHeader>
      <div className="mb-3.5 grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-2">
        <Stat label="To spend" sub={list.unpriced ? `plus ${list.unpriced} unpriced reagent${list.unpriced === 1 ? "" : "s"}` : undefined}>
          <Money value={list.cost} />
        </Stat>
        <Stat label="Sells for, after cut"><Money value={list.revenue} /></Stat>
        <Stat label="Profit"><Profit value={list.unpriced ? null : list.revenue - list.cost} /></Stat>
      </div>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(380px,100%),1fr))] items-start gap-3.5">
        <Panel title="Plan" action={<LinkButton onClick={app.clearCart}>Clear</LinkButton>}>
          <table className="w-full text-sm tabular-nums">
            <thead>
              <tr className="border-t text-[11px] tracking-wide text-muted-foreground uppercase">
                <th className="px-3.5 py-1.5 text-left font-medium">Recipe</th>
                <th className="py-1.5 text-right font-medium">Crafts</th>
                <th className="px-2 py-1.5 text-right font-medium">Profit</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {lines.map((line) => {
                const craft = app.craftById.get(line.recipeId)!
                const profit = craftProfit(craft, app.rows.get(craft.item_id), app.a.basis)
                const set = (quantity: number) => app.setCartQuantity(craft.recipe_id, quantity)
                return (
                  <tr
                    key={craft.recipe_id}
                    onClick={() => app.select(craft.item_id)}
                    className={`cursor-pointer border-t hover:bg-muted ${app.route.id === craft.item_id ? "bg-muted" : ""}`}
                  >
                    <td className="max-w-0 w-full px-3.5 py-1.5">
                      <NameCell name={app.name(craft.item_id)}>
                        <CountBadge craft={craft} />
                        <CooldownBadge craft={craft} />
                      </NameCell>
                    </td>
                    <td className="py-1.5" onClick={(event) => event.stopPropagation()}>
                      <span className="inline-flex items-center overflow-hidden rounded-lg border">
                        <button type="button" aria-label="Fewer" onClick={() => set(line.quantity - 1)} className="grid size-7 place-items-center hover:bg-muted">
                          <Minus className="size-3.5" aria-hidden />
                        </button>
                        <input
                          value={line.quantity}
                          inputMode="numeric"
                          aria-label="Quantity"
                          onChange={(event) => set(Math.max(1, parseInt(event.target.value, 10) || 1))}
                          className="h-7 w-10 border-x bg-transparent text-center outline-none"
                        />
                        <button type="button" aria-label="More" onClick={() => set(line.quantity + 1)} className="grid size-7 place-items-center hover:bg-muted">
                          <Plus className="size-3.5" aria-hidden />
                        </button>
                      </span>
                    </td>
                    <td className="px-2 py-1.5 text-right whitespace-nowrap">
                      <Profit value={profit == null ? null : profit * line.quantity} />
                    </td>
                    <td className="pr-2" onClick={(event) => event.stopPropagation()}>
                      <Button variant="ghost" size="icon-sm" aria-label="Remove" onClick={() => set(0)}>
                        <X />
                      </Button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </Panel>

        <Panel
          title="To buy"
          action={
            <LinkButton onClick={copy}>
              <Copy className="mr-1 inline size-3" aria-hidden />
              {copied ?? "Copy as text"}
            </LinkButton>
          }
        >
          {[...list.groups].map(([group, needs]) => (
            <div key={group}>
              <div className="border-t bg-muted px-3.5 py-1.5 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                {group}
              </div>
              <table className="w-full text-sm tabular-nums">
                <tbody>
                  {needs.map((need) => (
                    <tr
                      key={need.reagent.item_id}
                      onClick={() => app.select(need.reagent.item_id)}
                      className="cursor-pointer border-t hover:bg-muted"
                    >
                      <td className="max-w-0 w-full truncate px-3.5 py-1.5">{app.name(need.reagent.item_id)}</td>
                      <td className="py-1.5 pr-3 text-right whitespace-nowrap">{formatInt(need.count)} ×</td>
                      <td className="py-1.5 pr-3 text-right"><Money value={need.reagent.unit_price} /></td>
                      <td className="py-1.5 pr-3.5 text-right">
                        <Money value={need.reagent.unit_price == null ? null : need.reagent.unit_price * need.count} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </Panel>
      </div>
      <Hint className="mt-2">The list is kept in this browser.</Hint>
    </>
  )
}
