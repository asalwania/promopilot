"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useId, useState } from "react";

import {
  GapsTable,
  InventoryTable,
  ProductsTable,
} from "@/components/data-tables";
import { UndercutCallout } from "@/components/undercut-callout";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  getCompetitorGaps,
  getInventory,
  listProducts,
  listRegions,
} from "@/lib/api/catalog";
import { formatWeek } from "@/lib/format";

const MAX_RETRIES = 2;

type Filters = {
  region: string;
  category: string;
  overstockedOnly: boolean;
  undercutOnly: boolean;
};

const ALL = "";

// The `/data` explorer (ADR 0034): products, inventory and competitor gaps as
// three stacked cards. Each list loads once, unfiltered, when the page opens;
// one shared filter bar narrows them in the browser.
export function DataView() {
  const products = useQuery({
    queryKey: ["catalog", "products"],
    queryFn: () => listProducts(),
    retry: MAX_RETRIES,
  });
  const regions = useQuery({
    queryKey: ["catalog", "regions"],
    queryFn: () => listRegions(),
    retry: MAX_RETRIES,
  });
  const inventory = useQuery({
    queryKey: ["inventory"],
    queryFn: () => getInventory(),
    retry: MAX_RETRIES,
  });
  const gaps = useQuery({
    queryKey: ["competitors", "gaps"],
    queryFn: () => getCompetitorGaps(),
    retry: MAX_RETRIES,
  });
  const [filters, setFilters] = useState<Filters>({
    region: ALL,
    category: ALL,
    overstockedOnly: false,
    undercutOnly: false,
  });

  const inRegion = (region: string) =>
    filters.region === ALL || region === filters.region;
  const inCategory = (category: string) =>
    filters.category === ALL || category === filters.category;

  return (
    <div className="flex w-full flex-col gap-6">
      <FilterBar
        filters={filters}
        onChange={setFilters}
        regions={regions.data?.map((entry) => entry.region) ?? []}
        categories={[
          ...new Set(products.data?.map((product) => product.category)),
        ].sort()}
      />
      {inventory.data && (
        <p
          className="text-muted-foreground text-sm"
          title="Source: get_inventory_status"
        >
          As of {formatWeek(inventory.data.as_of_week)} · stock at end of{" "}
          {formatWeek(inventory.data.snapshot_week)} · overstock above{" "}
          {inventory.data.overstock_threshold_days} days
        </p>
      )}
      <Panel title="Products" noun="products" query={products}>
        {(data) => {
          const rows = data.filter((product) => inCategory(product.category));
          return (
            <Rows
              count={rows.length}
              of={data.length}
              empty="No products match these filters."
            >
              <ProductsTable products={rows} />
            </Rows>
          );
        }}
      </Panel>
      <Panel title="Inventory" noun="inventory" query={inventory}>
        {(data) => {
          const rows = data.statuses.filter(
            (row) =>
              inRegion(row.region) &&
              inCategory(row.category) &&
              (!filters.overstockedOnly || row.is_overstock),
          );
          return (
            <Rows
              count={rows.length}
              of={data.statuses.length}
              empty="No inventory matches these filters."
            >
              <InventoryTable rows={rows} snapshotWeek={data.snapshot_week} />
            </Rows>
          );
        }}
      </Panel>
      <Panel title="Competitor gaps" noun="competitor gaps" query={gaps}>
        {(data) => {
          const rows = data.gaps.filter(
            (gap) =>
              inRegion(gap.region) &&
              inCategory(gap.category) &&
              (!filters.undercutOnly || gap.undercut),
          );
          return (
            <Rows
              count={rows.length}
              of={data.gaps.length}
              empty="No competitor gaps match these filters."
            >
              <UndercutCallout gaps={rows} />
              <GapsTable gaps={rows} asOfWeek={data.as_of_week} />
            </Rows>
          );
        }}
      </Panel>
    </div>
  );
}

function FilterBar({
  filters,
  onChange,
  regions,
  categories,
}: {
  filters: Filters;
  onChange: (filters: Filters) => void;
  regions: string[];
  categories: string[];
}) {
  const id = useId();
  const selectClass =
    "border-input bg-background h-8 rounded-md border px-2 text-sm";
  return (
    <div
      role="group"
      aria-label="Filters"
      className="flex flex-wrap items-center gap-6 text-sm"
    >
      <label htmlFor={`${id}-region`} className="flex items-center gap-2">
        Region
        <select
          id={`${id}-region`}
          className={selectClass}
          value={filters.region}
          onChange={(event) =>
            onChange({ ...filters, region: event.target.value })
          }
        >
          <option value={ALL}>All regions</option>
          {regions.map((region) => (
            <option key={region} value={region}>
              {region}
            </option>
          ))}
        </select>
      </label>
      <label htmlFor={`${id}-category`} className="flex items-center gap-2">
        Category
        <select
          id={`${id}-category`}
          className={selectClass}
          value={filters.category}
          onChange={(event) =>
            onChange({ ...filters, category: event.target.value })
          }
        >
          <option value={ALL}>All categories</option>
          {categories.map((category) => (
            <option key={category} value={category}>
              {category}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={filters.overstockedOnly}
          onChange={(event) =>
            onChange({ ...filters, overstockedOnly: event.target.checked })
          }
        />
        Overstocked only
      </label>
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={filters.undercutOnly}
          onChange={(event) =>
            onChange({ ...filters, undercutOnly: event.target.checked })
          }
        />
        Undercut KVIs only
      </label>
    </div>
  );
}

// A card per list, with its own loading and error states (ADR 0021).
function Panel<T>({
  title,
  noun,
  query,
  children,
}: {
  title: string;
  noun: string;
  query: UseQueryResult<T>;
  children: (data: T) => React.ReactNode;
}) {
  return (
    <Card className="w-full">
      <CardHeader>
        <CardTitle>
          <h2>{title}</h2>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {query.error ? (
          <div role="alert" className="flex items-center justify-between gap-4">
            <div className="text-sm">
              <p className="font-medium">Couldn&apos;t load {noun}</p>
              <p className="text-muted-foreground">{query.error.message}</p>
            </div>
            <Button
              variant="outline"
              disabled={query.isFetching}
              onClick={() => query.refetch()}
            >
              Retry
            </Button>
          </div>
        ) : query.data ? (
          children(query.data)
        ) : (
          <p role="status" className="text-muted-foreground text-sm">
            Loading {noun}…
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Rows({
  count,
  of,
  empty,
  children,
}: {
  count: number;
  of: number;
  empty: string;
  children: React.ReactNode;
}) {
  if (count === 0) {
    return <p className="text-muted-foreground text-sm">{empty}</p>;
  }
  return (
    <>
      <CardDescription>
        Showing {count} of {of}
      </CardDescription>
      {children}
    </>
  );
}
