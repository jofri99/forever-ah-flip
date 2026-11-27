import { useState } from "react"
import type { ReactNode } from "react"
import { Maximize2, ShoppingCart } from "lucide-react"

import { CooldownBadge, Hint, ScoreMeter, Stepper, Tag, TrendBadge } from "@/components/bits"
import { Count, Money, Profit } from "@/components/money"
import { Button } from "@/components/ui/button"
import { useApp } from "@/lib/app"
import { formatInt, formatRatio, kindLabel, moneyText } from "@/lib/format"
import { relist } from "@/lib/relist"
import { canCraft } from "@/lib/rows"
import { AH_KEEP, bestReset, craftPerDay, craftProfit, flipProfit, isDowntrend, isSpiked, lowBuy, sellAt } from "@/lib/trade"
import type { Craft, SeriesPoint } from "@/lib/types"

function Section({ title, sub, children }: { title: ReactNode; sub?: ReactNode; children: ReactNode }) {
  return (
    <section>
      <h3 className="mb-1.5 flex flex-wrap items-center gap-1.5 text-xs font-semibold">
        {title}
        {sub && <span className="font-normal text-muted-foreground">· {sub}</span>}
      </h3>
      {children}
    </section>
  )
}

/** Was fuer ein Item das ist: Art und Typ - oder dass es gerade nicht im Auktionshaus steht. */
export function ItemTags({ itemId }: { itemId: number }) {
  const row = useApp().rows.get(itemId)
  return (
    <>
      {row && <Tag>{kindLabel(row.kind)}</Tag>}
      {row?.item_class && (
        <Tag solid>
          {row.item_class}
          {row.item_subclass && row.item_subclass !== row.item_class ? ` · ${row.item_subclass}` : ""}
        </Tag>
      )}
      <TrendBadge row={row} />
      {!row && <Tag>Not on the auction house</Tag>}
    </>
  )
}

/** Zwei Spalten: links was, rechts wie viel. */
export function Lines({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-sm">{children}</div>
}

export function Line({ label, children, strong }: { label: ReactNode; children: ReactNode; strong?: boolean }) {
  return (
    <>
      <span className={strong ? "" : "text-muted-foreground"}>{label}</span>
      <span className={`text-right tabular-nums ${strong ? "text-[15px] font-semibold" : ""}`}>{children}</span>
    </>
  )
}

/** Ein Name, der zum Item fuehrt. */
function ItemLink({ itemId }: { itemId: number }) {
  const { name, select } = useApp()
  return (
    <button
      type="button"
      onClick={() => select(itemId)}
      className="max-w-full truncate text-left underline decoration-dotted underline-offset-4 hover:decoration-solid"
    >
      {name(itemId)}
    </button>
  )
}

function learnedText(craft: Craft): string {
  if (craft.learned === "automatic") return "Known from the start"
  if (craft.learned === "trainer") {
    return `Taught by a trainer${craft.trainer_cost ? ` · ${moneyText(craft.trainer_cost)}` : ""}`
  }
  if (craft.learned === "recipe") {
    if (craft.recipe_price == null) return "Learned from a recipe item · not for sale right now"
    return `Learned from a recipe item · ${moneyText(craft.recipe_price)} ${craft.recipe_source === "vendor" ? "from a vendor" : "on the auction house"}`
  }
  return "Source unknown"
}

/** Ein Rezept aufgeschluesselt: jede Zutat mit Preis und Bezugsquelle, darunter die Rechnung. */
export function CraftSection({ itemId }: { itemId: number }) {
  const app = useApp()
  const recipes = app.craftsByItem.get(itemId)
  const [chosen, setChosen] = useState<number | null>(null)
  const [quantity, setQuantity] = useState(1)
  if (!recipes?.length) return null

  const craft = recipes.find((candidate) => candidate.recipe_id === chosen) ?? recipes[0]
  const row = app.rows.get(itemId)
  const price = sellAt(row, app.a.basis)
  const profit = craftProfit(craft, row, app.a.basis)
  const perDay = craftPerDay(craft, row, app.a)
  const blocked = app.hasProfessions && !canCraft(craft, app.professions)
  const inCart = app.cart.find((line) => line.recipeId === craft.recipe_id)?.quantity ?? 0

  return (
    <Section
      title={
        <>
          Craft it
          <CooldownBadge craft={craft} />
          {craft.new_in_forever && <Tag>New in Forever</Tag>}
        </>
      }
      sub={`${craft.profession}${craft.skill != null ? ` ${craft.skill}` : ""}`}
    >
      {recipes.length > 1 && (
        <select
          aria-label="Recipe"
          value={craft.recipe_id}
          onChange={(event) => setChosen(Number(event.target.value))}
          className="mb-2 h-8 w-full rounded-lg border bg-transparent px-2 text-sm"
        >
          {recipes.map((recipe) => (
            <option key={recipe.recipe_id} value={recipe.recipe_id}>
              {recipe.name} · {recipe.profession}
            </option>
          ))}
        </select>
      )}
      <table className="w-full text-sm tabular-nums">
        <tbody>
          {(app.reagents.get(craft.recipe_id) ?? []).map((reagent) => (
            <tr key={reagent.item_id} className="border-t first:border-t-0">
              <td className="max-w-0 w-full py-1 pr-2"><ItemLink itemId={reagent.item_id} /></td>
              <td className="py-1 pr-2 text-right whitespace-nowrap">{formatInt(reagent.count)} ×</td>
              <td className="py-1 pr-2 text-right"><Money value={reagent.unit_price} /></td>
              <td
                className="max-w-28 truncate py-1 text-muted-foreground"
                title={
                  reagent.source === "vendor"
                    ? `${reagent.vendor ?? ""}${reagent.zone ? `, ${reagent.zone}` : ""}${reagent.n_vendors && reagent.n_vendors > 1 ? ` (+${reagent.n_vendors - 1} more)` : ""}`
                    : undefined
                }
              >
                {reagent.source === "ah" ? "AH" : reagent.source === "vendor" ? (reagent.zone ?? reagent.vendor) : "none"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 border-t pt-2">
        <Lines>
          <Line label="Reagents">
            {craft.cost != null ? (
              <Money value={craft.cost} />
            ) : (
              <>
                <Money value={craft.cost_known} /> <span className="text-muted-foreground">+ {craft.unpriced} unpriced</span>
              </>
            )}
          </Line>
          <Line label={`Sells for${craft.item_count !== 1 ? ` (×${formatInt(craft.item_count)})` : ""}, after 5% cut`}>
            <Money value={price == null ? null : price * craft.item_count * AH_KEEP} />
          </Line>
          <Line label="Profit per craft" strong>
            <Profit value={profit} />
          </Line>
          <Line label={`At ${app.a.share * 100}% of daily sales`}>
            <Profit value={perDay} />
            <span className="text-muted-foreground"> /day</span>
          </Line>
        </Lines>
      </div>
      {isSpiked(row, app.a.basis) && (
        <Hint className="mt-1.5 text-down">
          The lowest listing is up {Math.round(row?.change_24h_pct ?? 0)}% in 24h. Switch “Sell at” to the 24h low
          for a cautious figure.
        </Hint>
      )}
      <Hint className="mt-1.5">
        {learnedText(craft)}
        {blocked && <span className="text-down"> · above your skill or not your profession</span>}
      </Hint>
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <Stepper value={quantity} onChange={setQuantity} />
        <Button onClick={() => app.setCartQuantity(craft.recipe_id, inCart + quantity)}>
          <ShoppingCart aria-hidden />
          Add to shopping list
        </Button>
        {inCart > 0 && <span className="text-xs text-muted-foreground">{formatInt(inCart)} on the list</span>}
      </div>
    </Section>
  )
}

/** Welche Rezepte dieses Item verbrauchen - damit man sieht, wo es am meisten bringt. */
export function UsedInSection({ itemId }: { itemId: number }) {
  const app = useApp()
  const uses = app.usedIn.get(itemId)
  if (!uses?.length) return null
  const ranked = uses
    .map((craft) => ({
      craft,
      profit: craftProfit(craft, app.rows.get(craft.item_id), app.a.basis),
      perDay: craftPerDay(craft, app.rows.get(craft.item_id), app.a),
    }))
    .sort((x, y) => (y.perDay ?? -Infinity) - (x.perDay ?? -Infinity))
  return (
    <Section title="Used in" sub={`${ranked.length} recipe${ranked.length === 1 ? "" : "s"}, best first`}>
      <table className="w-full text-sm tabular-nums">
        <thead>
          <tr className="text-left text-[11px] tracking-wide text-muted-foreground uppercase">
            <th className="py-1 font-medium">Makes</th>
            <th className="py-1 text-right font-medium">Profit</th>
            <th className="py-1 text-right font-medium">Est./day</th>
          </tr>
        </thead>
        <tbody>
          {ranked.slice(0, 8).map(({ craft, profit, perDay }) => (
            <tr key={craft.recipe_id} className="border-t">
              <td className="max-w-0 w-full py-1 pr-2"><ItemLink itemId={craft.item_id} /></td>
              <td className="py-1 pr-2 text-right"><Profit value={profit} /></td>
              <td className="py-1 text-right"><Profit value={perDay} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {ranked.length > 8 && <Hint className="mt-1">and {ranked.length - 8} more</Hint>}
    </Section>
  )
}

/** Wer das Item verkauft, was ein Haendler dafuer zahlt und was sich daraus machen laesst. */
export function VendorsSection({ itemId, bare }: { itemId: number; bare?: boolean }) {
  const app = useApp()
  const row = app.rows.get(itemId)
  const vendors = app.vendors.get(itemId) ?? []
  const pays = row?.vendor_sell != null && row.vendor_sell > 0 ? row.vendor_sell : null
  if (!vendors.length && pays == null) return null
  const flip = app.flipByItem.get(itemId)
  const body = (
    <>
      {vendors.length ? (
        <table className="w-full text-sm tabular-nums">
          <tbody>
            {vendors.map((vendor) => (
              <tr key={`${vendor.vendor}:${vendor.zone}`} className="border-t first:border-t-0">
                <td className="max-w-0 w-full truncate py-1 pr-2">
                  {vendor.vendor}
                  {vendor.zone && <span className="text-muted-foreground"> · {vendor.zone}</span>}{" "}
                  {vendor.limited && <Tag>Limited{vendor.limited_stock ? ` · ${vendor.limited_stock}` : ""}</Tag>}
                </td>
                <td className="py-1 text-right"><Money value={vendor.price_per_item} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <Hint>No vendor the Horde can reach sells this.</Hint>
      )}
      {vendors.length > 0 && vendors[0].n_vendors > vendors.length && (
        <Hint className="mt-1">and {vendors[0].n_vendors - vendors.length} more vendors</Hint>
      )}
      <div className="mt-2 border-t pt-2">
        <Lines>
          {flip && (
            <Line label="Buy from vendor, sell on AH" strong>
              <Profit value={flipProfit(flip, row, app.a.basis)} />
            </Line>
          )}
          {pays != null && (
            <Line label="A vendor pays">
              <Money value={pays} />
            </Line>
          )}
          {pays != null && row?.min_price != null && pays > row.min_price && (
            <Line label="Buy on AH, sell to vendor" strong>
              <Profit value={pays - row.min_price} />
            </Line>
          )}
        </Lines>
      </div>
    </>
  )
  return bare ? body : <Section title="Vendors">{body}</Section>
}

/**
 * In der Seitenleiste: was sich mit dem Item handeln laesst, in ein paar Zeilen.
 * Mit dem Verlauf steht dabei, wo es am besten wieder eingestellt wird.
 */
export function TradeSection({ itemId, series }: { itemId: number; series?: readonly SeriesPoint[] }) {
  const app = useApp()
  const row = app.rows.get(itemId)
  if (!row || row.min_price == null) return null
  const tiers = app.ladder.get(itemId)
  const low = lowBuy(row, tiers, app.a)
  const reset = bestReset(row, tiers, app.a)
  const where = series?.length ? relist(row, tiers, series, app.a.horizon) : null
  return (
    <Section title="Trade it">
      <Lines>
        <Line label="Buy score">
          <ScoreMeter value={app.scores.get(itemId)?.score} />
        </Line>
        {row.usual_price != null && (
          <Line label="Usual price">
            <Money value={row.usual_price} />{" "}
            <span className="text-muted-foreground">· now {Math.round((row.min_price / row.usual_price) * 100)}%</span>
          </Line>
        )}
        {low && (
          <Line label={<>Buy low: <Count value={low.units} /> for {moneyText(low.cost)}</>} strong>
            <Profit value={low.profit} />
          </Line>
        )}
        {reset && (
          <Line label={<>Reset: buy <Count value={reset.units} /> for {moneyText(reset.cost)}, relist at {moneyText(reset.target)}</>} strong>
            <Profit value={reset.profit} />
          </Line>
        )}
        {where && (
          <Line
            label={
              where.best === where.first
                ? "Relist: sell first, 1c under the lowest"
                : `Relist: reached ${Math.round((where.best.reached ?? 0) * 100)}% of the time within ${where.horizon} d`
            }
          >
            <Money value={where.best.price} precise />
          </Line>
        )}
      </Lines>
      {isDowntrend(row) && (
        <Hint className="mt-1.5 text-down">
          Falling about {formatRatio(-(row.trend_pct_day ?? 0))}% a day, steadily: a trend, not a dip.
        </Hint>
      )}
      {row.usual_price == null && (
        <Hint className="mt-1.5">Not enough history yet for a usual price ({row.usual_points} snapshots).</Hint>
      )}
      <Button variant="outline" className="mt-2.5" onClick={() => app.open(itemId)}>
        <Maximize2 aria-hidden />
        Full page with price ladder and heatmap
      </Button>
    </Section>
  )
}
