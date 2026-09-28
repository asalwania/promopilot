import { z } from "zod";

import { responseReason } from "@/lib/api/reason";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];

// The `/data` explorer's reads (ADR 0034). Each schema must match the
// OpenAPI-generated type (make api-types), or tsc fails here.
const region = z.enum(["North", "South", "East", "West"]);

const productSchema = z.object({
  sku_id: z.string(),
  name: z.string(),
  brand: z.string(),
  category: z.string(),
  subcategory: z.string(),
  pack_size: z.string(),
  base_price: z.number(),
  unit_cost: z.number(),
  is_kvi: z.boolean(),
}) satisfies z.ZodType<Schemas["Product"]>;

const regionStoresSchema = z.object({
  region,
  stores: z.array(
    z.object({
      store_id: z.string(),
      city: z.string(),
      segment_mix: z.record(z.string(), z.number()),
    }),
  ),
}) satisfies z.ZodType<Schemas["RegionStores"]>;

const inventoryReportSchema = z.object({
  as_of_week: z.number(),
  snapshot_week: z.number(),
  overstock_threshold_days: z.number(),
  statuses: z.array(
    z.object({
      sku_id: z.string(),
      name: z.string(),
      category: z.string(),
      region,
      on_hand: z.number(),
      safety_stock: z.number(),
      on_order: z.number(),
      available_stock: z.number(),
      days_of_cover: z.number(),
      is_overstock: z.boolean(),
    }),
  ),
}) satisfies z.ZodType<Schemas["InventoryReport"]>;

const competitorGapsSchema = z.object({
  as_of_week: z.number(),
  undercut_threshold: z.number(),
  kvi_price_tolerance: z.number(),
  gaps: z.array(
    z.object({
      region,
      sku_id: z.string(),
      name: z.string(),
      category: z.string(),
      subcategory: z.string(),
      is_kvi: z.boolean(),
      base_price: z.number(),
      competitor_price: z.number(),
      competitor_on_promo: z.boolean(),
      price_week: z.number(),
      cpi: z.number(),
      gap: z.number(),
      undercut: z.boolean(),
    }),
  ),
}) satisfies z.ZodType<Schemas["CompetitorGaps"]>;

export type Product = z.infer<typeof productSchema>;
export type RegionStores = z.infer<typeof regionStoresSchema>;
export type InventoryReport = z.infer<typeof inventoryReportSchema>;
export type InventoryRow = InventoryReport["statuses"][number];
export type CompetitorGaps = z.infer<typeof competitorGapsSchema>;
export type CompetitorGap = CompetitorGaps["gaps"][number];

export class CatalogRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CatalogRequestError";
  }
}

// Each list loads once, unfiltered: the page filters in the browser (ADR 0034).
export async function listProducts(
  fetchImpl: typeof fetch = fetch,
): Promise<Product[]> {
  const path = "/api/catalog/products";
  const schema = z.object({ products: z.array(productSchema) });
  return (await read(path, schema, fetchImpl)).products;
}

export async function listRegions(
  fetchImpl: typeof fetch = fetch,
): Promise<RegionStores[]> {
  const path = "/api/catalog/regions";
  const schema = z.object({ regions: z.array(regionStoresSchema) });
  return (await read(path, schema, fetchImpl)).regions;
}

export function getInventory(
  fetchImpl: typeof fetch = fetch,
): Promise<InventoryReport> {
  return read("/api/inventory", inventoryReportSchema, fetchImpl);
}

// Without options: the data's default as-of week and every SKU (ADR 0034). The
// session page asks for its request's as-of week and KVIs only (ADR 0060).
export function getCompetitorGaps(
  fetchImpl: typeof fetch = fetch,
  options: { asOfWeek?: number; kviOnly?: boolean } = {},
): Promise<CompetitorGaps> {
  const query = new URLSearchParams();
  if (options.asOfWeek !== undefined) {
    query.set("as_of_week", String(options.asOfWeek));
  }
  if (options.kviOnly) query.set("kvi_only", "true");
  const search = query.size > 0 ? `?${query}` : "";
  return read(
    `/api/competitors/gaps${search}`,
    competitorGapsSchema,
    fetchImpl,
  );
}

// Through the same-origin `/api/*` proxy (ADR 0018). Throws the API's reason
// (e.g. the 409 "run `make data`"), or the status when it gives none, so
// TanStack Query can surface it; network errors propagate as they are.
async function read<T>(
  path: string,
  schema: z.ZodType<T>,
  fetchImpl: typeof fetch,
): Promise<T> {
  const response = await fetchImpl(path, { cache: "no-store" });
  if (!response.ok)
    throw new CatalogRequestError(await responseReason(response));
  const parsed = schema.safeParse(await response.json());
  if (!parsed.success) {
    throw new CatalogRequestError(`unexpected response from ${path}`);
  }
  return parsed.data;
}
