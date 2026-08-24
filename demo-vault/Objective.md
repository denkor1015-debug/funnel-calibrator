# Advertising objective — 24 August 2026

The agent reads this note first. What it says here decides which products get
measured and which proposed decisions get audited, so this file is the input to
the flow rather than a place the output is filed.

## Today's question

Three products are running. The daily watchdog has proposed an action for each,
using the portfolio-wide assumptions — 65% approval, 52.5% buyout. Before any of
them is acted on, check each proposal against what the product's own funnel
actually did.

| Product | Current CPL (USD) | Watchdog proposal | Stated reason |
|---|---:|---|---|
| 21-154 | 1.63 | `scale` | "CPL is under the $2.55 goal — room to buy more." |
| 21-197 | 1.20 | `scale` | "Cheapest leads in the account." |
| 21-253 | 6.00 | `stop` | "CPL well over goal for five days." |

For 21-253, note that a competitor has been bidding on this product for the past
five days.

## Yesterday's conclusions

- The portfolio buyout assumption of 52.5% was last re-measured in June. Several
  products have moved since, and nothing re-checks them between monthly closes.
- 21-154 has been scaled twice this month on the strength of a low cost per lead.
  Nobody has looked at what happens to those orders after the call.
- Open question carried over: refusal statuses moved partway through the summer.
  Any funnel figure built on a single refusal status is suspect.

## What to produce

For each product: measure its own funnel, recalibrate its bounds from those
rates, and audit the watchdog's proposal against the corrected numbers. Write
the result to `Decisions/2026-08-24.md` with the evidence chain — the sample it
rests on, the assumed bound, the observed bound, and the verdict.

Where the evidence is too thin to judge, say so instead of choosing.
