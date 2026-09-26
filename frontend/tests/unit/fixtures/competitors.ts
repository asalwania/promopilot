import type { components } from "@/lib/api/schema";

type CompetitorGap = components["schemas"]["CompetitorGap"];

const kvi = {
  category: "Staples",
  is_kvi: true,
  price_week: 103,
};

// As GET /api/competitors/gaps returns them: widest gap first (ADR 0031).
export const competitorGaps: CompetitorGap[] = [
  {
    ...kvi,
    region: "North",
    sku_id: "SKU0101",
    name: "Annapurna Atta 5kg",
    subcategory: "Atta",
    base_price: 280,
    competitor_price: 252,
    competitor_on_promo: true,
    cpi: 0.9,
    gap: 0.1,
    undercut: true,
  },
  {
    region: "West",
    sku_id: "SKU0007",
    name: "Crunchy Namkeen 400g",
    category: "Snacks",
    subcategory: "Namkeen",
    is_kvi: false,
    price_week: 103,
    base_price: 110,
    competitor_price: 93.5,
    competitor_on_promo: true,
    cpi: 0.85,
    gap: 0.15,
    undercut: false,
  },
  {
    ...kvi,
    region: "South",
    sku_id: "SKU0102",
    name: "Kisan Gold Rice 1kg",
    subcategory: "Rice",
    base_price: 100,
    competitor_price: 94.9,
    competitor_on_promo: false,
    cpi: 0.949,
    gap: 0.051,
    undercut: true,
  },
  {
    ...kvi,
    region: "North",
    sku_id: "SKU0103",
    name: "Desi Harvest Dal 1kg",
    subcategory: "Dal",
    base_price: 100,
    competitor_price: 95.1,
    competitor_on_promo: false,
    cpi: 0.951,
    gap: 0.049,
    undercut: false,
  },
];
