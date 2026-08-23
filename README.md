# Funnel Calibrator

**An MCP server that recalibrates advertising decisions against what a sales funnel actually does — not what it is assumed to do.**

> ⚠️ **Status: work in progress.** Scaffolding and design are committed; the MCP server implementation lands 24 August 2026. Defence: **25 August 2026**.
>
> KSE AI Agentic Lab — Individual Lab Assignment (Week 7, *MCP Integration*).

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

Full input/output schemas, error conditions, side effects, and worked examples: **[`docs/tool-contracts.md`](docs/tool-contracts.md)**.

Why these four, why they sit at the MCP boundary, and what the design gives up: **[`docs/design-rationale.md`](docs/design-rationale.md)**.

## Data source

A **local, anonymised snapshot dataset** of historical order cohorts, exported from the business CRM by [`scripts/export_snapshot.py`](scripts/export_snapshot.py). No authentication and no network access are required at runtime, which makes the demonstration deterministic and reproducible.

All personally identifiable information — customer names, phone numbers, addresses, waybill numbers — is stripped at export. The snapshot retains only what the calibration requires: product code, order status, timestamps, amounts, and unit economics. See [`data/README.md`](data/README.md) for the anonymisation policy and schema.

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

Configuration is read from environment variables; copy the template and edit:

```bash
cp .env.example .env
```

Agent wiring for both MCP connections: [`agent/mcp_config.example.json`](agent/mcp_config.example.json).

## Repository layout

```
src/funnel_calibrator/   MCP server: tool definitions, calibration math, policy engine
scripts/                 snapshot exporter (CRM ──► anonymised local dataset)
data/                    snapshot dataset + anonymisation policy
docs/                    tool contracts, design rationale, defence checklist
agent/                   MCP client configuration for both connections
tests/                   unit tests for calibration and policy logic
```

## Build plan

- [x] Repository scaffolding, architecture, and design rationale
- [ ] Snapshot exporter with PII stripping
- [ ] `measure_sku_funnel` — censoring and sample gating
- [ ] `recalibrate_cpl_bounds` — unit-economics recomputation
- [ ] `recommend_next_action` — failure-mode diagnosis
- [ ] `audit_ad_verdict` — decision auditing
- [ ] Obsidian MCP integration and end-to-end agent flow
- [ ] Failure-path handling and demonstration
- [ ] Tool-contract documentation and defence script

## Assignment requirements map

| Requirement | Where |
|---|---|
| Part A — approved existing MCP server | Obsidian Local REST API; contract documented in `docs/tool-contracts.md` |
| Part B — custom MCP server, ≥ 3 substantive tools | `src/funnel_calibrator/`; four tools, three of which perform computation, diagnosis, or validation rather than retrieval |
| Part C — tool-contract documentation | `docs/tool-contracts.md` |
| Part D — operational requirements | No secrets committed; configuration via environment variables; local dataset requires no network access at runtime |
| Design rationale | `docs/design-rationale.md` |
| Defence script | `docs/defence-checklist.md` |

## Licence

MIT — see [LICENSE](LICENSE).
