import { SourcedNumber } from "@/components/sourced-number";
import { Badge } from "@/components/ui/badge";
import type { CompetitorGap, InventoryRow, Product } from "@/lib/api/catalog";
import { formatPrice, formatWeek } from "@/lib/format";

// The `/data` explorer's tables: presentational, from already-filtered rows
// (ADR 0034). Every number names the tool that computes it for the planner.

const fixed = (digits: number) => (value: number) => value.toFixed(digits);
const percent = (value: number) => `${(value * 100).toFixed(1)}%`;

export function ProductsTable({ products }: { products: Product[] }) {
  const source = "get_scope_data";
  return (
    <DataTable
      label="Products"
      columns={[
        "SKU",
        "Name",
        "Brand",
        "Category",
        "Pack",
        { label: "Base price", numeric: true },
        { label: "Unit cost", numeric: true },
        "KVI",
      ]}
    >
      {products.map((product) => (
        <tr key={product.sku_id} className="border-b">
          <Cell>{product.sku_id}</Cell>
          <Cell>{product.name}</Cell>
          <Cell>{product.brand}</Cell>
          <Cell>
            {product.category} / {product.subcategory}
          </Cell>
          <Cell>{product.pack_size}</Cell>
          <Cell numeric>
            <SourcedNumber
              value={product.base_price}
              format={formatPrice}
              source={source}
            />
          </Cell>
          <Cell numeric>
            <SourcedNumber
              value={product.unit_cost}
              format={formatPrice}
              source={source}
            />
          </Cell>
          <Cell>
            {product.is_kvi && <Badge variant="secondary">KVI</Badge>}
          </Cell>
        </tr>
      ))}
    </DataTable>
  );
}

export function InventoryTable({
  rows,
  snapshotWeek,
}: {
  rows: InventoryRow[];
  snapshotWeek: number;
}) {
  const sourced = {
    source: "get_inventory_status",
    detail: `stock at end of ${formatWeek(snapshotWeek)}`,
  };
  return (
    <DataTable
      label="Inventory"
      columns={[
        "SKU",
        "Name",
        "Region",
        { label: "On hand", numeric: true },
        { label: "Safety stock", numeric: true },
        { label: "On order", numeric: true },
        { label: "Available", numeric: true },
        { label: "Days of cover", numeric: true },
        "Status",
      ]}
    >
      {rows.map((row) => (
        <tr key={`${row.sku_id}-${row.region}`} className="border-b">
          <Cell>{row.sku_id}</Cell>
          <Cell>{row.name}</Cell>
          <Cell>{row.region}</Cell>
          <Cell numeric>
            <SourcedNumber value={row.on_hand} {...sourced} />
          </Cell>
          <Cell numeric>
            <SourcedNumber value={row.safety_stock} {...sourced} />
          </Cell>
          <Cell numeric>
            <SourcedNumber value={row.on_order} {...sourced} />
          </Cell>
          <Cell numeric>
            <SourcedNumber value={row.available_stock} {...sourced} />
          </Cell>
          <Cell numeric>
            <SourcedNumber
              value={row.days_of_cover}
              format={fixed(1)}
              {...sourced}
            />
          </Cell>
          <Cell>
            {row.is_overstock && (
              <Badge variant="destructive">Overstocked</Badge>
            )}
          </Cell>
        </tr>
      ))}
    </DataTable>
  );
}

export function GapsTable({
  gaps,
  asOfWeek,
}: {
  gaps: CompetitorGap[];
  asOfWeek: number;
}) {
  const sourced = {
    source: "get_competitor_gaps",
    detail: `as of ${formatWeek(asOfWeek)}`,
  };
  return (
    <DataTable
      label="Competitor gaps"
      columns={[
        "SKU",
        "Name",
        "Region",
        { label: "Our price", numeric: true },
        { label: "Competitor price", numeric: true },
        { label: "Price week", numeric: true },
        { label: "CPI", numeric: true },
        { label: "Gap", numeric: true },
        "Status",
      ]}
    >
      {gaps.map((gap) => (
        <tr key={`${gap.sku_id}-${gap.region}`} className="border-b">
          <Cell>{gap.sku_id}</Cell>
          <Cell>{gap.name}</Cell>
          <Cell>{gap.region}</Cell>
          <Cell numeric>
            <SourcedNumber
              value={gap.base_price}
              format={formatPrice}
              {...sourced}
            />
          </Cell>
          <Cell numeric>
            <span className="inline-flex items-center gap-2">
              <SourcedNumber
                value={gap.competitor_price}
                format={formatPrice}
                {...sourced}
              />
              {gap.competitor_on_promo && (
                <Badge variant="outline">On promo</Badge>
              )}
            </span>
          </Cell>
          <Cell numeric>
            <SourcedNumber
              value={gap.price_week}
              format={formatWeek}
              {...sourced}
            />
          </Cell>
          <Cell numeric>
            <SourcedNumber value={gap.cpi} format={fixed(3)} {...sourced} />
          </Cell>
          <Cell numeric>
            <SourcedNumber value={gap.gap} format={percent} {...sourced} />
          </Cell>
          <Cell>
            {gap.undercut && <Badge variant="destructive">Undercut</Badge>}
          </Cell>
        </tr>
      ))}
    </DataTable>
  );
}

type Column = string | { label: string; numeric: true };

function DataTable({
  label,
  columns,
  children,
}: {
  label: string;
  columns: Column[];
  children: React.ReactNode;
}) {
  return (
    <div className="max-h-[32rem] overflow-auto">
      <table aria-label={label} className="w-full text-sm">
        <thead className="bg-card sticky top-0">
          <tr className="border-b">
            {columns.map((column) => {
              const { label: text, numeric } =
                typeof column === "string"
                  ? { label: column, numeric: false }
                  : column;
              return (
                <th
                  key={text}
                  scope="col"
                  className={`text-muted-foreground px-2 py-2 font-medium ${numeric ? "text-right" : "text-left"}`}
                >
                  {text}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function Cell({
  numeric = false,
  children,
}: {
  numeric?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <td className={`px-2 py-2 ${numeric ? "text-right tabular-nums" : ""}`}>
      {children}
    </td>
  );
}
