import { useMemo } from "react"
import type { ReactNode } from "react"
import { User } from "lucide-react"

import { CooldownBadge, CountBadge, FallBadge, SpikeBadge, Tag, Toggle, TrendBadge, WarnBadge } from "@/components/bits"
import { Money } from "@/components/money"
import { Empty, LinkButton, PageHeader, Panel } from "@/components/page"
import { Button } from "@/components/ui/button"
import { useApp } from "@/lib/app"
import { formatDays, formatInt, moneyText } from "@/lib/format"
import { canCraft } from "@/lib/rows"
import { usePersistent } from "@/lib/settings"
import { belowVendor, craftPerDay, craftProfit, flipPerDay, flipProfit, refillsFast } from "@/lib/trade"
import type { BelowVendor } from "@/lib/trade"
import type { Craft, VendorFlip } from "@/lib/types"

const TOP = 6

/** Eine Gelegenheit: links was, rechts was sie bringt, darunter woraus sich das ergibt. */
function Row({ itemId, title, value, detail }: { itemId: number; title: ReactNode; value: ReactNode; detail: string }) {
  const { route, select, open } = useApp()
  return (
    <button
      type="button"
      onClick={() => select(itemId)}
      onDoubleClick={() => open(itemId)}
      className={`grid w-full grid-cols-[minmax(0,1fr)_auto] gap-x-2.5 gap-y-0.5 border-t px-3.5 py-2 text-left text-sm hover:bg-muted focus-visible:bg-muted focus-visible:outline-none ${
        route.id === itemId ? "bg-muted shadow-[inset_2px_0_0_var(--foreground)]" : ""
      }`}
    >
      <span className="flex min-w-0 items-center gap-1.5 font-medium">{title}</span>
      <span className="text-right font-semibold tabular-nums">{value}</span>
      <span className="col-span-2 truncate text-xs text-muted-foreground">{detail}</span>
    </button>
  )
}

const Name = ({ children }: { children: string }) => <span className="truncate">{children}</span>
const perDay = (value: number) => (
  <>
    <Money value={value} />
    <span className="font-normal text-muted-foreground"> /day</span>
  </>
)

export function OpportunitiesPage({ onSetProfessions }: { onSetProfessions: () => void }) {
  const app = useApp()
  const [cooldowns, setCooldowns] = usePersistent("opportunities.cooldowns", false)
  const [mine, setMine] = usePersistent("opportunities.mine", false)
  const onlyMine = mine && app.hasProfessions

  const crafts = useMemo(() => {
    const best = new Map<number, { craft: Craft; day: number }>() // je Item nur das beste Rezept
    for (const craft of app.crafts) {
      const day = craftPerDay(craft, app.rows.get(craft.item_id), app.a)
      if (day == null || day <= 0) continue
      if ((!cooldowns && craft.cooldown_seconds) || (onlyMine && !canCraft(craft, app.professions))) continue
      const known = best.get(craft.item_id)
      if (!known || day > known.day) best.set(craft.item_id, { craft, day })
    }
    return [...best.values()].sort((x, y) => y.day - x.day)
  }, [app.crafts, app.rows, app.a, app.professions, cooldowns, onlyMine])

  const flips = useMemo(
    () =>
      app.flips
        .map((flip): { flip: VendorFlip; day: number | null } => ({
          flip,
          day: flipPerDay(flip, app.rows.get(flip.item_id), app.a),
        }))
        .filter((entry): entry is { flip: VendorFlip; day: number } => entry.day != null && entry.day > 0)
        .sort((x, y) => y.day - x.day),
    [app.flips, app.rows, app.a],
  )

  const below = useMemo(() => {
    const list: BelowVendor[] = []
    for (const row of app.rows.values()) {
      const entry = belowVendor(row, app.ladder.get(row.item_id))
      if (entry) list.push(entry)
    }
    return list.sort((x, y) => y.total - x.total)
  }, [app.rows, app.ladder])

  const low = useMemo(() => {
    const score = (itemId: number) => app.scores.get(itemId)?.score ?? 0
    return [...app.trades.lowSteady].sort((x, y) => score(y.itemId) - score(x.itemId) || y.profit - x.profit)
  }, [app.trades.lowSteady, app.scores])
  const resets = useMemo(() => [...app.trades.resets].sort((x, y) => y.profit - x.profit), [app.trades.resets])
  const hasLadder = app.ladder.size > 0

  return (
    <>
      <PageHeader title="Opportunities">
        Ranked by what you could realistically earn per day, not by margin alone: profit per unit times your share
        of what actually sells. The assumptions sit in the bar above and apply everywhere.
      </PageHeader>
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <Toggle id="opp-cooldowns" label="Include cooldown recipes" checked={cooldowns} onChange={setCooldowns} />
        {app.hasProfessions ? (
          <Toggle id="opp-mine" label="My professions only" checked={mine} onChange={setMine} />
        ) : (
          <Button variant="outline" onClick={onSetProfessions}>
            <User aria-hidden />
            Set my professions
          </Button>
        )}
      </div>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(320px,100%),1fr))] items-start gap-3.5">
        {app.crafts.length > 0 && (
          <Panel
            title="Craft and sell"
            count={crafts.length}
            action={<LinkButton onClick={() => app.go("crafting")}>View all →</LinkButton>}
            sub="Buy the reagents, craft, list on the auction house."
          >
            {crafts.slice(0, TOP).map(({ craft, day }) => {
              const row = app.rows.get(craft.item_id)
              return (
                <Row
                  key={craft.recipe_id}
                  itemId={craft.item_id}
                  title={
                    <>
                      <Name>{app.name(craft.item_id)}</Name>
                      <CountBadge craft={craft} />
                      <CooldownBadge craft={craft} />
                      <SpikeBadge row={row} basis={app.a.basis} />
                    </>
                  }
                  value={perDay(day)}
                  detail={`${moneyText(craftProfit(craft, row, app.a.basis))} per craft · ${formatInt(row?.qty_sold_24h ?? 0)} sold/day · ${craft.profession}${craft.skill != null ? ` ${craft.skill}` : ""}`}
                />
              )
            })}
            {crafts.length === 0 && (
              <Empty>{onlyMine ? "Nothing profitable at your skill right now." : "Nothing profitable right now."}</Empty>
            )}
          </Panel>
        )}

        {app.flips.length > 0 && (
          <Panel
            title="Vendor to auction house"
            count={flips.length}
            action={<LinkButton onClick={() => app.go("flips")}>View all →</LinkButton>}
            sub="Buy from a vendor, list for more."
          >
            {flips.slice(0, TOP).map(({ flip, day }) => {
              const row = app.rows.get(flip.item_id)
              return (
                <Row
                  key={flip.item_id}
                  itemId={flip.item_id}
                  title={
                    <>
                      <Name>{app.name(flip.item_id)}</Name>
                      {flip.limited && <Tag>Limited{flip.limited_stock ? ` · ${flip.limited_stock}` : ""}</Tag>}
                      <SpikeBadge row={row} basis={app.a.basis} />
                    </>
                  }
                  value={perDay(day)}
                  detail={`${moneyText(flipProfit(flip, row, app.a.basis))} each · ${formatInt(row?.qty_sold_24h ?? 0)} sold/day · ${flip.vendor}${flip.zone ? `, ${flip.zone}` : ""}`}
                />
              )
            })}
            {flips.length === 0 && <Empty>No vendor flip sells right now.</Empty>}
          </Panel>
        )}

        {hasLadder && (
          <Panel
            title="Buy low"
            count={low.length}
            action={<LinkButton onClick={() => app.go("low")}>View all →</LinkButton>}
            sub={`Listed at ${Math.round(app.a.buyAt * 100)}% of the usual price or less, and not on a steady downtrend. Buy, relist at the usual price. Best buy score first.`}
          >
            {low.slice(0, TOP).map((p) => {
              const row = app.rows.get(p.itemId)
              return (
                <Row
                  key={p.itemId}
                  itemId={p.itemId}
                  title={
                    <>
                      <Name>{app.name(p.itemId)}</Name>
                      <Tag solid>Score {app.scores.get(p.itemId)?.score ?? 0}</Tag>
                      <Tag>{Math.round(((row?.min_price ?? 0) / p.target) * 100)}% of usual</Tag>
                      <FallBadge row={row} />
                    </>
                  }
                  value={<Money value={p.profit} />}
                  detail={`Buy ${formatInt(p.units)} for ${moneyText(p.cost)} · usual ${moneyText(p.target)} · ${formatInt(row?.qty_sold_24h ?? 0)} sold/day`}
                />
              )
            })}
            {low.length === 0 && <Empty>Nothing is listed that far below its usual price.</Empty>}
          </Panel>
        )}

        {hasLadder && (
          <Panel
            title="Market reset"
            count={resets.length}
            action={<LinkButton onClick={() => app.go("reset")}>View all →</LinkButton>}
            sub={`Buy every listing up to a gap, relist just under the next one. With ${formatInt(app.a.gold)}g to spend.`}
          >
            {resets.slice(0, TOP).map((p) => {
              const row = app.rows.get(p.itemId)
              return (
                <Row
                  key={p.itemId}
                  itemId={p.itemId}
                  title={
                    <>
                      <Name>{app.name(p.itemId)}</Name>
                      {refillsFast(row, app.levels) && <WarnBadge>Refills fast</WarnBadge>}
                      <TrendBadge row={row} />
                      <FallBadge row={row} />
                    </>
                  }
                  value={<Money value={p.profit} />}
                  detail={`Buy ${formatInt(p.units)} for ${moneyText(p.cost)} · relist at ${moneyText(p.target)} · sells in ${p.days == null ? "–" : formatDays(p.days)}`}
                />
              )
            })}
            {resets.length === 0 && <Empty>No reset fits your gold right now.</Empty>}
          </Panel>
        )}

        <Panel
          title="Below vendor price"
          count={below.length}
          action={<LinkButton onClick={() => app.go("market")}>Open market →</LinkButton>}
          sub="Buy on the auction house, sell to any vendor. No risk, limited supply."
        >
          {below.slice(0, TOP).map((entry) => {
            const row = app.rows.get(entry.itemId)
            return (
              <Row
                key={entry.itemId}
                itemId={entry.itemId}
                title={<Name>{app.name(entry.itemId)}</Name>}
                value={<Money value={entry.total} />}
                detail={`${formatInt(entry.units)} unit${entry.units === 1 ? "" : "s"} below vendor price · listed ${moneyText(row?.min_price)}, vendor pays ${moneyText(row?.vendor_sell)}`}
              />
            )
          })}
          {below.length === 0 && <Empty>Nothing is listed below vendor price.</Empty>}
        </Panel>
      </div>
    </>
  )
}
