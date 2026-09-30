# PromoPilot API

Generated from [`docs/openapi.json`](openapi.json) by `make api-types` (`make api-docs` alone rewrites this page from the committed contract). Do not edit it by hand: change the API, run `make api-types` and commit the result. CI fails when this page drifts from the contract ([ADR 0082](adr/0082-api-docs-generated-from-the-contract.md)).

Version 0.1.0, OpenAPI 3.1.0. With the API running, its interactive docs are at http://localhost:8000/docs.

## Errors

Every error response's body is [ErrorResponse](#errorresponse): a sentence to show (`detail`), a `code`, the request's `reference_id` and, for a 422, every problem (`errors`). Its `code` is one of `bad_request`, `not_found`, `conflict`, `payload_too_large`, `validation_failed`, `rate_limited`, `internal_error`, `api_unreachable`, `unavailable`, `timeout`.

The README's [Errors, limits and timeouts](../README.md#errors-limits-and-timeouts) explains each code, the input limits, the timeouts and the rate limits ([ADR 0071](adr/0071-one-error-schema-input-limits-and-timeouts.md), [ADR 0079](adr/0079-briefs-are-data-and-per-client-rate-limits.md)).

These operations are rate-limited per client and answer `429` with a `Retry-After` header when a client is over its limit:

- [`POST /api/sessions`](#post-apisessions)
- [`POST /api/sessions/{session_id}/amend`](#post-apisessionssession_idamend)
- [`POST /api/sessions/{session_id}/clarify`](#post-apisessionssession_idclarify)
- [`POST /api/plans/{session_id}/simulate`](#post-apiplanssession_idsimulate)

## Endpoints

| Method | Path | Summary |
| --- | --- | --- |
| `GET` | [`/api/health`](#get-apihealth) | Health |
| `GET` | [`/health`](#get-health) | Health |
| `POST` | [`/api/sessions`](#post-apisessions) | Create Session |
| `GET` | [`/api/sessions/{session_id}`](#get-apisessionssession_id) | Get Session |
| `POST` | [`/api/sessions/{session_id}/amend`](#post-apisessionssession_idamend) | Amend Session |
| `POST` | [`/api/sessions/{session_id}/approve`](#post-apisessionssession_idapprove) | Approve Session |
| `POST` | [`/api/sessions/{session_id}/clarify`](#post-apisessionssession_idclarify) | Clarify Session |
| `GET` | [`/api/sessions/{session_id}/events`](#get-apisessionssession_idevents) | Session Events |
| `POST` | [`/api/sessions/{session_id}/reject`](#post-apisessionssession_idreject) | Reject Session |
| `POST` | [`/api/plans/{session_id}/simulate`](#post-apiplanssession_idsimulate) | Simulate Plan |
| `GET` | [`/api/catalog/products`](#get-apicatalogproducts) | List Products |
| `GET` | [`/api/catalog/regions`](#get-apicatalogregions) | List Regions |
| `GET` | [`/api/inventory`](#get-apiinventory) | Inventory |
| `GET` | [`/api/competitors/gaps`](#get-apicompetitorsgaps) | Competitor Gaps |
| `GET` | [`/api/relations/{sku_id}`](#get-apirelationssku_id) | Get Relations |
| `GET` | [`/api/models`](#get-apimodels) | List Models |
| `POST` | [`/api/models/retrain`](#post-apimodelsretrain) | Retrain |
| `GET` | [`/api/evals/latest`](#get-apievalslatest) | Latest |

### Health

#### `GET /api/health`

**Health**

**Responses**

| Status | Description | Body | Headers |
| --- | --- | --- | --- |
| 200 | Successful Response | [HealthResponse](#healthresponse) |  |

#### `GET /health`

**Health**

**Responses**

| Status | Description | Body | Headers |
| --- | --- | --- | --- |
| 200 | Successful Response | [HealthResponse](#healthresponse) |  |

### Sessions

#### `POST /api/sessions`

**Create Session**

**Request body** (required): [CreateSessionRequest](#createsessionrequest)

**Responses**

| Status | Description | Body | Headers |
| --- | --- | --- | --- |
| 202 | Successful Response | [SessionCreated](#sessioncreated) |  |
| 413 | The request body is larger than MAX_REQUEST_BODY_BYTES | [ErrorResponse](#errorresponse) |  |
| 422 | Validation Error | [ErrorResponse](#errorresponse) |  |
| 429 | Too many requests from this client (RATE_LIMIT_*_PER_MINUTE) | [ErrorResponse](#errorresponse) | `Retry-After` (integer): Whole seconds until the client may send this request again. |
| 503 | Planning is unavailable | [ErrorResponse](#errorresponse) |  |

#### `GET /api/sessions/{session_id}`

**Get Session**

**Parameters**

| Name | In | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `session_id` | path | string (uuid) | yes |  |  |

**Responses**

| Status | Description | Body | Headers |
| --- | --- | --- | --- |
| 200 | Successful Response | [SessionResponse](#sessionresponse) |  |
| 404 | Unknown session | [ErrorResponse](#errorresponse) |  |
| 422 | Validation Error | [ErrorResponse](#errorresponse) |  |

#### `POST /api/sessions/{session_id}/amend`

**Amend Session**

Amend the planning request (AG-05); a new plan revision, with its diff from the
previous one, is planned in the background.

**Parameters**

| Name | In | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `session_id` | path | string (uuid) | yes |  |  |

**Request body** (required): [AmendRequest](#amendrequest)

**Responses**

| Status | Description | Body | Headers |
| --- | --- | --- | --- |
| 202 | Successful Response | [SessionResponse](#sessionresponse) |  |
| 404 | Unknown session | [ErrorResponse](#errorresponse) |  |
| 409 | The session is not awaiting approval or rejected, or (accept_relaxation) its latest revision has no relaxation | [ErrorResponse](#errorresponse) |  |
| 413 | The request body is larger than MAX_REQUEST_BODY_BYTES | [ErrorResponse](#errorresponse) |  |
| 422 | Validation Error | [ErrorResponse](#errorresponse) |  |
| 429 | Too many requests from this client (RATE_LIMIT_*_PER_MINUTE) | [ErrorResponse](#errorresponse) | `Retry-After` (integer): Whole seconds until the client may send this request again. |
| 503 | Planning is unavailable | [ErrorResponse](#errorresponse) |  |

#### `POST /api/sessions/{session_id}/approve`

**Approve Session**

Approve the session's latest plan revision, which makes it final (SF-04).

**Parameters**

| Name | In | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `session_id` | path | string (uuid) | yes |  |  |

**Request body** (required): [ApproveRequest](#approverequest)

**Responses**

| Status | Description | Body | Headers |
| --- | --- | --- | --- |
| 200 | Successful Response | [SessionResponse](#sessionresponse) |  |
| 404 | Unknown session | [ErrorResponse](#errorresponse) |  |
| 409 | The session is not awaiting approval, the revision is not its latest, or (approve) the revision is infeasible | [ErrorResponse](#errorresponse) |  |
| 413 | The request body is larger than MAX_REQUEST_BODY_BYTES | [ErrorResponse](#errorresponse) |  |
| 422 | Validation Error | [ErrorResponse](#errorresponse) |  |
| 503 | Planning is unavailable | [ErrorResponse](#errorresponse) |  |

#### `POST /api/sessions/{session_id}/clarify`

**Clarify Session**

Answer the open clarification questions; planning resumes in the background.

**Parameters**

| Name | In | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `session_id` | path | string (uuid) | yes |  |  |

**Request body** (required): [ClarifyRequest](#clarifyrequest)

**Responses**

| Status | Description | Body | Headers |
| --- | --- | --- | --- |
| 202 | Successful Response | [SessionResponse](#sessionresponse) |  |
| 404 | Unknown session | [ErrorResponse](#errorresponse) |  |
| 409 | The session is not awaiting clarification | [ErrorResponse](#errorresponse) |  |
| 413 | The request body is larger than MAX_REQUEST_BODY_BYTES | [ErrorResponse](#errorresponse) |  |
| 422 | Validation Error | [ErrorResponse](#errorresponse) |  |
| 429 | Too many requests from this client (RATE_LIMIT_*_PER_MINUTE) | [ErrorResponse](#errorresponse) | `Retry-After` (integer): Whole seconds until the client may send this request again. |
| 503 | Planning is unavailable | [ErrorResponse](#errorresponse) |  |

#### `GET /api/sessions/{session_id}/events`

**Session Events**

The session's trace events over SSE (SF-01, ADR 0047), in order, as they happen.

Each event's SSE `id` is its number in the session; a client that reconnects with
`Last-Event-ID` gets the events after it, with no gaps or repeats (a missing or
non-numeric one replays the trace from the start). Once the session is final
(approved, or failed) the stream sends `event: end` with its status and closes.

**Parameters**

| Name | In | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `session_id` | path | string (uuid) | yes |  |  |
| `last-event-id` | header | string or null | no |  |  |

**Responses**

| Status | Description | Body | Headers |
| --- | --- | --- | --- |
| 200 | Successful Response | `text/event-stream`: each event's `data` is [TraceEvent](#traceevent) or [TraceStreamEnd](#tracestreamend) |  |
| 404 | Unknown session | [ErrorResponse](#errorresponse) |  |
| 422 | Validation Error | [ErrorResponse](#errorresponse) |  |

#### `POST /api/sessions/{session_id}/reject`

**Reject Session**

Reject the session's latest plan revision with a reason; the session stays open.

**Parameters**

| Name | In | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `session_id` | path | string (uuid) | yes |  |  |

**Request body** (required): [RejectRequest](#rejectrequest)

**Responses**

| Status | Description | Body | Headers |
| --- | --- | --- | --- |
| 200 | Successful Response | [SessionResponse](#sessionresponse) |  |
| 404 | Unknown session | [ErrorResponse](#errorresponse) |  |
| 409 | The session is not awaiting approval, the revision is not its latest, or (approve) the revision is infeasible | [ErrorResponse](#errorresponse) |  |
| 413 | The request body is larger than MAX_REQUEST_BODY_BYTES | [ErrorResponse](#errorresponse) |  |
| 422 | Validation Error | [ErrorResponse](#errorresponse) |  |
| 503 | Planning is unavailable | [ErrorResponse](#errorresponse) |  |

### Plans

#### `POST /api/plans/{session_id}/simulate`

**Simulate Plan**

Re-simulate the session's latest plan revision and store the result against it.

**Parameters**

| Name | In | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `session_id` | path | string (uuid) | yes |  |  |

**Request body** (required): [SimulatePlanRequest](#simulateplanrequest)

**Responses**

| Status | Description | Body | Headers |
| --- | --- | --- | --- |
| 200 | Successful Response | [PlanSimulationResponse](#plansimulationresponse) |  |
| 404 | Unknown session, or a session without a plan revision yet | [ErrorResponse](#errorresponse) |  |
| 409 | The session is approved, so its plan is final, or the latest demand model cannot simulate the stored plan | [ErrorResponse](#errorresponse) |  |
| 413 | The request body is larger than MAX_REQUEST_BODY_BYTES | [ErrorResponse](#errorresponse) |  |
| 422 | Validation Error | [ErrorResponse](#errorresponse) |  |
| 429 | Too many requests from this client (RATE_LIMIT_*_PER_MINUTE) | [ErrorResponse](#errorresponse) | `Retry-After` (integer): Whole seconds until the client may send this request again. |
| 503 | No trained demand model, or no inventory snapshot for the planning request's as-of week | [ErrorResponse](#errorresponse) |  |
| 504 | The simulation took longer than TOOL_TIMEOUT_SECONDS | [ErrorResponse](#errorresponse) |  |

### Catalog

#### `GET /api/catalog/products`

**List Products**

Every product in SKU order; an unknown category is 422.

**Parameters**

| Name | In | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `category` | query | string or null | no | maxLength 64 |  |
| `kvi_only` | query | boolean | no | default `false` |  |

**Responses**

| Status | Description | Body | Headers |
| --- | --- | --- | --- |
| 200 | Successful Response | [ProductList](#productlist) |  |
| 422 | Validation Error | [ErrorResponse](#errorresponse) |  |

#### `GET /api/catalog/regions`

**List Regions**

Each region's stores with their customer segment mix.

**Responses**

| Status | Description | Body | Headers |
| --- | --- | --- | --- |
| 200 | Successful Response | [RegionList](#regionlist) |  |

#### `GET /api/inventory`

**Inventory**

Stock per SKU x region pooled over the region's stores, with overstock flags.

An unknown category, or a region without stores, is 422.

**Parameters**

| Name | In | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `as_of_week` | query | integer or null | no | minimum 0 | Defaults to the data's default as-of week. |
| `region` | query | [Region](#region) or null | no |  |  |
| `category` | query | string or null | no | maxLength 64 |  |
| `overstocked_only` | query | boolean | no | default `false` |  |

**Responses**

| Status | Description | Body | Headers |
| --- | --- | --- | --- |
| 200 | Successful Response | [InventoryReport](#inventoryreport) |  |
| 409 | No data is loaded for the week | [ErrorResponse](#errorresponse) |  |
| 422 | Validation Error | [ErrorResponse](#errorresponse) |  |

### Competitors

#### `GET /api/competitors/gaps`

**Competitor Gaps**

Competitor price index, gap and KVI undercut per SKU x region, widest gap first.

An unknown category is 422.

**Parameters**

| Name | In | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `as_of_week` | query | integer or null | no | minimum 0 | Defaults to the data's default as-of week. |
| `region` | query | [Region](#region) or null | no |  |  |
| `category` | query | string or null | no | maxLength 64 |  |
| `kvi_only` | query | boolean | no | default `false` |  |

**Responses**

| Status | Description | Body | Headers |
| --- | --- | --- | --- |
| 200 | Successful Response | [CompetitorGaps](#competitorgaps) |  |
| 409 | No data is loaded | [ErrorResponse](#errorresponse) |  |
| 422 | Validation Error | [ErrorResponse](#errorresponse) |  |

### Relations

#### `GET /api/relations/{sku_id}`

**Get Relations**

**Parameters**

| Name | In | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- | --- |
| `sku_id` | path | string | yes | maxLength 64 |  |

**Responses**

| Status | Description | Body | Headers |
| --- | --- | --- | --- |
| 200 | Successful Response | [RelationsResponse](#relationsresponse) |  |
| 404 | No such SKU | [ErrorResponse](#errorresponse) |  |
| 422 | Validation Error | [ErrorResponse](#errorresponse) |  |
| 503 | No relations model fitted on the live demand model | [ErrorResponse](#errorresponse) |  |

### Models

#### `GET /api/models`

**List Models**

**Responses**

| Status | Description | Body | Headers |
| --- | --- | --- | --- |
| 200 | Successful Response | [ModelList](#modellist) |  |

#### `POST /api/models/retrain`

**Retrain**

**Responses**

| Status | Description | Body | Headers |
| --- | --- | --- | --- |
| 201 | Successful Response | [ModelEntry](#modelentry) |  |
| 409 | A retrain is running or no data | [ErrorResponse](#errorresponse) |  |

### Evals

#### `GET /api/evals/latest`

**Latest**

**Responses**

| Status | Description | Body | Headers |
| --- | --- | --- | --- |
| 200 | Successful Response | [EvalReport](#evalreport) |  |
| 404 | No eval report this version can read | [ErrorResponse](#errorresponse) |  |

## Schemas

### AmendRequest

Amend the planning request of a session awaiting approval or rejected (ADR 0052): in
plain English, or by accepting the latest revision's relaxation. Exactly one of the two.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `accept_relaxation` | boolean | no | default `false` | Accept the latest plan revision's smallest relaxation (ADR 0044) as the amendment instead of writing one. |
| `text` | string or null | no | maxLength 2000 | The change, in plain English ("cut budget to ₹6 lakh", "drop West"). |

### Amendment

A change to the planning request, in the manager's words, made while a plan revision
waited for a decision (AG-05, ADR 0052). Every amendment is kept, oldest first.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `amended_at` | string (date-time) | yes |  |  |
| `amends_revision` | integer | yes | minimum 1 |  |
| `relaxation` | [Relaxation](#relaxation) or null | no |  |  |
| `text` | string | yes |  |  |

### ApproveRequest

Approve a plan revision: it must be the session's latest (ADR 0046).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `revision_number` | integer | yes | minimum 1 | The plan revision being approved. |

### Assumption

One planning-request field (or a fact the plan relies on) as the agent read or inferred
it: its value in words, where it came from and how sure the agent is (ADR 0048).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `confidence` | number | yes | minimum 0, maximum 1 |  |
| `fallback` | boolean | no | default `false` |  |
| `field` | string | yes |  |  |
| `flagged` | boolean | no | default `false` |  |
| `note` | string or null | no |  |  |
| `source` | [AssumptionSource](#assumptionsource) | yes |  |  |
| `value` | string | yes |  |  |

### AssumptionSource

Where an assumed value came from.

string, one of `brief`, `data`, `default`.

### BestPlanSummary

The best plan (ADR 0063): our optimiser run on true-parameter predictions.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `lines` | integer | yes |  |  |
| `objective` | number or null | yes |  |  |
| `sku_ids` | array of string | yes |  |  |
| `solver_status` | [SolveStatus](#solvestatus) | yes |  |  |

### BindingConstraint

A constraint that limits the plan: dropping it gives a strictly better objective, or,
when time ran out, one that may.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `category` | string or null | no |  |  |
| `evidence` | [BindingEvidence](#bindingevidence) | yes |  |  |
| `kind` | [ConstraintKind](#constraintkind) | yes |  |  |
| `limit` | number | yes |  |  |
| `objective_gain` | number or null | yes |  |  |
| `region` | [Region](#region) or null | no |  |  |
| `sku_id` | string or null | no |  |  |
| `source` | [ConstraintSource](#constraintsource) | yes |  |  |

### BindingEvidence

How sure the optimiser is that a constraint binds (ADR 0038).

string, one of `exact`, `lower_bound`, `unproven`, `infeasible`.

### Breach

A constraint the plan's true outcome breaks, by the oracle (ADR 0012).

string, one of `promo_cost_over_budget`, `margin_below_minimum`, `demand_over_stock`.

### Clarification

A question the agent asked and the manager's answer, in their own words.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `answer` | string | yes |  |  |
| `question` | [ClarificationQuestion](#clarificationquestion) | yes |  |  |

### ClarificationAsked

The Context agent paused to ask the manager these questions.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `kind` | string | no | always `clarification`, default `clarification` |  |
| `questions` | array of string | yes |  |  |

### ClarificationCheck

Whether a vague or conflicting scenario's session asked about, or flagged, a field the
scenario names (#55).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `asked` | array of string | yes |  |  |
| `flagged` | array of string | yes |  |  |
| `named` | array of string | yes |  |  |
| `passed` | boolean | yes |  |  |

### ClarificationQuestion

A specific question the agent asks instead of guessing (AG-02).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `field` | string | yes |  |  |
| `id` | string | yes |  |  |
| `question` | string | yes |  |  |
| `reason` | [QuestionReason](#questionreason) | yes |  |  |
| `suggestions` | array of string | no | default `[]` |  |

### ClarifyRequest

Answers to the session's open clarification questions (ADR 0048).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `answers` | map of string to string | yes | minProperties 1, maxProperties 20, keys maxLength 64, values maxLength 2000 | An answer in plain English for every open question, keyed by its id. |

### ClearanceShortfall

A clearance target the plan misses: no plan within the other constraints reaches it,
so the optimiser returned the plan that comes closest and reports by how much it falls
short (SPEC §9.4, F-06 AC2, ADR 0040).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `expected_sell_through` | number | yes |  |  |
| `region` | [Region](#region) | yes |  |  |
| `shortfall_units` | number | yes |  |  |
| `sku_id` | string | yes |  |  |
| `target` | number | yes |  |  |

### ClearanceTarget

The minimum sell-through the brief asks for a SKU it names for clearance, in every
region of the scope (ADR 0014, ADR 0040).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `sell_through` | number | yes | exclusiveMinimum 0, maximum 1 |  |
| `sku_id` | string | yes |  |  |

### CompetitorGap

One SKU in one region against the competitor's latest price before the as-of week.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `base_price` | number | yes |  | Our regular shelf price in rupees. |
| `category` | string | yes |  |  |
| `competitor_on_promo` | boolean | yes |  | Whether that price was a competitor promo. |
| `competitor_price` | number | yes |  | The competitor's latest price in rupees. |
| `cpi` | number | yes |  | Competitor price index: competitor price ÷ base price. |
| `gap` | number | yes |  | 1 minus CPI: how much cheaper the competitor is (< 0: dearer). |
| `is_kvi` | boolean | yes |  |  |
| `name` | string | yes |  |  |
| `price_week` | integer | yes | minimum 0 | The week of that price, before the as-of week. |
| `region` | [Region](#region) | yes |  |  |
| `sku_id` | string | yes |  |  |
| `subcategory` | string | yes |  |  |
| `undercut` | boolean | yes |  | A KVI whose CPI is below 1 minus the undercut threshold. |

### CompetitorGaps

The gaps for a scope, widest first, with the company-policy rules they were judged by.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `as_of_week` | integer | yes | minimum 0 |  |
| `gaps` | array of [CompetitorGap](#competitorgap) | yes |  |  |
| `kvi_price_tolerance` | number | yes |  | How far above the competitor a KVI promo price may sit, when enabled. |
| `undercut_threshold` | number | yes |  |  |

### CompetitorReaction

The competitor-reaction scenario (F-09 AC2, ADR 0045): in each run, each plan line's
competitor matches its discount with this probability, independently of the other lines.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `match_probability` | number | yes | minimum 0, maximum 1 | Chance, per plan line and run, that the competitor matches our discount. |

### Complement

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `lift` | number | yes |  | P(both in a basket) / (P(one) x P(other)). |
| `sku_id` | string | yes |  |  |
| `std_error` | number or null | yes |  |  |
| `support` | number | yes |  | Share of baskets holding both SKUs. |
| `theta` | number or null | yes |  | Cross-price effect, or null if not estimable. |

### ConstraintCheck

The final plan revision's hard constraints on its plan-time values (ADR 0012).

string, one of `passed`, `failed`, `infeasible`, `no_plan`.

### ConstraintKind

A plan-level constraint the optimiser enforces (ADR 0036, ADR 0038).

string, one of `marketing_budget`, `minimum_margin`, `margin_floor`, `max_promoted_skus`, `regional_budget`, `clearance_target`, `kvi_price_tolerance`, `strong_substitutes`.

### ConstraintSource

Who set a constraint: only the brief's constraints may be relaxed (ADR 0007).

string, one of `brief`, `company_policy`.

### CreateSessionRequest

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `brief` | string | yes | maxLength 2000 | The brief, in plain English. |

### DecisionKind

string, one of `approved`, `rejected`.

### DecisionMade

A decision taken in the graph: a route a node chose, or a human's approve or reject.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `decision` | string | yes |  |  |
| `kind` | string | no | always `decision`, default `decision` |  |
| `summary` | string | yes |  |  |

### DefaultPlanSummary

The default sequence's plan for the same final request (ADR 0078): our optimiser on
the scenario's fitted models, as the best plan is on the true parameters.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `lines` | integer | yes |  |  |
| `objective` | number | yes |  |  |
| `sku_ids` | array of string | yes |  |  |
| `solver_status` | [SolveStatus](#solvestatus) | yes |  |  |

### DemoRecording

string, one of `recorded`, `not_in_demo_recordings`.

### ErrorResponse

What every API error answers (ADR 0071).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `code` | string | yes | one of `bad_request`, `not_found`, `conflict`, `payload_too_large`, `validation_failed`, `rate_limited`, `internal_error`, `api_unreachable`, `unavailable`, `timeout` | The kind of error, set by the HTTP status. |
| `detail` | string | yes |  | What went wrong, in a sentence to show the user. |
| `errors` | array of [FieldError](#fielderror) or null | no | default `null` | Every problem with the request: a 422's, null otherwise. |
| `reference_id` | string | yes |  | The request's id, also its `X-Request-ID` header: quote it to find the request in the logs. |

### EvalReport

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `generated_at` | string (date-time) | yes |  |  |
| `metrics` | array of [Metric](#metric) | yes |  |  |
| `planning_settings` | object | yes |  |  |
| `provider` | string | yes |  |  |
| `runs_per_scenario` | integer | yes |  |  |
| `scenarios` | array of [ScenarioResult](#scenarioresult) | yes |  |  |
| `world_seed` | integer | yes |  |  |

### ExplainerRun

One run of the Explainer: the explanation a plan revision waited for approval with.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `fallback_reason` | [FallbackReason](#fallbackreason) or null | yes |  |  |
| `revision` | integer | yes |  |  |
| `source` | [ExplanationSource](#explanationsource) | yes |  |  |

### ExplanationSource

string, one of `llm`, `template`.

### FallbackReason

Why the template explained a plan revision instead of the LLM.

string, one of `ungrounded`, `invalid_answer`, `llm_unavailable`.

### FieldError

One problem with the request: where it is, and what is wrong.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `loc` | string | yes |  | Where, e.g. `body.brief` or `path.session_id`. |
| `message` | string | yes |  |  |

### FieldMatch

One labelled planning-request field against what the final request reads (#55).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `expected` | string | yes |  |  |
| `field` | string | yes |  |  |
| `got` | string or null | yes |  |  |
| `matched` | boolean | yes |  |  |

### FindingRaised

Something the Critic found in the plan.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `code` | string | yes |  |  |
| `kind` | string | no | always `finding`, default `finding` |  |
| `message` | string | yes |  |  |
| `source` | string | yes |  |  |

### HealthChecks

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `database` | string | yes | one of `ok`, `error` |  |
| `model_registry` | string | yes | one of `ok`, `missing` |  |

### HealthResponse

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `checks` | [HealthChecks](#healthchecks) | yes |  |  |
| `llm` | [LLMStatus](#llmstatus) | yes |  |  |
| `status` | string | yes | one of `ok`, `degraded` |  |
| `version` | string | yes |  |  |

### InfeasibilityCheck

Whether an infeasible scenario's final revision says so, names what binds and proposes
a relaxation (AG-06, #55).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `binding_named` | boolean | yes |  |  |
| `declared` | boolean | yes |  |  |
| `passed` | boolean | yes |  |  |
| `relaxation` | boolean | yes |  |  |
| `revision` | integer or null | yes |  |  |

### InventoryReport

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `as_of_week` | integer | yes |  |  |
| `overstock_threshold_days` | number | yes |  |  |
| `snapshot_week` | integer | yes |  |  |
| `statuses` | array of [InventoryRow](#inventoryrow) | yes |  |  |

### InventoryRow

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `available_stock` | integer | yes |  |  |
| `category` | string | yes |  |  |
| `days_of_cover` | number | yes |  |  |
| `is_overstock` | boolean | yes |  |  |
| `name` | string | yes |  |  |
| `on_hand` | integer | yes |  |  |
| `on_order` | integer | yes |  |  |
| `region` | [Region](#region) | yes |  |  |
| `safety_stock` | integer | yes |  |  |
| `sku_id` | string | yes |  |  |

### JsonValue

Any JSON value.

### LLMStatus

Which LLM answers the planning agents (ADR 0073): the committed cassettes (`replay`, the
no-key demo) or a live provider and its model.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `mode` | string | yes | one of `replay`, `live` |  |
| `model` | string or null | yes |  | The live provider's model; null when replaying. |
| `provider` | string | yes | one of `replay`, `openai`, `anthropic`, `fake` |  |

### LineChange

A plan line whose SKU and region are in both revisions but whose decision changed.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `after` | [PlanRevisionLine](#planrevisionline) | yes |  |  |
| `before` | [PlanRevisionLine](#planrevisionline) | yes |  |  |
| `fields` | array of string | yes |  |  |
| `region` | [Region](#region) | yes |  |  |
| `sku_id` | string | yes |  |  |

### LineCrossEffect

Another SKU a plan line moves in its region, as the relations calculators give it
(ADR 0033): a fall in profit is cannibalisation, a rise is halo.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `profit_change` | number | yes |  |  |
| `sku_id` | string | yes |  |  |
| `units_change_pct` | number | yes |  |  |

### LineSimulation

One plan line's simulated ranges, identified by its SKU and region.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `gross_profit` | [Percentiles](#percentiles) | yes |  |  |
| `margin` | [Percentiles](#percentiles) | yes |  |  |
| `promo_spend` | [Percentiles](#percentiles) | yes |  |  |
| `region` | [Region](#region) | yes |  |  |
| `revenue` | [Percentiles](#percentiles) | yes |  |  |
| `sell_through` | [Percentiles](#percentiles) or null | yes |  |  |
| `sku_id` | string | yes |  |  |
| `stockout_probability` | number | yes | minimum 0, maximum 1 |  |
| `units` | [Percentiles](#percentiles) | yes |  |  |

### Mechanism

string, one of `PCT_OFF`, `BOGO`, `BUNDLE`, `FIXED_PRICE`.

### MechanismOption

One promo option's expected numbers, as its prediction gave them (rupees, units over
its promo weeks; a BUNDLE's money fields include its partner).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `anchor_sku_id` | string | yes |  |  |
| `basket_lift` | number or null | no |  |  |
| `cannibalised_profit` | number | yes |  |  |
| `clearance_value` | number | yes |  |  |
| `effective_price` | number | yes |  |  |
| `gross_profit` | number | yes |  |  |
| `halo_profit` | number | yes |  |  |
| `incremental_profit` | number | yes |  |  |
| `margin` | number | yes |  |  |
| `option` | [PlanLine](#planline) | yes |  |  |
| `partner_effective_price` | number or null | no |  |  |
| `partner_sku_id` | string or null | no |  |  |
| `promo_cost` | number | yes |  |  |
| `revenue` | number | yes |  |  |
| `units` | number | yes |  |  |
| `value` | number | yes |  |  |

### MechanismOutcome

One mechanism in a comparison: its best option, or why it has none.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `best` | [MechanismOption](#mechanismoption) or null | yes |  |  |
| `chosen` | boolean | no | default `false` |  |
| `mechanism` | [Mechanism](#mechanism) | yes |  |  |
| `unavailable` | array of [PruneReason](#prunereason) | no | default `[]` |  |

### Metric

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `aim` | number or null | no |  |  |
| `breakdown` | map of string to integer | no | default `{}` |  |
| `count` | integer | yes |  |  |
| `direction` | string or null | no | one of `at_least`, `at_most` |  |
| `label` | string | yes |  |  |
| `name` | string | yes |  |  |
| `of` | integer | yes |  |  |
| `passed` | boolean or null | no |  |  |
| `target` | number or null | no |  |  |
| `unit` | string | no | one of `share`, `seconds`, `rupees`, default `share` |  |
| `value` | number or null | yes |  |  |

### ModelEntry

One registered model version; `live` marks the one the API is serving.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `as_of_week` | integer | yes |  |  |
| `kind` | [ModelKind](#modelkind) | yes |  |  |
| `live` | boolean | yes |  |  |
| `metrics` | map of string to number | yes |  |  |
| `model_id` | string (uuid) | yes |  |  |
| `trained_at` | string (date-time) | yes |  |  |
| `version` | integer | yes |  |  |

### ModelKind

string, one of `demand`, `relations`.

### ModelList

Registered models, newest first.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `models` | array of [ModelEntry](#modelentry) | yes |  |  |

### ModelVersion

The registered model that produced the numbers, so a plan can be traced to it.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `as_of_week` | integer | yes |  |  |
| `model_id` | string (uuid) | yes |  |  |
| `version` | integer | yes |  |  |

### NodeFinished

A graph node's run ended.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `duration_ms` | integer | yes | minimum 0 |  |
| `error` | string or null | no |  |  |
| `kind` | string | no | always `node_finished`, default `node_finished` |  |
| `outcome` | [NodeOutcome](#nodeoutcome) | yes |  |  |

### NodeOutcome

How a node's run ended: it finished, paused at an interrupt, or raised.

string, one of `completed`, `interrupted`, `failed`.

### NodeStarted

A graph node started running (again, when an interrupted node resumes).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `kind` | string | no | always `node_started`, default `node_started` |  |

### NotSelectedOption

The best option of a SKU and region with no plan line, and why it was left out.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `cannibalises` | array of string | no | default `[]` |  |
| `option` | [PlanLine](#planline) | yes |  |  |
| `reasons` | array of [NotSelectedReason](#notselectedreason) | yes |  |  |
| `value` | number | yes |  |  |

### NotSelectedReason

Why a promo option is not in the plan: a rule it breaks alone or added to the plan.

string, one of `low_uplift`, `out_of_stock`, `breaks_policy`, `over_budget`, `over_regional_budget`, `breaks_margin`, `max_promoted_skus`, `misses_clearance_target`, `breaks_kvi_tolerance`, `strong_substitute`, `cannibalises`, `time_limit`.

### OpenIssue

One of [Violation](#violation) or [RiskFinding](#riskfinding).

### OracleScore

The final plan's true expected outcome (ADR 0011, ADR 0017).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `blended_margin` | number or null | yes |  |  |
| `breaches` | array of [Breach](#breach) | yes |  |  |
| `clearance_value` | number | yes |  |  |
| `incremental_profit` | number | yes |  |  |
| `promo_cost` | number | yes |  |  |
| `stock_capped_lines` | integer | yes |  |  |

### Percentiles

The 10th, 50th and 90th percentiles of one simulated metric across the runs.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `p10` | number | yes |  |  |
| `p50` | number | yes |  |  |
| `p90` | number | yes |  |  |

### PlanDecision

One human decision on one plan revision: an approval or a rejection with its reason.
Every decision is kept, in order, as the session's audit trail (SF-04, ADR 0046).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `decided_at` | string (date-time) | yes |  |  |
| `decision` | [DecisionKind](#decisionkind) | yes |  |  |
| `reason` | string or null | no |  |  |
| `revision_number` | integer | yes | minimum 1 |  |

### PlanExplanation

What the Explainer wrote for one plan revision.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `changes` | string or null | no |  |  |
| `competitor_response` | array of string | no | default `[]` |  |
| `fallback_reason` | [FallbackReason](#fallbackreason) or null | no |  |  |
| `rationales` | array of string | no | default `[]` |  |
| `source` | [ExplanationSource](#explanationsource) | yes |  |  |
| `summary` | string | yes |  |  |

### PlanLine

A promo option selected into a promo plan: one (SKU, region) decision (ADR 0004).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `bundle_partner_sku_id` | string or null | no |  |  |
| `depth_pct` | integer | yes | minimum 1, maximum 100 |  |
| `duration_weeks` | integer | yes | minimum 1, maximum 4 |  |
| `mechanism` | [Mechanism](#mechanism) | yes |  |  |
| `region` | [Region](#region) | yes |  |  |
| `sku_id` | string | yes |  |  |
| `start_week` | integer | yes | minimum 0 |  |
| `target_segment` | [TargetSegment](#targetsegment) | yes |  |  |

### PlanQuality

A scored final plan against the rule-based baseline and the best plan (ADR 0063), and
its regret by cause against the default sequence's plan (ADR 0078).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `best` | [BestPlanSummary](#bestplansummary) | yes |  |  |
| `breakdown` | [RegretBreakdown](#regretbreakdown) or null | no |  |  |
| `default` | [DefaultPlanSummary](#defaultplansummary) or null | no |  |  |
| `objective` | number | yes |  |  |
| `regret` | number or null | yes |  |  |
| `regret_rupees` | number or null | yes |  |  |
| `rule_based` | [RuleBasedSummary](#rulebasedsummary) | yes |  |  |
| `timed_out` | array of string | no | items one of `best`, `default`, `ours`, default `[]` |  |
| `versus_rule_based` | string | yes | one of `beats`, `ties`, `loses` |  |

### PlanRevision

One numbered version of the promo plan within a planning session.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `binding_constraints` | array of [BindingConstraint](#bindingconstraint) | no | default `[]` |  |
| `clearance_shortfalls` | array of [ClearanceShortfall](#clearanceshortfall) | no | default `[]` |  |
| `diff` | [RevisionDiff](#revisiondiff) or null | no |  |  |
| `explanation` | [PlanExplanation](#planexplanation) or null | no |  |  |
| `lines` | array of [PlanRevisionLine](#planrevisionline) | no | default `[]` |  |
| `not_selected` | array of [NotSelectedOption](#notselectedoption) | no | default `[]` |  |
| `number` | integer | yes | minimum 1 |  |
| `objective` | number or null | no |  |  |
| `open_issues` | array of [OpenIssue](#openissue) | no | default `[]` |  |
| `policy_findings` | array of [PolicyFinding](#policyfinding) | no | default `[]` |  |
| `relaxation` | [Relaxation](#relaxation) or null | no |  |  |
| `safety_margin` | [PlanSafetyMargin](#plansafetymargin) or null | no |  |  |
| `simulation` | [PlanSimulation](#plansimulation) or null | no |  |  |
| `solver_status` | [SolveStatus](#solvestatus) or null | no |  |  |

### PlanRevisionLine

A plan line with the expected numbers the planning tool computed for it (rupees).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `baseline_units` | number or null | no | minimum 0 |  |
| `cross_effects` | array of [LineCrossEffect](#linecrosseffect) | no | default `[]` |  |
| `expected_incremental_profit` | number | yes |  |  |
| `expected_units` | number | yes | minimum 0 |  |
| `line` | [PlanLine](#planline) | yes |  |  |
| `mechanism_comparison` | array of [MechanismOutcome](#mechanismoutcome) | no | default `[]` |  |
| `promo_cost` | number | yes | minimum 0 |  |
| `segments` | array of [SegmentUplift](#segmentuplift) | no | default `[]` |  |
| `uplift_pct` | number or null | no |  |  |
| `why_chosen` | [WhyChosen](#whychosen) or null | no |  |  |

### PlanSafetyMargin

The safety margin a plan revision was planned with, and its promo cost as budgeted.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `budget_margin_waived` | boolean | no | default `false` |  |
| `budget_quantile` | number | no | minimum 0.5, exclusiveMaximum 1, default `0.5` |  |
| `margin_quantile` | number | no | exclusiveMinimum 0, maximum 0.5, default `0.5` |  |
| `planned_promo_cost` | number | yes | minimum 0 |  |
| `stock_sigmas` | number | no | minimum 1.2816, default `1.2816` |  |

### PlanSimulation

What `simulate` returns for a promo plan, and what a plan revision stores.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `competitor_reaction` | [CompetitorReaction](#competitorreaction) or null | no |  |  |
| `lines` | array of [LineSimulation](#linesimulation) | no | default `[]` |  |
| `n_runs` | integer | yes | minimum 1 |  |
| `regions` | array of [RegionStockout](#regionstockout) | no | default `[]` |  |
| `seed` | integer | yes |  |  |
| `total` | [SimulatedOutcomes](#simulatedoutcomes) | yes |  |  |

### PlanSimulationResponse

A plan revision's new simulation, now stored against it in place of the old one.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `as_of_week` | integer | yes |  |  |
| `demand_model` | [ModelVersion](#modelversion) | yes |  |  |
| `revision_number` | integer | yes |  |  |
| `session_id` | string (uuid) | yes |  |  |
| `simulation` | [PlanSimulation](#plansimulation) | yes |  |  |

### PlanningRequest

Money is in rupees (ADR 0015). The brief's optional constraints may only tighten
company policy; a value that would loosen it is kept here as read, and planning applies
the policy value instead and flags it (ADR 0007, ADR 0040).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `as_of_week` | integer | yes | minimum 0 |  |
| `clearance_targets` | array of [ClearanceTarget](#clearancetarget) | no | default `[]` |  |
| `kvi_price_tolerance` | number or null | no | minimum 0, exclusiveMaximum 1 |  |
| `marketing_budget` | number | yes | exclusiveMinimum 0 |  |
| `max_promoted_skus_per_category_per_region` | integer or null | no | minimum 1 |  |
| `min_margin` | number or null | no | minimum 0, exclusiveMaximum 1 |  |
| `promo_window` | [PromoWindow](#promowindow) | yes |  |  |
| `regional_budget_caps` | map of string to number | no |  |  |
| `scope` | [Scope](#scope) | yes |  |  |

### PolicyFinding

A brief value that would loosen company policy: planning keeps the policy value and
flags it (ADR 0007, ADR 0040).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `applied` | number | yes |  |  |
| `field` | string | yes |  |  |
| `message` | string | yes |  |  |
| `requested` | number | yes |  |  |

### Product

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `base_price` | number | yes |  |  |
| `brand` | string | yes |  |  |
| `category` | string | yes |  |  |
| `is_kvi` | boolean | yes |  |  |
| `name` | string | yes |  |  |
| `pack_size` | string | yes |  |  |
| `sku_id` | string | yes |  |  |
| `subcategory` | string | yes |  |  |
| `unit_cost` | number | yes |  |  |

### ProductList

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `products` | array of [Product](#product) | yes |  |  |

### PromoWindow

The future weeks, inclusive, in which a plan's promotions must start and end.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `end_week` | integer | yes | minimum 0 |  |
| `start_week` | integer | yes | minimum 0 |  |

### PropertyResult

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `detail` | string | yes |  |  |
| `passed` | boolean | yes |  |  |
| `property` | string | yes |  |  |

### PruneReason

Why option generation dropped an enumerated promo option, in the order the rules are
applied (ADR 0035).

string, one of `no_charm_price`, `max_discount`, `below_cost`, `duplicate_price`, `stock`, `partner_stock`.

### QuestionReason

string, one of `missing`, `low_confidence`, `ambiguous`.

### Region

string, one of `North`, `South`, `East`, `West`.

### RegionList

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `regions` | array of [RegionStores](#regionstores) | yes |  |  |

### RegionStockout

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `region` | [Region](#region) | yes |  |  |
| `stockout_probability` | number | yes | minimum 0, maximum 1 |  |

### RegionStores

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `region` | [Region](#region) | yes |  |  |
| `stores` | array of [Store](#store) | yes |  |  |

### RegretBreakdown

A run's regret by cause, each a signed share of the best plan's oracle objective; the
three sum to the regret (ADR 0078).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `model_error` | number | yes |  |  |
| `planner` | number | yes |  |  |
| `timeouts` | number | yes |  |  |

### RejectRequest

Reject a plan revision, the session's latest, with the reason (ADR 0046).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `reason` | string | yes | maxLength 2000 | Why, in plain English. |
| `revision_number` | integer | yes | minimum 1 | The plan revision being rejected. |

### RelationsResponse

A SKU's substitutes (strongest first) and complements (highest lift first).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `complements` | array of [Complement](#complement) | yes |  |  |
| `model` | [ModelVersion](#modelversion) | yes |  |  |
| `sku_id` | string | yes |  |  |
| `substitutes` | array of [Substitute](#substitute) | yes |  |  |

### Relaxation

The smallest change to the brief's constraints that makes an infeasible request
feasible: the least sum of each change as a share of the brief's value (ADR 0044).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `changes` | array of [RelaxedConstraint](#relaxedconstraint) | yes |  |  |
| `policy_binds` | boolean | yes |  |  |
| `proven` | boolean | yes |  |  |

### RelaxedConstraint

One brief constraint the relaxation changes, and by how much (ADR 0044).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `change` | number | yes |  |  |
| `current` | number | yes |  |  |
| `kind` | [ConstraintKind](#constraintkind) | yes |  |  |
| `policy_allows` | number or null | no |  |  |
| `region` | [Region](#region) or null | no |  |  |
| `relaxed` | number or null | yes |  |  |
| `sku_id` | string or null | no |  |  |
| `source` | [ConstraintSource](#constraintsource) | no | default `brief` |  |

### RequestChange

A planning-request field an amendment changed, shown as the explanation may cite it.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `after` | string | yes |  |  |
| `before` | string | yes |  |  |
| `field` | string | yes |  |  |

### RevisionDiff

What changed from the previous plan revision (AG-05, ADR 0052): plan lines matched by
(SKU, region), the objective and promo-cost deltas, and the planning-request changes.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `added` | array of [PlanRevisionLine](#planrevisionline) | no | default `[]` |  |
| `changed` | array of [LineChange](#linechange) | no | default `[]` |  |
| `from_revision` | integer | yes | minimum 1 |  |
| `objective_after` | number or null | no |  |  |
| `objective_before` | number or null | no |  |  |
| `objective_delta` | number or null | no |  |  |
| `promo_cost_after` | number | no | default `0.0` |  |
| `promo_cost_before` | number | no | default `0.0` |  |
| `promo_cost_delta` | number | no | default `0.0` |  |
| `removed` | array of [PlanRevisionLine](#planrevisionline) | no | default `[]` |  |
| `request_changes` | array of [RequestChange](#requestchange) | no | default `[]` |  |
| `unchanged` | integer | no | minimum 0, default `0` |  |

### RevisionSummary

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `lines` | integer | yes |  |  |
| `marketing_budget` | number | yes |  |  |
| `number` | integer | yes |  |  |
| `objective` | number or null | yes |  |  |
| `promo_cost` | number | yes |  |  |
| `regions` | array of [Region](#region) | yes |  |  |
| `sku_ids` | array of string | no | default `[]` |  |
| `solver_status` | [SolveStatus](#solvestatus) or null | yes |  |  |

### RiskCode

string, one of `OVER_CONCENTRATION`, `HEAVY_CANNIBALISATION`, `STOCKOUT_RISK`.

### RiskFinding

One risk the Critic's review found, with feedback specific enough for the planner to act
on. Its numbers come from the plan's tool outputs, never from the LLM.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `actual` | number | yes |  |  |
| `category` | string or null | no |  |  |
| `code` | [RiskCode](#riskcode) | yes |  |  |
| `feedback` | string | yes |  |  |
| `kind` | string | no | always `risk`, default `risk` |  |
| `limit` | number | yes |  |  |
| `message` | string | yes |  |  |
| `region` | [Region](#region) or null | no |  |  |
| `sku_id` | string or null | no |  |  |

### RuleBasedSummary

The rule-based baseline (SPEC §12.2, ADR 0063): 20% off the top 10 sellers in scope,
to All customers, over the whole promo window, dropped from the bottom until its expected
promo cost fits the budget.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `dropped_sku_ids` | array of string | yes |  |  |
| `expected_promo_cost` | number | yes |  |  |
| `lines` | integer | yes |  |  |
| `objective` | number | yes |  |  |
| `sku_ids` | array of string | yes |  |  |

### RunOutcome

How a scenario's session ended.

string, one of `planned`, `awaiting_clarification`, `failed`.

### RunResult

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `amendments_applied` | integer | no | default `0` |  |
| `cassette_misses` | array of string | no | default `[]` |  |
| `clarification` | [ClarificationCheck](#clarificationcheck) or null | no |  |  |
| `constraints` | [ConstraintCheck](#constraintcheck) | no | default `no_plan` |  |
| `duration_s` | number | no | default `0.0` |  |
| `error` | string or null | no |  |  |
| `explanations` | array of [ExplainerRun](#explainerrun) | no | default `[]` |  |
| `extraction` | array of [FieldMatch](#fieldmatch) | no | default `[]` |  |
| `fallbacks` | array of string | no | default `[]` |  |
| `flagged` | array of string | no | default `[]` |  |
| `infeasibility` | [InfeasibilityCheck](#infeasibilitycheck) or null | no |  |  |
| `llm_s` | number | no | default `0.0` |  |
| `oracle` | [OracleScore](#oraclescore) or null | no |  |  |
| `outcome` | [RunOutcome](#runoutcome) | yes |  |  |
| `passed` | boolean | yes | read-only | It ran, kept its hard constraints and had every expected property. Written into the JSON, so `/evals` shows it as the report says and never re-derives it (ADR 0072). |
| `properties` | array of [PropertyResult](#propertyresult) | no | default `[]` |  |
| `quality` | [PlanQuality](#planquality) or null | no |  |  |
| `questions_asked` | array of string | no | default `[]` |  |
| `revision` | [RevisionSummary](#revisionsummary) or null | no |  |  |
| `route` | array of string | no | default `[]` |  |
| `run` | integer | yes |  |  |
| `session_s` | number | no | default `0.0` |  |
| `unneeded_asks` | array of string | no | default `[]` |  |
| `usage` | [SessionUsage](#sessionusage) | no | default `{"calls": 0, "cost_inr": 0.0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "unpriced_models": []}` |  |
| `violations` | array of [Violation](#violation) | no | default `[]` |  |

### ScenarioResult

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `as_of_week` | integer | yes |  |  |
| `consistency` | number or null | no |  |  |
| `group` | string | yes |  |  |
| `name` | string | yes |  |  |
| `passed` | boolean | yes |  |  |
| `runs` | array of [RunResult](#runresult) | yes |  |  |
| `seed` | integer | yes |  |  |

### Scope

The regions and categories a planning request covers, optionally narrowed to SKUs.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `categories` | array of string | yes | minItems 1 |  |
| `regions` | array of [Region](#region) | yes | minItems 1 |  |
| `sku_ids` | array of string | no | default `[]` |  |

### Segment

A behavioural customer group; never defined by protected attributes.

string, one of `Value Seekers`, `Families`, `Premium`, `Young Urban`.

### SegmentUplift

A plan line's expected units in one customer segment against its no-promotion baseline,
the anchor SKU's over the promo weeks (F-03 AC2).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `baseline_units` | number | yes | minimum 0 |  |
| `segment` | [Segment](#segment) | yes |  |  |
| `units` | number | yes | minimum 0 |  |
| `uplift_pct` | number or null | yes |  |  |

### SelectionReason

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `amount` | number | yes |  |  |
| `code` | [SelectionReasonCode](#selectionreasoncode) | yes |  |  |

### SelectionReasonCode

A positive part of a plan line's value (ADR 0005, ADR 0035), or the clearance target it
helps meet (ADR 0040).

string, one of `incremental_profit`, `clearance_value`, `halo`, `clearance_target`.

### SessionCreated

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `session_id` | string (uuid) | yes |  |  |

### SessionResponse

One planning session's read model: status, brief, planning request, latest revision.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `amendments` | array of [Amendment](#amendment) | yes |  | Every amendment to the planning request, oldest first (ADR 0052). |
| `assumptions` | array of [Assumption](#assumption) | yes |  | How the Context agent read the brief, each with its source and confidence (ADR 0048). |
| `brief` | string | yes |  |  |
| `clarifications` | array of [Clarification](#clarification) | yes |  | Every question answered so far, oldest first. |
| `decisions` | array of [PlanDecision](#plandecision) | yes |  | Every approval and rejection, oldest first: the session's audit trail. |
| `demo_recording` | [DemoRecording](#demorecording) or null | no |  | Replaying with no API key: `recorded` while the brief, answers and amendments so far are a recorded session's, which replays; `not_in_demo_recordings` once not, and it plans without the language model. Null with a live LLM (ADR 0073). |
| `error` | string or null | yes |  |  |
| `plan_revision` | [PlanRevision](#planrevision) or null | yes |  |  |
| `planning_request` | [PlanningRequest](#planningrequest) or null | yes |  |  |
| `questions` | array of [ClarificationQuestion](#clarificationquestion) | yes |  | The clarification questions waiting for an answer (awaiting_clarification). |
| `session_id` | string (uuid) | yes |  |  |
| `status` | [SessionStatus](#sessionstatus) | yes |  |  |
| `usage` | [SessionUsage](#sessionusage) | yes |  | What the session's LLM calls used and cost: the sums of its token-usage trace events (ADR 0047). |

### SessionStatus

Every status a planning session can have (ADR 0046).

planning -> awaiting_approval -> approved (final) or rejected (open for amendments); any
failure while planning -> failed; planning -> awaiting_clarification -> planning when the
questions are answered (ADR 0048); awaiting_approval or rejected -> planning when the
request is amended (ADR 0052).

string, one of `planning`, `awaiting_clarification`, `awaiting_approval`, `approved`, `rejected`, `failed`.

### SessionUsage

What a planning session's LLM calls used and cost: the sums of its token-usage events.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `calls` | integer | no | default `0` |  |
| `cost_inr` | number | no | default `0.0` |  |
| `cost_usd` | number | no | default `0.0` |  |
| `input_tokens` | integer | no | default `0` |  |
| `output_tokens` | integer | no | default `0` |  |
| `unpriced_models` | array of string | no | default `[]` |  |

### SimulatePlanRequest

Re-simulate a session's latest plan revision (ADR 0043), optionally against a
competitor reaction (ADR 0045). The seed is configuration.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `competitor_reaction` | [CompetitorReaction](#competitorreaction) or null | no |  | The competitor-reaction scenario; omit or null for a competitor that never reacts. |
| `n_runs` | integer or null | no | minimum 100, maximum 5000 | Runs to simulate; omit for the configured default (SIMULATION_RUNS). |

### SimulatedOutcomes

Ranges over the promo weeks, units capped at pooled available stock (ADR 0004, 0011).

Units and sell-through are the anchor SKU's; revenue, gross profit and promo spend
include a BUNDLE's partner (ADR 0017). Margin is gross profit over revenue in each run
(0 in a run with no revenue). Sell-through is None when there is no available stock.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `gross_profit` | [Percentiles](#percentiles) | yes |  |  |
| `margin` | [Percentiles](#percentiles) | yes |  |  |
| `promo_spend` | [Percentiles](#percentiles) | yes |  |  |
| `revenue` | [Percentiles](#percentiles) | yes |  |  |
| `sell_through` | [Percentiles](#percentiles) or null | yes |  |  |
| `units` | [Percentiles](#percentiles) | yes |  |  |

### SolveStatus

string, one of `OPTIMAL`, `FEASIBLE`, `INFEASIBLE`.

### Store

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `city` | string | yes |  |  |
| `segment_mix` | map of string to number | yes |  |  |
| `store_id` | string | yes |  |  |

### Substitute

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `q_value` | number | yes |  |  |
| `sku_id` | string | yes |  |  |
| `std_error` | number | yes |  |  |
| `theta` | number | yes |  | Cross-price effect: positive for a substitute. |

### TargetSegment

Who a plan line is offered to: one segment exclusively, or All customers (ADR 0006).

string, one of `Value Seekers`, `Families`, `Premium`, `Young Urban`, `All customers`.

### TokensUsed

One billed LLM call: its model, tokens and cost, priced when it was made.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `cost_inr` | number or null | yes |  |  |
| `cost_usd` | number or null | yes |  |  |
| `input_tokens` | integer | yes | minimum 0 |  |
| `kind` | string | no | always `token_usage`, default `token_usage` |  |
| `model` | string | yes |  |  |
| `output_tokens` | integer | yes | minimum 0 |  |

### ToolCalled

A deterministic tool was called: its arguments and a summary of what it returned.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `arguments` | [JsonValue](#jsonvalue) | yes |  |  |
| `error_code` | string or null | no |  |  |
| `kind` | string | no | always `tool_called`, default `tool_called` |  |
| `ok` | boolean | yes |  |  |
| `result_summary` | [JsonValue](#jsonvalue) | yes |  |  |
| `tool` | string | yes |  |  |

### TraceEvent

One step of a planning session's trace.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `at` | string (date-time) | yes |  |  |
| `id` | integer | yes | minimum 1 |  |
| `node` | string or null | yes |  |  |
| `payload` | [TracePayload](#tracepayload) | yes |  |  |
| `session_id` | string (uuid) | yes |  |  |

### TracePayload

One of [NodeStarted](#nodestarted), [NodeFinished](#nodefinished), [ToolCalled](#toolcalled), [DecisionMade](#decisionmade), [ClarificationAsked](#clarificationasked), [FindingRaised](#findingraised) or [TokensUsed](#tokensused), told apart by `kind`.

### TraceStreamEnd

The last event of a session's trace stream (`event: end`): the session is final, so no
more trace events can come (ADR 0047).

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `session_id` | string (uuid) | yes |  |  |
| `status` | [SessionStatus](#sessionstatus) | yes |  |  |

### Violation

One broken hard constraint, specific enough for the planner to fix.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `actual` | number or null | no |  |  |
| `code` | [ViolationCode](#violationcode) | yes |  |  |
| `kind` | string | no | always `violation`, default `violation` |  |
| `limit` | number or null | no |  |  |
| `message` | string | yes |  |  |
| `region` | [Region](#region) or null | no |  |  |
| `sku_id` | string or null | no |  |  |

### ViolationCode

string, one of `BUDGET`, `REGIONAL_BUDGET`, `MIN_MARGIN`, `MARGIN_FLOOR`, `STOCK`, `MAX_DISCOUNT`, `BELOW_COST`, `WINDOW`, `MAX_SKUS`, `DUPLICATE_LINE`, `CLEARANCE_TARGET`, `KVI_TOLERANCE`, `STRONG_SUBSTITUTES`.

### WhyChosen

Why a plan line was chosen: the positive parts of its value, what it is worth alone,
and whether it is the best option the optimiser could pick for its SKU and region.

| Field | Type | Required | Constraints | Description |
| --- | --- | --- | --- | --- |
| `best_for_sku_region` | boolean | yes |  |  |
| `reasons` | array of [SelectionReason](#selectionreason) | yes |  |  |
| `value` | number | yes |  |  |
