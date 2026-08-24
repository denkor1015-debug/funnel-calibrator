# Funnel Calibrator

**An MCP server that recalibrates advertising decisions against what a sales funnel actually does — not what it is assumed to do.**

> KSE AI Agentic Lab — Individual Lab Assignment (Week 7, *MCP Integration*). Defence: **25 August 2026**.

---

## The problem this solves

The project is built on a live Ukrainian cash-on-delivery (COD) e-commerce business selling women's clothing through Meta ads. Its funnel has five stages:

```
Meta ads ──► Lead ──► Call-centre approval ──► Shipment ──► Buyout at post office ──► Profit
```

Because payment happens **on delivery**, the outcome of an ad campaign is not known when the money is spent. It is known two to four weeks later, when the customer either collects the parcel or does not. The business bridges that gap with two portfolio-wide constants — a 65% approval rate and a 52.5% buyout rate — and uses them to compute, for every product, the maximum cost-per-lead at which that product still breaks even (`Stop CPL`) and the target it should be optimised toward (`Goal CPL`).

**Those constants are portfolio averages applied to individual products, and individual products diverge sharply from them.** Measured examples from the source business: one manufacturer's products buy out at 37% against the assumed 52.5%; one product's approval rate measured 53% against the assumed 65%; buyout correlates strongly with price band, ranging from roughly 93% at 690–790 ₴ to roughly 55% above 1290 ₴.

When a product's real rates are worse than assumed, its real break-even CPL is lower than the number the business is steering by — so the advertising target can sit *above* the true break-even point. Traffic looks healthy in the ads dashboard while every lead loses money, and the loss only becomes visible at the monthly financial close, weeks later.

This is an **open-loop control system**: the measurement never returns to the decision. Funnel Calibrator closes the loop.

## What it does

The server measures each product's *own* funnel rates from historical order data, recomputes that product's true CPL bounds, and audits proposed advertising decisions against the corrected figures — returning structured evidence rather than a verdict to be taken on faith.

Two problems make this harder than an average, and both are handled explicitly in the tool contracts:

- **Censoring.** Recent orders have not resolved yet — a parcel in transit is neither a buyout nor a return. Counting them naively depresses the measured rate. The server excludes cohorts younger than a configurable maturity window and reports how many orders it set aside.
- **Small samples.** Per product, per size, per colour, the counts get small quickly. Every measurement carries its sample size and a reliability flag, and the server declines to draw conclusions below a configurable threshold rather than reporting confident noise.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Agent  (Claude Agent SDK)                                  │
│                                                             │
│    ├── MCP ──► Obsidian Local REST API      [existing]      │
│    │           decision journal: reads the day's objective  │
│    │           and prior conclusions, writes calibrated      │
│    │           verdicts back as a durable record            │
│    │                                                         │
│    └── MCP ──► Funnel Calibrator            [custom]        │
│                measure → recalibrate → recommend → audit    │
│                        │                                     │
│                        ▼                                     │
│                 local snapshot dataset                       │
│                 (anonymised order cohorts + unit economics)  │
└─────────────────────────────────────────────────────────────┘
```

The custom server runs as a **separate process** communicating over stdio, and is startable independently of the agent.

### Agent flow

1. Read the day's advertising objective and yesterday's conclusions from the Obsidian vault.
2. Measure each product's observed funnel rates from the snapshot (censoring- and sample-aware).
3. Recompute that product's true `Stop`/`Goal` CPL and the drift against the assumed baseline.
4. Diagnose *why* a product underperforms — the cure differs by cause — and recommend a next action.
5. Audit the day's proposed decisions against the corrected bounds.
6. Write the calibrated verdict, with its evidence chain, back to the vault.

Each step consumes the previous step's output: the vault's contents determine what is measured, the measurement determines the corrected bounds, and the bounds determine whether a proposed decision stands or is overturned.

## Custom tools

| Tool | Responsibility |
|---|---|
| `measure_sku_funnel` | Observed approval / buyout / return rates for one product, with cohort censoring and sample-size gating. *Primary data-source tool.* |
| `recalibrate_cpl_bounds` | Recomputes true `Stop`/`Goal` CPL from observed rates; reports drift against the assumed baseline. |
| `recommend_next_action` | Distinguishes the failure mode — weak offer, contested auction, traffic quality, creative fatigue, structural loss — and returns the matching action. |
| `audit_ad_verdict` | Tests a proposed decision against the calibrated bounds; returns `supported` / `contradicted` / `insufficient_data` with the numeric evidence chain. |

A fifth tool, `list_covered_skus`, resolves a product code against the dataset. It is documented but deliberately **not** counted toward the assignment's three substantive tools — it sits too close to "list all rows".

Full input/output schemas, error conditions, side effects, and worked examples: **[`docs/tool-contracts.md`](docs/tool-contracts.md)**.

Why these four, why they sit at the MCP boundary, and what the design gives up: **[`docs/design-rationale.md`](docs/design-rationale.md)**.

## What it found

Article **21-154**, measured on 95 resolved orders:

| | Assumed | Observed |
|---|---|---|
| Approval | 65% | **59.0%** |
| Buyout | 52.5% | **45.3%** |
| Stop CPL (break-even) | $2.32 | **$1.61** |
| Goal CPL (target) | **$1.63** | $1.12 |

The target the business optimises toward, **$1.63**, sits *above* the product's true break-even of **$1.61**. Every lead bought at target loses money, while the ads dashboard shows a cost per lead comfortably inside its goal. The product had been scaled twice on that basis.

The build also turned up a CRM status — 35 "Відмова", 216 shipped orders — that the business's own reporting classifies as `unknown` and counts nowhere. Evidence in [`docs/design-rationale.md`](docs/design-rationale.md) §5.

## Data source

A **local, anonymised snapshot dataset** of historical order cohorts, exported from the business CRM by [`scripts/export_snapshot.py`](scripts/export_snapshot.py): **4 132 orders across 51 products, 1 June – 24 August 2026**. No authentication and no network access are required at runtime, which makes the demonstration deterministic and reproducible — the export is a separate program from the server, run offline and ahead of time.

All personally identifiable information — customer names, phone numbers, addresses, waybill numbers, call-centre operator names — is stripped at export by a field whitelist, so a field the CRM adds later cannot leak by default. The snapshot retains only what the calibration requires: product code, order status, creation date, amount, and campaign labels. See [`data/README.md`](data/README.md) for the anonymisation policy and schema.

## Quickstart

**Prerequisites:** Python ≥ 3.11 and [`uv`](https://docs.astral.sh/uv/). Obsidian with the Local REST API plugin is required only for the agent flow, not for running the server.

```bash
git clone https://github.com/denkor1015-debug/funnel-calibrator.git
cd funnel-calibrator
uv sync
```

Run the MCP server standalone (it speaks MCP over stdio and will wait for a client):

```bash
uv run funnel-calibrator
```

Inspect the exposed tools interactively with the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector uv run funnel-calibrator
```

Run the tests:

```bash
uv run pytest
```

Configuration is read from environment variables; copy the template and edit:

```bash
cp .env.example .env
```

### Running the agent flow

The agent needs the Obsidian side as well. One-time setup, in full: [`demo-vault/README.md`](demo-vault/README.md).

1. Open `demo-vault/` in Obsidian as a vault — **not a personal vault**.
2. Install and enable the community plugin **Local REST API with MCP** by Adam Coddington ([coddingtonbear/obsidian-local-rest-api](https://github.com/coddingtonbear/obsidian-local-rest-api)). Several similarly named plugins mention MCP; this is the approved one.
3. Copy its generated API key into `.env` as `OBSIDIAN_API_KEY`.
4. Enable **Enable Non-encrypted (HTTP) Server** in the same pane and set `OBSIDIAN_PORT=27123`. The plugin's HTTPS certificate is self-signed and Node rejects it; `demo-vault/README.md` explains the alternative if you would rather keep TLS.

Then:

```bash
uv run python agent/run_agent.py --dry-run   # connect to both servers, list tools, stop
uv run python agent/run_agent.py             # full flow, writes demo-vault/Decisions/<today>.md
```

The Claude Agent SDK inherits the Claude Code CLI's authentication, so **no Anthropic API key is set or needed**. The only secret in play is the Obsidian plugin's token.

Agent wiring in portable form, for other MCP hosts: [`agent/mcp_config.example.json`](agent/mcp_config.example.json).

### Regenerating the dataset

Not required to run anything — `data/` is committed. The economics half rebuilds with no credentials at all:

```bash
uv run python scripts/export_snapshot.py --economics-only
```

The order half reads the business CRM through a worker, with the shared secret taken from `KEYCRM_MCP_SECRET`. It throttles, backs off on HTTP 429, and resumes rather than restarts:

```bash
uv run python scripts/export_snapshot.py --from 2026-06-01 --to 2026-08-24
```

## Repository layout

```
src/funnel_calibrator/   MCP server
  server.py              tool definitions and MCP wiring
  snapshot.py            dataset loading, status taxonomy, cohort censoring
  calibration.py         unit economics — mirrors the business's own econ.py
  policy.py              diagnosis tree: evidence ──► diagnosis ──► action
scripts/                 snapshot exporter (CRM ──► anonymised local dataset)
data/                    snapshot dataset + anonymisation policy
demo-vault/              Obsidian vault for the demonstration (no personal notes)
docs/                    tool contracts, design rationale, defence checklist
agent/                   end-to-end agent flow across both connections
tests/                   37 tests: calibration, censoring, sample gating, policy
```

## Build plan

- [x] Repository scaffolding, architecture, and design rationale
- [x] Snapshot exporter with PII stripping, rate-limit backoff, and resumable catalogue mapping
- [x] `measure_sku_funnel` — censoring and sample gating
- [x] `recalibrate_cpl_bounds` — unit-economics recomputation
- [x] `recommend_next_action` — failure-mode diagnosis
- [x] `audit_ad_verdict` — decision auditing
- [x] Obsidian MCP integration and end-to-end agent flow
- [x] Failure-path handling and demonstration
- [x] Tool-contract documentation and defence script

## Assignment requirements map

| Requirement | Where |
|---|---|
| Part A — approved existing MCP server | Obsidian Local REST API, the plugin's own MCP server, no wrapper. `vault_read` documented in full and driving step 1 of the flow; three failures reproducible on demand |
| Part B — custom MCP server, ≥ 3 substantive tools | `src/funnel_calibrator/`, separate process over stdio, startable alone with `uv run funnel-calibrator`. Four substantive tools; three of them compute, diagnose, or validate rather than retrieve |
| Part C — tool-contract documentation | `docs/tool-contracts.md` — exact model-facing strings, recorded outputs |
| Part D — operational requirements | No secrets committed; all configuration via environment variables; local dataset, so **no network access at runtime** and no API fixtures required; the export path throttles and backs off on HTTP 429 |
| Design rationale | `docs/design-rationale.md` |
| Defence script | `docs/defence-checklist.md` |

## Licence

MIT — see [LICENSE](LICENSE).
