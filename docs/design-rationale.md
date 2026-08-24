# Design rationale

> Revised 24 August 2026, after the build. Two things changed against the version written ahead of it, and both are recorded rather than quietly fixed: the worked example in §1 was arithmetically wrong in the business's favour, and the status taxonomy in §5 was missing a refusal status that nothing in the business counts at all.

## 1. The problem, stated precisely

In a cash-on-delivery business, the feedback signal that tells you whether an advertising decision was correct arrives two to four weeks after the money is spent. The customer pays when the parcel is collected, and roughly half of them do not collect it.

The business bridges that delay with assumed constants. Every product's break-even cost-per-lead is computed as:

```
returns_cost = ((1 - buyout) / buyout) * return_fee
contribution = price + upsell - cogs - returns_cost - call_centre_fee
stop_cpl     = contribution * (approval * buyout) / usd_uah
```

with `approval = 0.65` and `buyout = 0.525` — portfolio averages, applied uniformly to every product.

The constants are not wrong on average. They are wrong *per product*, and the error is not symmetric in consequence. Measured divergences in the source business: one manufacturer's products buy out at 37%; one product's call-centre approval measured 53%; buyout tracks price band, from roughly 93% in the 690–790 ₴ range to roughly 55% above 1290 ₴.

Worked example, using the business's own formula on a real product — article 17-252, price 1499 ₴, COGS 990 ₴:

| | Assumed (65% / 52.5%) | Observed at 37% buyout |
|---|---|---|
| Returns cost per buyout | 85 ₴ | 160 ₴ |
| Call-centre cost per buyout | 44 ₴ | **62 ₴** |
| Contribution before ads | 475 ₴ | **382 ₴** |
| **Stop CPL** (break-even) | **$3.60** | **$2.04** |
| **Goal CPL** (target) | **$2.52** | **$1.43** |

The assumed *target* of $2.52 sits **above** the true *break-even* of $2.04. Optimising toward that target loses money on every lead, and nothing in the advertising dashboard shows it: cost-per-lead looks healthy, because the failure happens later, at the post office.

> **Correction.** The version of this table written before the build gave contribution 400 ₴ and Stop $2.14, holding the call-centre fee constant at 44 ₴. That is wrong: the fee is paid per *confirmed order*, not per parcel collected, so at 37% buyout the same fee spreads over fewer collections and rises to `(1 / 0.37) × 23 = 62 ₴`. Correctly scaled, contribution is 382 ₴ and Stop CPL is $2.04 — the argument gets stronger, not weaker. The error is worth naming because it is the same error the whole project is about: an assumption held fixed while the thing it depends on moved. `tests/test_calibration.py::test_call_centre_fee_scales_with_buyout` pins the corrected figures so it cannot come back.

This is an open-loop control system. Measurement exists — the CRM records every resolution — but it never returns to the decision. It surfaces at the monthly financial close, by which point a month of budget has been committed.

### What the built system found

Run against 4 132 real orders (1 June – 24 August 2026, 51 products), the failure above is not hypothetical. Article **21-154**, on a sample of 95 resolved orders and therefore `high` reliability:

| | Assumed | Observed |
|---|---|---|
| Approval | 65% | **59.0%** |
| Buyout | 52.5% | **45.3%** |
| Stop CPL | $2.32 | **$1.61** |
| Goal CPL | **$1.63** | $1.12 |

The assumed **target** of $1.63 sits above the true **break-even** of $1.61. The product had been scaled twice this month on the strength of a cost per lead inside its goal.

## 2. Why this belongs at the MCP boundary

The calculation above is not hard. Its difficulty is entirely in *when it is applied* and *what it is trusted for*, which is an interface problem, not an arithmetic one.

Three reasons the calibration is exposed as MCP tools rather than folded into the agent's prompt or a local script:

**Determinism where it matters.** The recomputation must be reproducible and identical on every call. Unit economics decided by a language model's arithmetic is not something a business should act on. Fixing the formula in a server, behind a typed contract, makes the numbers auditable and the model's role interpretive rather than computational.

**The guards must be unskippable.** Censoring and sample-size gating are the difference between a measurement and a plausible-looking fiction. Placed in the server, they apply on every call regardless of how the agent phrases its request. Placed in a prompt, they hold until the context is long enough for the model to forget them.

**Composability across hosts.** The same server is usable by the interactive agent, by a scheduled routine, and later by a second operator's tooling. A script embedded in one agent is not.

The counterargument, honestly: a fourth tool that merely audits a proposed decision could be an agent-side prompt over the other three tools' outputs. It is exposed as a tool because the *verdict boundary* — the point where the system says "this decision is contradicted by evidence" — is the thing that must be logged, tested, and later measured for accuracy. That is worth a contract.

## 3. Why Obsidian

The agent's output is a judgement about money, and judgements about money need to be reviewable after the fact — both to defend them and to grade the policy that produced them.

Obsidian is the decision journal. The agent reads the day's objective and the previous session's conclusions from the vault, and writes back the calibrated verdict with its evidence chain: what was measured, on what sample, what the corrected bounds were, and which proposed decisions the evidence overturned.

This is a genuine role rather than a token integration, on three counts. The vault's contents **determine what the agent measures** — it is the input to step one, not a sink at the end. The written note is **human-readable prose with structure**, which is what makes it reviewable weeks later, and is the format Obsidian is actually good at. And the journal accumulates into the dataset needed to evaluate the recommendation policy itself: of the last twenty "pause and retry" recommendations, how many restarts succeeded?

A database would store the same fields. It would not be read by a person on a Sunday evening.

## 4. Tool boundaries

Four tools, split by *what kind of claim each makes*:

| Tool | Claim | Why separate |
|---|---|---|
| `measure_sku_funnel` | "This is what happened." | Pure observation over the dataset. No economics, no opinion. Separating it means the measurement can be trusted and reused even when the economics change. |
| `recalibrate_cpl_bounds` | "This is what it implies for the bounds." | Deterministic economics. Depends on measurement but not on any proposed action. |
| `recommend_next_action` | "This is the likeliest cause and the matching remedy." | Diagnosis, and the only tool encoding business judgement. Isolated so its rules are inspectable and revisable without touching the arithmetic. |
| `audit_ad_verdict` | "This proposed decision is supported / contradicted." | Validation of an *external* proposal. Distinct in direction: the others produce conclusions, this one tests one. |

The split follows the seam between fact, arithmetic, judgement, and validation. Merging any two would blur what a caller is trusting when it accepts a result — and the failure modes differ: a bad measurement is a data problem, a bad recommendation is a policy problem, and they should not be diagnosed together.

`recommend_next_action` deserves specific defence, because "CPL too high" is not one problem:

| Evidence | Diagnosis | Action |
|---|---|---|
| CPL above stop, sustained, no competitor on the product | Weak offer or creative | `stop`, then autopsy on creative metrics |
| CPL spike above 40%, held for days, competitor active on the same product | Contested auction | `pause_retry` — the auction, not the product, is the problem |
| CPL healthy, **approval rate collapsed** | Traffic quality — cheap leads, weak intent | `new_creative` / audience change. Not a price problem |
| CPL healthy, **buyout collapsed** | Offer problem — price band, sizing, expectation gap | `reprice` or fix sizing. Not a creative problem |
| Contribution ≤ 0 at any CPL | Structural loss | `full_stop` — no cost-per-lead saves it |
| CPL drifting up over weeks, frequency rising | Creative fatigue | `refresh_creative` before killing the product |

Two products can present the identical symptom — a missed target — and require opposite remedies. Recommending a price cut for a targeting problem makes the business worse. This table is the tool's reason for existing.

## 5. Handling the hard measurement problems

### The status taxonomy, and the refusal nobody counts

Before a rate can be measured at all, every CRM status has to be sorted into what it says about two different outcomes: did the call centre approve the order, and was the parcel collected. Getting that sorting wrong does not raise an error — it silently changes the answer.

The taxonomy in `snapshot.py` was therefore derived from evidence rather than inherited from the business's existing reports. Every status in the dataset was checked two ways: whether its orders carry a waybill, and how its counts move month by month.

That turned up a status the business does not count anywhere. **35 "Відмова"** — 216 orders — is absent from the CRM's own status list, and the reporting layer classifies it as `unknown`, so it falls out of every funnel figure. Two independent checks place it:

- **All 216 carry a waybill.** So do all of statuses 12, 28 and 32; no cancelled-before-shipment status does (status 19 "Скасовано" is 812 without a waybill against 85 with). Whatever 35 means, those parcels were shipped.
- **The monthly pattern is a handover.** Refusals run 32 through July, 35 appearing in July, 28 taking over in August:

  | | June | July | August |
  |---|---:|---:|---:|
  | 32 Відмова на пошті | 457 | 201 | 0 |
  | 35 Відмова | 0 | 155 | 61 |
  | 28 Повернення назад | 0 | 0 | 119 |

Counting all three, the portfolio buyout rate reads 53.4% in June and 56.4% in July — either side of the business's own measured 52.5%. Dropping 35 reads July as **69.6%**, which no other evidence supports. The taxonomy is pinned by `tests/test_measurement.py::test_every_refusal_status_is_counted`.

This matters beyond one status. It is the same class of failure as the assumed constants: a definition set once, and then quietly outrun by the thing it describes.

### The two hard measurement problems

**Censoring.** An order placed nine days ago is neither a buyout nor a return; it is in transit. Including it as a non-buyout biases the rate downward, and the bias is worst exactly where it hurts most — on newly launched products, where the entire sample is recent, and where the decision to scale or stop is being made right now.

The server excludes cohorts younger than a configurable maturity window (default 21 days) and reports how many orders were set aside. This is visible in output rather than silent, because the exclusion is itself information: "measured on 84 resolved orders, 12 still in flight" tells the caller how provisional the answer is.

**Small samples.** Per product, per size, per colour, counts fall off quickly. Five extra returns in a 40-order cell is noise that looks like signal. Every measurement carries its sample size and a reliability flag, and below the configured threshold the server returns `insufficient` rather than a number.

Declining to answer is a feature. The system's purpose is to stop the business acting on assumptions it cannot support; replacing a portfolio constant with a confidently-stated measurement drawn from eleven orders would substitute one false certainty for another.

## 6. Errors and empty results

A tool must let the caller distinguish three outcomes that a naive implementation conflates:

- **Success with data** — measured rates, with reliability.
- **Success, genuinely empty** — the product exists, the window is valid, and no orders fall in it. Not an error.
- **Failure** — unknown product code, malformed window, unreadable snapshot.

These are returned distinctly: empty results carry `reliability: "insufficient"` with `resolved_orders: 0`, while failures raise an MCP tool error naming the offending input. Conflating them would let an agent read a typo in a product code as evidence that a product has no orders — and recommend stopping a campaign on that basis.

## 7. Trade-offs and known limitations

**The snapshot is stale by construction.** The server reads a point-in-time export, not the live CRM. This buys determinism, reproducibility, and freedom from authentication — the demonstration runs identically on any machine, offline. The cost is that operational use requires a refresh step. This is the right trade for a graded demonstration and an acceptable one in production, where the underlying signal moves on a scale of weeks.

**Correlation, not causation.** The data shows *which* orders fail, never *why*. A product may buy out poorly because of sizing, photography, price, or a call-centre script — and the dataset cannot separate these. The one genuine reason code available is the "wrong size / size unavailable" status. `recommend_next_action` therefore returns the *likeliest* failure mode with its supporting evidence, and is deliberately built to be overridden by a human who knows something the data does not.

**Break-even simulation is arithmetic, not prophecy.** Where a recommendation involves a price change, the server computes the break-even condition — "this pays for itself only if buyout rises at least 3.1 points" — rather than predicting the new buyout rate. The price-elasticity relationship is evidenced but weakly, and presenting a simulated outcome as a forecast would overstate what the data supports.

**Read-only by design.** The server changes no advertising campaign, no price, and no CRM record. Its only side effect is the note the agent writes to the Obsidian vault. This is a deliberate limit on autonomy: the calibration should earn trust as an advisor across a season of decisions before it is given hands. A production version would graduate actions by reversibility — pausing an overspending campaign is cheap and undoable; changing a price touches the CRM, the landing page, and the customer's expectations, and should stay human.

### Limitations the build exposed that the design did not anticipate

**Attribution is a join, and the join was nearly wrong.** An order line carries the *offer's* SKU — a serial identifying one colour and size, like `1256` — not the product code the business advertises and prices by, like `2614`. Both are bare numbers, neither contains the other, and the campaign name that would disambiguate them is not part of the order line. Parsing a code out of the order string, which is the obvious implementation, attributes orders to the wrong products *silently*: the rates still look plausible. The exporter therefore builds an explicit offer-to-product map from the catalogue (1 920 offer SKUs) and records, per order, which route produced the code — `offer_map` for 3 943 of 4 132 orders, the campaign name as a documented fallback for 189. This was found by probing the CRM's actual response shape rather than by reading its documentation, and it would not have been found by testing against the tidy fixture the tests use.

**Thin samples are the normal case, not the exception.** Of the 51 products with orders in the window, **21** clear the 30-resolved-order threshold and only **7** reach `high` reliability; a further filter applies, because only **15** of those also have price and cost on file and can therefore be recalibrated at all. The gating is not a defensive corner case — it fires on most of the portfolio. That is a real limit on what the server can offer: for roughly two thirds of products its honest answer is that it cannot say, and the portfolio constant remains the only available number. Widening the window trades that against staleness rather than removing it.

**A schema can exist and still say nothing.** Every tool was typed on the way
in — constrained integers, ISO dates, enumerated actions — and the input
schemas MCP published were genuinely useful. The output side looked done for
the same reason and was not: annotating a tool `-> dict[str, Any]` publishes
`{"additionalProperties": true}`, a schema that satisfies the letter of "expose
an output schema" while telling a caller nothing. The fix was to declare each
return as a `TypedDict` (`contracts.py`), which took the published schema for
`measure_sku_funnel` from zero described fields to twenty.

Doing it surfaced a second thing worth recording, because it fails in a
misleading way. The SDK marks **every** property of an output schema as
required, so a `NotRequired` key produces a schema the server's own successful
responses fail to validate against — and the tool call comes back as an error
that reads like a data problem. Two payload fields were genuinely conditional:
the break-even condition, which only a price remedy carries, and three
evidence fields the diagnosis tree never computes when it returns early. Both
now emit the key with `null`. That is the better contract regardless of the
constraint: a caller can rely on the key set, and `null` here already carries
meaning elsewhere — a null buyout rate means "measured, sample too thin to
report", which is a finding rather than an absence.

**Rate limits shape the export.** The CRM answers HTTP 429 under sustained polling, which the first export run hit after roughly 80 requests. The exporter now throttles, backs off exponentially, and checkpoints its offer map after every product so an interrupted run resumes rather than restarts. Worth stating because the runtime path has no such fragility at all — the server reads a local file — but the step that *produces* that file does.
