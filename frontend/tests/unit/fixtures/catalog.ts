import type {
  CompetitorGaps,
  InventoryReport,
  Product,
  RegionStores,
} from "@/lib/api/catalog";

import { competitorGaps } from "./competitors";

// As GET /api/catalog/products returns them: SKU order (ADR 0034).
export const products: Product[] = [
  {
    sku_id: "SKU0007",
    name: "Crunchy Namkeen 400g",
    brand: "Crunchy",
    category: "Snacks",
    subcategory: "Namkeen",
    pack_size: "400g",
    base_price: 110,
    unit_cost: 72.5,
    is_kvi: false,
  },
  {
    sku_id: "SKU0101",
    name: "Annapurna Atta 5kg",
    brand: "Annapurna",
    category: "Staples",
    subcategory: "Atta",
    pack_size: "5kg",
    base_price: 280,
    unit_cost: 231,
    is_kvi: true,
  },
  {
    sku_id: "SKU0102",
    name: "Kisan Gold Rice 1kg",
    brand: "Kisan Gold",
    category: "Staples",
    subcategory: "Rice",
    pack_size: "1kg",
    base_price: 100,
    unit_cost: 82,
    is_kvi: true,
  },
];

const mix = {
  "Value Seekers": 0.4,
  Families: 0.3,
  Premium: 0.2,
  "Young Urban": 0.1,
};

export const regions: RegionStores[] = [
  {
    region: "North",
    stores: [{ store_id: "S01", city: "Delhi", segment_mix: mix }],
  },
  {
    region: "South",
    stores: [{ store_id: "S06", city: "Chennai", segment_mix: mix }],
  },
];

// As GET /api/inventory returns it: SKU then region order (ADR 0032).
export const inventory: InventoryReport = {
  as_of_week: 105,
  snapshot_week: 104,
  overstock_threshold_days: 56,
  statuses: [
    {
      sku_id: "SKU0007",
      name: "Crunchy Namkeen 400g",
      category: "Snacks",
      region: "North",
      on_hand: 1200,
      safety_stock: 150,
      on_order: 0,
      available_stock: 1050,
      days_of_cover: 71.43,
      is_overstock: true,
    },
    {
      sku_id: "SKU0007",
      name: "Crunchy Namkeen 400g",
      category: "Snacks",
      region: "South",
      on_hand: 400,
      safety_stock: 120,
      on_order: 60,
      available_stock: 280,
      days_of_cover: 20,
      is_overstock: false,
    },
    {
      sku_id: "SKU0101",
      name: "Annapurna Atta 5kg",
      category: "Staples",
      region: "North",
      on_hand: 300,
      safety_stock: 90,
      on_order: 40,
      available_stock: 210,
      days_of_cover: 14.25,
      is_overstock: false,
    },
  ],
};

export const gaps: CompetitorGaps = {
  as_of_week: 105,
  undercut_threshold: 0.05,
  kvi_price_tolerance: 0.02,
  gaps: competitorGaps,
};
