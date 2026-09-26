# The data explorer loads flat lists once, filters them in the browser, and names each number's source tool

E10 (#68) adds `/data`, a simple data explorer for products, inventory with overstock flags and competitor gaps (SPEC §11). It also adds the three missing SPEC §10 endpoints: `GET /api/catalog/products`, `GET /api/catalog/regions` and `GET /api/inventory`. The spec gives only their purpose. It does not give their parameters or shapes, the page layout, the columns, how overstock and undercuts stand out, which as-of week the page shows, or how a number names its source before #60 builds the shared component. We chose these with the owner:

- **The endpoints are flat and unpaginated.**
  - The largest list has 200 SKUs × 4 regions = 800 rows, so paging would only add work.
  - **`GET /api/catalog/products`** returns `{products: [...]}` in SKU order, one row per product: `sku_id`, `name`, `brand`, `category`, `subcategory`, `pack_size`, `base_price`, `unit_cost`, `is_kvi`. Optional filters are `category` and `kvi_only`. An unknown category is `422`.
  - **`GET /api/catalog/regions`** returns `{regions: [{region, stores: [{store_id, city, segment_mix}]}]}`, in region order. We rejected a pooled mix per region, which nobody asked for.
  - **`GET /api/inventory`** returns `get_inventory_status`'s output: `as_of_week`, `snapshot_week`, `overstock_threshold_days` and one row per SKU × region.
    - Each row also carries the SKU's `name` and `category`, so the table needs no join. We rejected a client-side join with the products list.
    - Optional filters are `region`, `category`, `overstocked_only` and `as_of_week`. The as-of week defaults to the data's default as-of week, as `GET /api/competitors/gaps` does (ADR 0031).
    - With no data loaded, or no stock snapshot for the week, it is `409`. An unknown category, or a region with no stores, is `422`.
- **The endpoints reuse the data tools.**
  - Products come from `get_scope_data` and inventory from `get_inventory_status`, called directly with a fixed as-of week (ADR 0032).
  - So the explorer shows exactly the filters, pooling, days of cover and overstock flag the planner sees.
  - `promopilot.api.catalog` owns the routes. The LLM never sees these endpoints.
- **The page is three stacked cards: Products, Inventory and Competitor gaps.** We rejected tabs, which would need a new Tabs component and would hide two of the three lists.
- **Each list loads once, unfiltered, when the page opens.**
  - One shared filter bar narrows the lists in the browser. It has Region and Category selects, an "Overstocked only" toggle and an "Undercut KVIs only" toggle.
  - Region applies to inventory and gaps, since products have no region. Category applies to all three lists.
  - The Region select lists `GET /api/catalog/regions`; the Category select lists the products' categories.
  - We rejected refetching from the server on every filter change: 800 rows filter instantly in the browser.
- **Each card has its own loading and error states.** A failed read retries twice, then shows "Couldn't load …" with the API's reason and a Retry button, as `/models` does (ADR 0030). The other cards still render.
- **Columns.**
  - **Products:** SKU, name, brand, category / subcategory, pack, base price, unit cost, and a KVI badge.
  - **Inventory:** SKU, name, region, on hand, safety stock, on order, available, days of cover (1 decimal), and status.
  - **Competitor gaps:** SKU, name, region, our base price, competitor price (with an "On promo" badge), price week, CPI (3 decimals), gap (% to 1 decimal), and status.
  - Prices show paise, as `UndercutCallout` does.
- **Status badges highlight rows.**
  - "Overstocked" and "Undercut" appear in each table's status column.
  - `UndercutCallout` (ADR 0031) sits above the gaps table and lists the filtered undercut KVIs.
  - We rejected tinted rows, which are hard to read in a long table and invisible to screen readers.
- **There is no week picker.** A caption under the filters reads "As of W105 · stock at end of W104 · overstock above 56 days", from the inventory response. The page always shows the data's default as-of week; the API keeps `as_of_week` for people and scripts.
- **A shared `SourcedNumber` names the source tool of every number (SPEC §11 UX rule).**
  - Its props are generic: `value`, an optional `format`, the `source` tool's name and an optional `detail`.
  - Its tooltip reads, for example, "Source: get_inventory_status · stock at end of W104".
  - The explorer's numbers name `get_scope_data`, `get_inventory_status` or `get_competitor_gaps`, and #60's plan table reuses the component.
  - It uses the native `title` tooltip, which keeps an 800-row table light. #60 may swap in a richer tooltip behind the same props.
- **The header nav gains a Data link** next to Home and Models (ADR 0030).

## Consequences

- The explorer and the planner cannot disagree about stock or overstock: both read through `get_inventory_status`.
- A reader can open the explorer at an earlier as-of week only through the API, not the page.
- If the catalogue grows past a few thousand rows, the lists will need server-side filtering and paging.
