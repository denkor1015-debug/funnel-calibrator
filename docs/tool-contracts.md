# Tool contracts

Every tool documents: name, purpose, model-facing description, input schema, output schema, error conditions, side effects, and a worked example — per Part C of the assignment.

Descriptions below are the **exact strings** the server exposes. Examples are **recorded outputs** from the committed snapshot (4 132 orders, 1 June – 24 August 2026), not illustrations; running the same call reproduces them.

To check this document against a running server:

```bash
npx @modelcontextprotocol/inspector uv run funnel-calibrator
```

---

## Custom server — Funnel Calibrator

Five tools are exposed. Four carry the workflow; `list_covered_skus` is a discovery helper and is documented last, deliberately *not* counted toward the assignment's three substantive tools.

| Tool | Claim it makes | Substantive because |
|---|---|---|
| `measure_sku_funnel` | "This is what happened." | Applies cohort censoring and sample gating over order-level data; computes rates rather than reading them. Primary data-source tool. |
| `recalibrate_cpl_bounds` | "This is what it implies." | Deterministic unit-economics recomputation, surfacing a failure the caller cannot otherwise see. |
| `recommend_next_action` | "This is the cause and the remedy." | Encodes a diagnosis tree that maps identical symptoms to opposite actions. |
| `audit_ad_verdict` | "This proposal is supported / contradicted." | Validates an *external* decision against evidence; distinct in direction from the other three. |

---

### `measure_sku_funnel`

| | |
|---|---|
| **Purpose** | Measure one product's actual funnel performance from resolved order cohorts. Use before any decision that depends on approval or buyout rates. *This is the primary data-source tool.* |
| **Side effects** | **None.** Read-only over the local snapshot file — no network, no writes. Declared to MCP as `readOnlyHint: true`, `destructiveHint: false`, `openWorldHint: false`. |

**Model-facing description** (exact string):

> Measure the observed call-centre approval, post-office buyout, and return rates for one product over a date window, counting only order cohorts old enough to have resolved. Use this before any decision that depends on approval or buyout rates, instead of assuming the portfolio-wide 65% approval and 52.5% buyout. Returns rates together with sample size and a reliability flag, and returns null rates with reliability 'insufficient' rather than a number when the resolved sample is too small to support a conclusion. Read-only.

**Input**

| Field | Type | Required | Constraints | Default |
|---|---|---|---|---|
| `sku` | string | yes | Product code as it appears in the snapshot, e.g. `21-183` | — |
| `window_from` | string \| null | no | ISO `YYYY-MM-DD` | snapshot start |
| `window_to` | string \| null | no | ISO `YYYY-MM-DD` | snapshot date |
| `maturity_days` | integer \| null | no | `0 ≤ n ≤ 90`, enforced by the schema | `FC_COHORT_MATURITY_DAYS` (21) |

**Output**

| Field | Type | Meaning |
|---|---|---|
| `sku` | string | Echo of the requested product |
| `window` | object | `{from, to}` actually applied |
| `approval_rate` | number \| null | Approved ÷ all leads. `null` below the sample threshold |
| `buyout_rate` | number \| null | Bought out ÷ parcels whose fate is known |
| `return_rate` | number \| null | Refused ÷ parcels whose fate is known |
| `leads` | integer | Mature orders in window — the approval denominator |
| `approved` | integer | Orders the call centre confirmed |
| `bought_out`, `refused` | integer | Resolved parcel outcomes |
| `resolved_orders` | integer | Buyout denominator (`bought_out + refused`) |
| `excluded_in_flight` | integer | Everything set aside, total |
| `excluded_immature_cohort` | integer | Too recent to have resolved |
| `excluded_still_moving` | integer | Shipped, not yet collected or refused |
| `excluded_awaiting_call` | integer | Still with the call centre |
| `maturity_days`, `cohort_cutoff` | integer, date | The censoring actually applied |
| `min_sample` | integer | Threshold in force |
| `reliability` | `high` \| `low` \| `insufficient` | Whether the rates may be acted on |
| `snapshot_generated_at` | string | Provenance of every figure above |

**Error conditions**

| Condition | Representation |
|---|---|
| Unknown `sku` | MCP tool error naming the code and offering near matches — *not* an empty result |
| Empty `sku` | MCP tool error |
| `window_from` after `window_to` | MCP tool error quoting both dates |
| Malformed date | MCP tool error quoting the offending value |
| `maturity_days` outside 0–90 | Schema validation error, before the handler runs |
| Snapshot missing or unreadable | MCP tool error naming the configured path |
| **Valid product, no orders in window** | **Success**, `resolved_orders: 0`, `reliability: "insufficient"`, rates `null` |

**Example** — recorded output:

```jsonc
// in
{ "sku": "21-154" }
// out
{
  "sku": "21-154",
  "window": { "from": "2026-06-01", "to": "2026-08-24" },
  "approval_rate": 0.5901, "buyout_rate": 0.4526, "return_rate": 0.5474,
  "leads": 161, "approved": 95,
  "bought_out": 43, "refused": 52, "resolved_orders": 95,
  "excluded_in_flight": 20, "excluded_immature_cohort": 20,
  "excluded_still_moving": 0, "excluded_awaiting_call": 0,
  "maturity_days": 21, "cohort_cutoff": "2026-08-03",
  "min_sample": 30, "reliability": "high",
  "snapshot_generated_at": "2026-08-24T14:14:37"
}
```

Read against the assumptions: this product approves at **59.0%** against an assumed 65%, and buys out at **45.3%** against an assumed 52.5%.

---

### `recalibrate_cpl_bounds`

| | |
|---|---|
| **Purpose** | Recompute a product's true break-even and target cost-per-lead from its observed rates, and quantify the drift against the assumed baseline. Use whenever a CPL target is being set, defended, or questioned. |
| **Side effects** | **None.** Read-only. |

**Model-facing description** (exact string):

> Recompute Stop CPL (the cost per lead at which profit reaches zero) and Goal CPL (the optimisation target) for one product from its own measured funnel rates instead of portfolio-wide assumptions, and report the drift against the baseline currently in use. Measures the product itself when observed rates are not supplied. Use whenever a cost-per-lead target is being set, defended, or questioned. Flags the case where the assumed target sits above the true break-even, which is invisible in the ads dashboard. Read-only.

**Input**

| Field | Type | Required | Constraints | Default |
|---|---|---|---|---|
| `sku` | string | yes | Product code | — |
| `observed_approval` | number \| null | no | `0 < n ≤ 1` | measured on demand |
| `observed_buyout` | number \| null | no | `0 < n ≤ 1` | measured on demand |
| `usd_uah` | number \| null | no | `> 0` | the product's own rate |
| `window_from`, `window_to` | string \| null | no | ISO date; used only when measuring | snapshot window |

**Output**

| Field | Type | Meaning |
|---|---|---|
| `rate_source` | `caller` \| `measured` | Whether rates were supplied or measured here |
| `stop_cpl_assumed`, `goal_cpl_assumed` | number | Bounds from the portfolio constants — what the business steers by today |
| `stop_cpl_observed`, `goal_cpl_observed` | number \| null | Bounds from this product's own rates |
| `contribution_uah` | number | Left per parcel collected, before advertising |
| `drift_pct` | number \| null | Observed vs. assumed Stop CPL. Negative = true break-even is *lower* than assumed |
| `target_above_breakeven` | boolean | **The finding.** Assumed Goal exceeds observed Stop: every lead bought at target loses money while the dashboard looks healthy |
| `structural_loss` | boolean | Contribution ≤ 0 — no cost per lead rescues it |
| `economics_reliable` | boolean | False when price or cost is stale or inferred |
| `inputs_used` | object | Every constant and input, for tracing a value back to source |

**Error conditions**

| Condition | Representation |
|---|---|
| Unknown `sku` | MCP tool error naming the code |
| No price or cost on file | MCP tool error saying so explicitly — never a silent default |
| Rate outside `(0, 1]` | Schema validation error |
| `usd_uah ≤ 0` | Schema validation error |
| Contribution ≤ 0 | **Success**, flagged `structural_loss: true`. A finding, not a failure |
| Sample too thin | **Success** with `stop_cpl_observed: null` and `reliability: "insufficient"` |

**Example** — recorded output:

```jsonc
// in
{ "sku": "21-154" }
// out
{
  "sku": "21-154", "rate_source": "measured",
  "reliability": "high", "resolved_orders": 95,
  "stop_cpl_assumed": 2.32,  "goal_cpl_assumed": 1.63,
  "stop_cpl_observed": 1.61, "goal_cpl_observed": 1.12,
  "contribution_uah": 270.49, "contribution_uah_assumed": 306.14,
  "drift_pct": -30.6,
  "target_above_breakeven": true,
  "structural_loss": false, "economics_reliable": true,
  "observed_rates": { "approval": 0.5901, "buyout": 0.4526 },
  "inputs_used": {
    "price_uah": 690.0, "cogs_uah": 350.0,
    "cogs_source": "cogs_history: 350 ₴ напряму",
    "cost_effective_from": "2026-07-13",
    "usd_uah": 45.0, "upsell_uah": 95.0,
    "return_fee_uah": 94.0, "call_centre_fee_uah": 23.0,
    "goal_ratio": 0.7,
    "assumed_approval_rate": 0.65, "assumed_buyout_rate": 0.525
  }
}
```

**This is the case the server exists for.** The assumed *target* is **$1.63**. The true *break-even* is **$1.61**. Buying leads at target loses money on every one, while the ads dashboard shows a cost per lead comfortably inside its goal.

---

### `recommend_next_action`

| | |
|---|---|
| **Purpose** | Diagnose *why* a product is underperforming and return the matching remedy. Use when a campaign misses its target and the cause is not yet established. |
| **Side effects** | **None.** Read-only. |

**Model-facing description** (exact string):

> Diagnose why a product is underperforming and return the matching remedy. Given the product's measured funnel, its current cost per lead, and optional competitor and creative signals, identifies the likeliest failure mode — structural loss, contested auction, traffic quality, offer or price mismatch, creative fatigue, or a weak offer — and returns the action that fits it. Use when a campaign misses its target and the cause is not yet established, because cheap leads that fail on the call and leads that fail at the post office need opposite remedies. Returns action 'hold' with diagnosis 'insufficient_data' rather than guessing when the sample is too small. Read-only.

**Input**

| Field | Type | Required | Constraints |
|---|---|---|---|
| `sku` | string | yes | Product code |
| `current_cpl` | number | yes | USD, `≥ 0` |
| `cpl_trend_days` | integer \| null | no | `0 ≤ n ≤ 365` |
| `competitor_active` | boolean \| null | no | — |
| `creative_frequency` | number \| null | no | `≥ 0` |
| `creative_ctr_trend` | number \| null | no | Negative means falling |
| `window_from`, `window_to` | string \| null | no | ISO date |

**Output**

| Field | Type | Meaning |
|---|---|---|
| `action` | enum | `scale` \| `hold` \| `pause_retry` \| `stop` \| `full_stop` \| `reprice` \| `new_creative` \| `refresh_creative` |
| `diagnosis` | enum | `healthy` \| `structural_loss` \| `contested_auction` \| `traffic_quality` \| `offer_mismatch` \| `creative_fatigue` \| `weak_offer_or_creative` \| `insufficient_data` |
| `rationale` | string | Prose naming the numbers behind the call |
| `evidence` | object | Bounds, rates, margin at current CPL, reliability |
| `confidence` | `high` \| `medium` \| `low` | Capped at `medium` when reliability is `low` |
| `priority` | integer | 1 = act today |
| `measurement` | object | The full `measure_sku_funnel` payload it was built on |
| `breakeven_condition` | object | Present only for `reprice`: the buyout rate required for the current CPL to break even. **A condition, not a forecast** |

**Error conditions**

| Condition | Representation |
|---|---|
| Unknown `sku` | MCP tool error naming the code |
| Negative `current_cpl` | Schema validation error, then an explicit guard |
| Missing economics | MCP tool error |
| Insufficient sample | **Success** with `action: "hold"`, `diagnosis: "insufficient_data"` — declining, not guessing |

**Examples** — recorded, showing the discrimination that justifies the tool:

```jsonc
// in  { "sku": "21-197", "current_cpl": 1.20 }
// out → action "new_creative", diagnosis "traffic_quality"
// "Leads are affordable (1.20 against a break-even of 2.17), but only 32%
//  confirm on the call against an assumed 65%. Cheap leads with weak intent
//  are a creative and audience problem, not a price problem."

// in  { "sku": "21-253", "current_cpl": 6.00 }
// out → action "stop", diagnosis "weak_offer_or_creative"

// in  { "sku": "21-253", "current_cpl": 6.00,
//       "competitor_active": true, "cpl_trend_days": 5 }
// out → action "pause_retry", diagnosis "contested_auction"
// "Cost per lead is 75% above target and has held for 5 days with a known
//  competitor on this product. The auction is the problem, not the offer."
```

The same product at the same cost per lead yields **`stop`** or **`pause_retry`** depending on one competitor signal. That difference — and the difference between `new_creative` and `reprice` for two products showing the identical symptom — is the tool's reason for existing.

---

### `audit_ad_verdict`

| | |
|---|---|
| **Purpose** | Test a proposed advertising decision — from the daily watchdog, from an operator, from the decision journal — against calibrated economics. Use before acting on any recommendation that originated outside this server. |
| **Side effects** | **None.** Read-only. |

**Model-facing description** (exact string):

> Test an advertising decision that originated elsewhere — a daily watchdog report, an operator's judgement, a note in the decision journal — against this product's recalibrated economics. Returns 'supported', 'contradicted', or 'insufficient_data', together with the numeric chain that produced the verdict and a counter-recommendation where the proposal is contradicted. Use before acting on any recommendation this server did not itself produce. Read-only.

**Input**

| Field | Type | Required | Constraints |
|---|---|---|---|
| `sku` | string | yes | Product code |
| `proposed_action` | enum | yes | One of the eight actions; schema-enforced |
| `current_cpl` | number | yes | USD, `≥ 0` |
| `source` | string \| null | no | Provenance, kept in the audit record |
| `competitor_active` | boolean \| null | no | — |
| `cpl_trend_days` | integer \| null | no | `0 ≤ n ≤ 365` |

**Output**

| Field | Type | Meaning |
|---|---|---|
| `verdict` | `supported` \| `contradicted` \| `insufficient_data` | — |
| `evidence` | object | Assumed vs. observed bounds, margin at current CPL, sample size, the proposal and its source |
| `counter_recommendation` | string \| null | What the evidence indicates instead; `null` when supported |
| `reliability` | enum | Sample quality behind the verdict |
| `rationale` | string | The chain in prose |

Compatibility is deliberately not exact-match: `stop` and `full_stop` agree in direction, and `hold` is consistent with `scale`. The mapping lives in `policy.COMPATIBLE`, where it can be argued with.

**Error conditions**

| Condition | Representation |
|---|---|
| Unknown `sku` | MCP tool error naming the code |
| Unrecognised `proposed_action` | Schema validation error listing accepted values |
| Negative `current_cpl` | Schema validation error |
| Insufficient data | **Success** with `verdict: "insufficient_data"` and `counter_recommendation: null` — never a fabricated judgement |

**Example** — recorded, and the verdict the demonstration turns on:

```jsonc
// in
{ "sku": "21-154", "proposed_action": "scale", "current_cpl": 1.63,
  "source": "ads-watchdog daily report" }
// out
{ "sku": "21-154", "verdict": "contradicted",
  "proposed_action": "scale", "counter_recommendation": "stop",
  "reliability": "high",
  "rationale": "Evidence indicates 'stop' (weak_offer_or_creative). The
    proposal 'scale' is not. Cost per lead 1.63 is above this product's true
    break-even of 1.61 …" }
```

The watchdog proposed `scale` because $1.63 is inside the assumed goal of $1.63. Against the product's own rates the break-even is $1.61, so the verdict is **contradicted** and the counter-recommendation is `stop`.

---

### `list_covered_skus` *(discovery helper — not counted toward the required three)*

| | |
|---|---|
| **Purpose** | Resolve a product code, or see what the dataset covers, before measuring. |
| **Side effects** | None. |
| **Input** | `min_orders` (integer, optional, `≥ 0`, default `1`) |
| **Output** | `products[]` with `sku`, `orders`, `manufacturer`, `has_economics`; plus the snapshot window, total orders, and the status taxonomy in force |
| **Errors** | Snapshot missing or unreadable → tool error naming the path |

Listed for honesty rather than credit: it sits close to "list all rows", which the assignment excludes from the substantive count. It earns its place by letting the agent resolve a code instead of guessing one, but the substantive tools are the four above.

---

## Existing server — Obsidian Local REST API

**Repository:** [coddingtonbear/obsidian-local-rest-api](https://github.com/coddingtonbear/obsidian-local-rest-api) — the approved package, used directly. The plugin now ships its own MCP server, so no third-party wrapper sits in between.

| | |
|---|---|
| **Transport** | Streamable HTTP at `https://127.0.0.1:27124/mcp/` (self-signed certificate), or plain HTTP at `http://127.0.0.1:27123/mcp/` when enabled |
| **Auth** | `Authorization: Bearer <api-key>`; the key is generated by the plugin and read from `OBSIDIAN_API_KEY`. Never committed |
| **Tools exposed** | `vault_list`, `vault_read`, `vault_write`, `vault_append`, `vault_patch`, `vault_delete`, `vault_move`, `vault_copy`, `vault_get_document_map`, `active_file_get_path`, `search_query`, `search_simple`, `tag_list`, `command_list`, `command_execute`, `open_file` |
| **Used in this project** | `vault_read` (step 1) and `vault_write` (step 5). The rest are reachable but out of the flow |

To print the live schemas rather than trusting this table:

```bash
uv run python scripts/capture_obsidian_contract.py vault_read
```

### `vault_read` — documented in full

Captured from the running plugin (`obsidian-local-rest-api` 1.0.0), not transcribed.

**Purpose in this project.** It is step one, and the reason the vault is an *input* rather than a log. The agent reads `Objective.md`, and that note determines which products are measured and which proposals are audited. Change the table in the note and the whole run changes — no product code is hard-coded anywhere in `agent/run_agent.py`.

**Model-facing description** (exact string):

> Read a vault file's content and metadata. Returns a JSON object with: content (full markdown text), path, tags (array of tag strings), frontmatter (parsed YAML front-matter as an object), stat ({ctime, mtime, size}), links (array of vault-relative paths this file links to), backlinks (array of vault-relative paths of files that link here), and unresolvedLinks (array of link text in this file that does not resolve to an existing vault file). Throws if the file does not exist.
>
> When targetType and target are both provided, returns only the matched section as a plain string (markdown) or JSON value (frontmatter) instead of the full object. To save context, call vault_get_document_map first to identify headings, block IDs, or frontmatter keys, and prefer targeted reads over full reads for anything but short files.

**Input**

| Field | Type | Required | Constraints |
|---|---|---|---|
| `path` | string | yes | File path relative to the vault root, e.g. `Objective.md` |
| `targetType` | string | no | Enum: `heading` \| `block` \| `frontmatter` |
| `target` | string \| string[] | no | For a heading, an **array** naming the path from top level down (a bare string is rejected); for a block, the bare id without `^`; for frontmatter, the key |
| `scope` | string | no | Enum: `content` \| `marker` \| `markerAndContent`; default `content` |

`additionalProperties: false` — the schema rejects anything else outright.

**Returned content.** With `path` alone, a JSON object: `content`, `path`, `tags`, `frontmatter`, `stat`, `links`, `backlinks`, `unresolvedLinks`. With `targetType` + `target`, only the matched section. This project uses the plain form — `Objective.md` is short, and the whole note is what drives the run.

**Constraint worth noting.** Paths resolve inside the configured vault only; the plugin will not read outside it. That is what makes a dedicated demonstration vault a real boundary rather than a convention.

**Error conditions**

| Condition | Representation |
|---|---|
| Missing note | Tool error; the agent reports it and does not invent an objective |
| Wrong or absent API key | HTTP 401 at connection time — caught by `run_agent.py`'s pre-flight check before the agent starts |
| Plugin stopped or Obsidian closed | Connection refused; the run stops with the cause named |
| Path outside the vault | Refused by the plugin |

**Side effects.** None — `vault_read` is a read. The **only** side effect anywhere in this system is `vault_write` creating `Decisions/YYYY-MM-DD.md` in the demonstration vault. No campaign is paused, no price changed, no CRM record touched.

### Failure demonstration

Three failures are reproducible on demand; see `docs/defence-checklist.md` §4 for exact commands.

1. **Server unavailable** — quit Obsidian, or disable the plugin, then run the agent. The pre-flight check names the endpoint and the refusal, and the run stops with exit code 2 rather than proceeding with half a flow.
2. **Wrong API key** — `OBSIDIAN_API_KEY=wrong uv run python agent/run_agent.py`. The plugin answers 401 and the message says to re-copy the key from the plugin's settings.
3. **Mid-flow loss** — disable the plugin after the measurement steps and before the write. The `vault_write` call fails, the agent reports which step it could not complete rather than claiming the note was written, and `run_agent.py` independently prints whether the file exists on disk.
