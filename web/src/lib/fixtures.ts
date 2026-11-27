import type { Craft, CraftReagent, MarketRow, VendorFlip } from "./types"

/** Bausteine fuer die Tests: eine vollstaendige Zeile, von der nur das Noetige genannt wird. */

export function marketRow(partial: Partial<MarketRow> & Pick<MarketRow, "item_id">): MarketRow {
  return {
    kind: "auction",
    ts: 0,
    min_price: null,
    p25_price: null,
    median_price: null,
    n_listings: 0,
    quantity: 0,
    snapshots_24h: null,
    qty_sold_24h: null,
    value_sold_24h: null,
    sales_hours_24h: null,
    low_24h: null,
    high_24h: null,
    open_24h: null,
    change_24h_pct: null,
    item_class: null,
    item_subclass: null,
    vendor_sell: null,
    vendor_buy: null,
    usual_price: null,
    usual_points: 0,
    qty_new_24h: null,
    market_value: null,
    ...partial,
  }
}

export function craft(partial: Partial<Craft> & Pick<Craft, "recipe_id" | "item_id">): Craft {
  return {
    name: `Recipe ${partial.recipe_id}`,
    profession: "Alchemy",
    category: "Potions",
    skill: 100,
    kind: "commodity",
    item_count: 1,
    reagents: 2,
    unpriced: 0,
    cost_known: 100,
    cost: 100,
    ah_price: 200,
    profit: 90,
    profit_pct: 90,
    n_listings: 1,
    qty_sold_24h: null,
    sales_hours_24h: null,
    learned: "trainer",
    trainer_cost: 500,
    recipe_item_id: null,
    recipe_price: null,
    recipe_source: null,
    item_class: "Consumable",
    item_subclass: "Potion",
    new_in_forever: false,
    cooldown_seconds: null,
    cast_seconds: null,
    ...partial,
  }
}

export function reagent(
  partial: Partial<CraftReagent> & Pick<CraftReagent, "recipe_id" | "item_id">,
): CraftReagent {
  return {
    name: `Item ${partial.item_id}`,
    count: 1,
    unit_price: 10,
    source: "ah",
    vendor: null,
    zone: null,
    n_vendors: null,
    ...partial,
  }
}

export function flip(partial: Partial<VendorFlip> & Pick<VendorFlip, "item_id">): VendorFlip {
  return {
    kind: "auction",
    item_class: "Recipe",
    item_subclass: "Tailoring",
    vendor_price: 100,
    ah_price: 200,
    profit: 90,
    profit_pct: 90,
    n_listings: 1,
    qty_sold_24h: null,
    sales_hours_24h: null,
    limited: false,
    limited_stock: null,
    vendor: "Mahu",
    zone: "Thunder Bluff",
    side: "Horde",
    reputation: null,
    seen_in_forever: true,
    ...partial,
  }
}
