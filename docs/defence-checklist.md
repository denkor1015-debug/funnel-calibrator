# Defence checklist

Individual defence, 10–15 minutes. Every command below is real and runs from the repository root.

For a **recorded** defence the requirements are stricter — one continuous take, and the changed input, the failure, and the traced value must all be shown unprompted. Script for that: [`video-runbook.md`](video-runbook.md).

## Before starting

- [ ] `git status` clean; `data/snapshot.json` and `data/economics.json` present
- [ ] `.env` configured — **and every editor showing it closed**. Nothing on screen may display the Obsidian key
- [ ] Obsidian running, Local REST API enabled with its **plain-HTTP listener on 27123** on, **`demo-vault` open — not a personal vault**
- [ ] `demo-vault/Decisions/` emptied, so the note the agent writes is visibly new
- [ ] Terminal font large enough for tool calls and JSON to be legible on the recording
- [ ] Second terminal ready for the failure demonstration

Quick pre-flight, all three should pass:

```bash
uv run pytest -q
uv run python scripts/export_snapshot.py --economics-only
uv run python agent/run_agent.py --dry-run
```

`pytest` should report **65 passed**.

---

## 1 · Independent startup and architecture (≈2 min)

- [ ] Start the custom server **on its own, before the agent**, in its own terminal — this is the process-separation evidence:

  ```bash
  uv run funnel-calibrator
  ```

  It waits on stdio and prints nothing. Say so: an MCP server over stdio is silent until a client speaks to it. Stop it with **Ctrl-D** — closing the pipe is how a host shuts a stdio server down; this server does not act on Ctrl-C.

- [ ] Show the tools with an independent client, no agent involved:

  ```bash
  npx @modelcontextprotocol/inspector uv run funnel-calibrator
  ```

- [ ] State the problem in one sentence: *in a cash-on-delivery business the outcome of an ad is known two to four weeks after the money is spent, so targets run on portfolio-wide constants that individual products violate.*

- [ ] Point at the architecture: agent process ↔ MCP ↔ two separate servers; the calibrator reads a local snapshot and never touches the network.

## 2 · Existing server inside an agent flow (≈2–3 min)

- [ ] Show `demo-vault/Objective.md` on screen. **This note is the input.** It names the three products, their current CPL, and the watchdog's proposed action for each.
- [ ] Start the agent:

  ```bash
  uv run python agent/run_agent.py
  ```

- [ ] Point at the printed `MCP connections discovered` block — both servers `connected`.
- [ ] Point at the first tool call: `vault_read` on `Objective.md`, and then measurement calls **for the products that note named**. Nothing is hard-coded — `grep -n "21-154" agent/run_agent.py` returns nothing.
- [ ] Explain `vault_read`'s contract: vault-relative path argument, resolves inside the configured vault only, returns note text, fails on a missing note, **no side effects**. Full write-up in `docs/tool-contracts.md`.

  ```bash
  uv run python scripts/capture_obsidian_contract.py vault_read
  ```

## 3 · Custom end-to-end workflow (≈3–4 min)

- [ ] Four substantive tools plus one helper, visible in the inspector or in the agent's calls.
- [ ] **Show an output schema, not just an input one.** In the inspector, open `measure_sku_funnel` → Output Schema: twenty typed fields, `reliability` an enum of three values, `window` a `$ref`. Say why it is there: a caller can validate a response instead of trusting it, and the tool returns structured content beside the JSON. The declarations live in `src/funnel_calibrator/contracts.py`.

  If asked why nothing is optional: the SDK marks every property required, so a `NotRequired` key would publish a schema the server's own responses fail. Conditional fields emit `null` instead — `breakeven_condition` is null unless the remedy is a price change. `tests/test_contracts.py::test_every_field_is_required` pins it.
- [ ] Let the flow complete: read journal → measure → recalibrate → audit → write verdict back.
- [ ] **All three watchdog proposals come back `contradicted`, with three different counter-recommendations.** That is the point: "the target was missed" is not one problem.

  | Product | Proposed | Verdict | Counter | Assumed Goal | Observed Stop | Sample | Reliability |
  |---|---|---|---|---:|---:|---:|---|
  | 21-154 | `scale` | contradicted | `stop` | $1.63 | **$1.61** | 95 | high |
  | 21-197 | `scale` | contradicted | `new_creative` | $2.16 | $2.17 | 31 | low |
  | 21-253 | `stop` | contradicted | `pause_retry` | $3.08 | $4.89 | 206 | high |

- [ ] **21-154 is the sharp one** — the failure the server exists to catch. Approval 59.0% (not 65%), buyout 45.3% (not 52.5%), so break-even falls to **$1.61** while $1.63 is being paid. `target_above_breakeven: true`, margin **−$0.02 per lead**. The note says it was scaled twice this month on cost per lead alone.
- [ ] **21-197 shows the tool declining to overreach.** Approval collapsed to 31.6%, so cheap leads are a traffic-quality artefact, not headroom — but the resolved sample is 31 against a threshold of 30, so reliability is `low` and the whole product is reported as provisional.
- [ ] **21-253 shows the opposite error.** It is the only product whose economics *improved* (+10.9%). The $6.00 CPL is genuinely unaffordable, but with a competitor active for five days the diagnosis is a contested auction — `pause_retry`, not `stop`. Stopping would retire a product that works.
- [ ] Explain `measure_sku_funnel` in depth, and why censoring lives in the server:

  > A parcel posted nine days ago is neither a buyout nor a return. Counting it as a non-buyout biases the rate downward, and worst exactly where the scale-or-stop decision is live — a newly launched product whose whole sample is recent. In the server, the exclusion applies on every call however the agent phrases the request. In a prompt, it holds until the context is long enough for the model to forget it.

- [ ] Show the vault note the agent wrote: `demo-vault/Decisions/<today>.md`.

## 4 · Failure and variation (≈2 min)

- [ ] **Existing-server failure.** In Obsidian, disable the Local REST API plugin, then:

  ```bash
  uv run python agent/run_agent.py
  ```

  The pre-flight names the endpoint and the refusal, and the run stops at exit code 2. Nothing is fabricated. Re-enable the plugin.

- [ ] **Wrong credential** — a different failure with a different message:

  ```bash
  OBSIDIAN_API_KEY=wrong uv run python agent/run_agent.py
  ```

- [ ] **Invalid input → error, not empty result:**

  ```bash
  uv run python -c "from funnel_calibrator import server as s; s.measure_sku_funnel('21-999')"
  ```

  Names the code and offers near matches.

- [ ] **Empty vs. error** — valid product, valid window, no orders. A *success*:

  ```bash
  uv run python -c "import json; from funnel_calibrator import server as s; print(json.dumps(s.measure_sku_funnel('21-253', window_from='2026-06-01', window_to='2026-06-02'), indent=1))"
  ```

  `resolved_orders: 0`, `reliability: "insufficient"`, rates `null`.

- [ ] **Changed valid input** — same product, different censoring, different answer:

  ```bash
  uv run python -c "from funnel_calibrator import server as s; [print(d, s.measure_sku_funnel('21-183', maturity_days=d)['resolved_orders']) for d in (0, 21, 45)]"
  ```

## 5 · Questions (≈3–4 min)

**Trace a value.** Take Stop CPL **$1.61** for 21-154 in the final note:

1. `recalibrate_cpl_bounds` returned it, with `inputs_used` showing price 690 ₴, COGS 350 ₴ (effective 2026-07-13), rate 45, upsell 95, return fee 94, call-centre fee 23.
2. The rates came from `measure_sku_funnel`: approval 95/161, buyout 43/95.
3. Those counts came from `data/snapshot.json` — 43 orders at status 12 and 52 at 28/32/35, all created on or before the cohort cutoff **2026-08-03**. Count them and show one:

   ```bash
   uv run python -c "import json; o=json.load(open('data/snapshot.json'))['orders']; m=[r for r in o if r['sku']=='21-154' and r['created_at']<='2026-08-03']; print('bought out', sum(1 for r in m if r['status_id']==12)); print('refused', sum(1 for r in m if r['status_id'] in (28,32,35))); print(json.dumps([r for r in m if r['status_id']==12][0], ensure_ascii=False))"
   ```

   Prints `bought out 43`, `refused 52` — the numerator and denominator of the 45.3% buyout rate.

4. That row's `order_id` is a real KeyCRM order.

**Where is the side effect?** One: `vault_write` creating `Decisions/<date>.md`. The calibrator is read-only and declares `readOnlyHint` on every tool; the agent is given no file, shell, or network tools at all.

**Why at the MCP boundary and not in the prompt?** Determinism (a business should not act on unit economics computed by a language model); unskippable guards (censoring and sample gating apply per call, not per remembered instruction); reuse by a scheduled routine and a second operator's tooling.

**Why four tools rather than one?** They make different kinds of claim — fact, arithmetic, judgement, validation — and fail in different ways. A bad measurement is a data problem; a bad recommendation is a policy problem. Merging them hides which one you are trusting.

**What does it refuse to answer?** Any product below 30 resolved orders. 35 of 56 products in this snapshot fall there. Replacing a portfolio constant with a rate drawn from eleven orders swaps one false certainty for another.

**What if the snapshot were a week stale?** Every rate would be measured against an older cutoff, so recent cohorts would be missing and rates would lean on older ones. The signal moves on a scale of weeks, so a week is tolerable and `snapshot_generated_at` rides on every response so a caller can see the age. Re-export with `scripts/export_snapshot.py`.

**Anything you found that you did not expect?** Status 35 — 216 shipped orders that the business's own reporting classifies as `unknown` and counts nowhere. `docs/design-rationale.md` §5 has the evidence.

## Do not

- Open a personal vault, or anything confidential
- Show `.env`, the Obsidian key, or the CRM worker secret on screen
- Claim a break-even figure is a forecast — it is a condition, not a prediction
- Claim the server writes anything. It does not
