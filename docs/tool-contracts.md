# Tool contracts

> ⚠️ **Status: specification, not yet implementation.** Schemas below are the design target for the 24 August build. Model-facing descriptions and examples will be replaced with the exact strings and recorded outputs the server produces.

Every tool documents: name, purpose, model-facing description, input schema, output schema, error conditions, side effects, and a worked example — per Part C of the assignment.

---

## Custom server — Funnel Calibrator

### `measure_sku_funnel`

| | |
|---|---|
| **Purpose** | Measure one product's actual funnel performance from resolved order cohorts. Use before any decision that depends on approval or buyout rates. *This is the primary data-source tool.* |
| **Model-facing description** | *(exact string — to be finalised at build)* Measure the observed call-centre approval, post-office buyout, and return rates for one product over a date window, counting only order cohorts old enough to have resolved. Returns rates with sample size and a reliability flag; returns `insufficient` rather than a rate when the resolved sample is too small to support a conclusion. |
| **Side effects** | None. Read-only over the local snapshot. |

**Input**

| Field | Type | Required | Constraints |
|---|---|---|---|
| `sku` | string | yes | Product code as it appears in the snapshot, e.g. `21-183` |
| `window_from` | string (date) | no | ISO `YYYY-MM-DD`; defaults to snapshot start |
| `window_to` | string (date) | no | ISO `YYYY-MM-DD`; defaults to snapshot date |
| `maturity_days` | integer | no | Cohort maturity override; default from `FC_COHORT_MATURITY_DAYS` (21); range 0–90 |

**Output**

| Field | Type | Meaning |
|---|---|---|
| `sku` | string | Echo of the requested product |
| `approval_rate` | number \| null | Confirmed ÷ total leads; `null` when insufficient |
| `buyout_rate` | number \| null | Bought out ÷ shipped; `null` when insufficient |
| `return_rate` | number \| null | Returned ÷ shipped |
| `resolved_orders` | integer | Orders counted (mature cohorts only) |
| `excluded_in_flight` | integer | Orders set aside as unresolved |
| `reliability` | enum | `high` \| `low` \| `insufficient` |

**Error conditions**

| Condition | Representation |
|---|---|
| Unknown `sku` | Tool error naming the code; *not* an empty result |
| `window_from` after `window_to` | Tool error identifying the invalid range |
| Snapshot missing or unreadable | Tool error naming the configured path |
| Valid product, no orders in window | **Success**, `resolved_orders: 0`, `reliability: "insufficient"` |

**Example** — *(to be replaced with recorded output)*

```json
// in
{ "sku": "21-183", "window_from": "2026-08-05", "window_to": "2026-08-23" }
// out
{ "sku": "21-183", "approval_rate": 0.53, "buyout_rate": 0.49, "return_rate": 0.42,
  "resolved_orders": 99, "excluded_in_flight": 6, "reliability": "high" }
```

---

### `recalibrate_cpl_bounds`

| | |
|---|---|
| **Purpose** | Recompute a product's true break-even and target cost-per-lead from its observed rates, and quantify the drift against the assumed baseline. Use whenever a CPL target is being set, defended, or questioned. |
| **Model-facing description** | *(to be finalised)* Recompute Stop CPL (break-even cost per lead) and Goal CPL (optimisation target) for one product using its measured funnel rates instead of portfolio-wide assumptions, and report the difference against the baseline currently in use. |
| **Side effects** | None. |

**Input:** `sku` (string, required); `observed_approval`, `observed_buyout` (number 0–1, optional — measured on demand when omitted); `usd_uah` (number, optional, default from env).

**Output:** `stop_cpl_assumed`, `goal_cpl_assumed`, `stop_cpl_observed`, `goal_cpl_observed`, `contribution_uah`, `drift_pct`, `economics_reliable` (boolean — false when price or cost inputs are stale or missing), `inputs_used` (object, for tracing a value back to source).

**Error conditions:** unknown `sku`; missing price or cost data for the product (error, not a silent default); rate outside 0–1; contribution ≤ 0 returned as a **successful** result flagged `structural_loss` — a real and important finding, not a failure.

---

### `recommend_next_action`

| | |
|---|---|
| **Purpose** | Diagnose *why* a product is underperforming and return the matching remedy. Use when a campaign misses its target and the cause is not yet established. |
| **Model-facing description** | *(to be finalised)* Given a product's measured funnel, current cost-per-lead, and optional competitor and creative signals, identify the likeliest failure mode — weak offer, contested auction, poor traffic quality, offer/price mismatch, creative fatigue, or structural loss — and return the corresponding recommended action with supporting evidence. |
| **Side effects** | None. |

**Input:** `sku` (required); `current_cpl` (number, USD, required); `cpl_trend_days` (integer, optional); `competitor_active` (boolean, optional); `creative_frequency`, `creative_ctr_trend` (optional).

**Output:** `action` (enum: `scale` \| `hold` \| `pause_retry` \| `stop` \| `full_stop` \| `reprice` \| `new_creative` \| `refresh_creative`), `diagnosis` (enum), `rationale` (string), `evidence` (object), `confidence` (enum), `priority` (integer).

**Error conditions:** unknown `sku`; negative `current_cpl`; insufficient measurement returns a **successful** result with `action: "hold"` and `diagnosis: "insufficient_data"` — explicitly declining to recommend rather than guessing.

---

### `audit_ad_verdict`

| | |
|---|---|
| **Purpose** | Test a proposed advertising decision — from the daily watchdog report, or from the operator — against calibrated economics. Use before acting on any recommendation that originated outside this server. |
| **Model-facing description** | *(to be finalised)* Evaluate a proposed action for one product against its recalibrated CPL bounds and return whether the evidence supports it, contradicts it, or is insufficient to judge, together with the numeric chain that produced the verdict. |
| **Side effects** | None. |

**Input:** `sku` (required); `proposed_action` (enum, required); `current_cpl` (number, required); `source` (string, optional — provenance of the proposal).

**Output:** `verdict` (enum: `supported` \| `contradicted` \| `insufficient_data`), `evidence` (object containing assumed vs. observed bounds, margin at current CPL, sample size), `counter_recommendation` (nullable), `reliability`.

**Error conditions:** unknown `sku`; unrecognised `proposed_action` (error listing accepted values); insufficient data returns `verdict: "insufficient_data"` as a **success**, never a fabricated judgement.

---

## Existing server — Obsidian Local REST API

*To be completed once the vault and plugin are configured. Will document one tool in full (name, model-facing description, arguments and constraints, returned content, error conditions, side effects) as exposed in this project's configuration, plus its role in the agent flow and the failure demonstration: stopping the plugin mid-flow and showing how the agent reports the lost connection.*
