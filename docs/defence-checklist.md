# Defence checklist

Individual defence, 10–15 minutes. Target sequence and the evidence each step must show.

> Status: skeleton. Exact commands and timings filled in after the build.

## Before starting

- [ ] Snapshot dataset present and anonymised; `git status` clean
- [ ] `.env` configured; **screen shows no secrets** (close editors with `.env` open)
- [ ] Obsidian running with Local REST API enabled; demo vault open — *not* a personal vault
- [ ] Terminal font large enough for tool calls and outputs to be legible on the recording
- [ ] A second terminal ready for the failure demonstration

## 1 · Independent startup and architecture (≈2 min)

- [ ] Start the custom server **on its own**, before the agent, in its own terminal — shows process separation
- [ ] Start the agent; show it discovering **both** MCP connections and listing tools
- [ ] State the problem in one sentence: COD feedback arrives weeks after the spend, so ad targets run on assumed constants that individual products violate

## 2 · Existing server inside an agent flow (≈2–3 min)

- [ ] Invoke an Obsidian tool successfully and show the result
- [ ] Show that the vault's content **drives what happens next** — the objective read from the note determines which product is measured
- [ ] Explain that tool's contract: name, arguments and constraints, what it returns, how it fails, what it changes

## 3 · Custom end-to-end workflow (≈3–4 min)

- [ ] Show all four tools exposed
- [ ] Run the full flow: read journal → measure → recalibrate → recommend → audit → write verdict back
- [ ] Show a verdict being **overturned** by calibration — the assumed bound says proceed, the observed bound says stop
- [ ] Explain one contract in depth: `measure_sku_funnel`, and why cohort censoring is in the server rather than the prompt

## 4 · Failure and variation (≈2 min)

- [ ] **Existing-server failure:** stop the Obsidian plugin mid-flow; show how the agent reports the lost connection rather than fabricating a result
- [ ] **Invalid input:** unknown product code → error naming the input, *not* an empty result
- [ ] **Changed valid input:** re-run on a different product and show the output change
- [ ] **Empty vs. error:** valid product, empty window → success with `reliability: "insufficient"`

## 5 · Questions (≈3–4 min)

Be ready to answer:

- [ ] **Trace a value:** pick a number in the final note and walk it back through the tools to the snapshot row it came from
- [ ] Where is the side effect, and what exactly changes? (Only the vault note.)
- [ ] Why does this belong at the MCP boundary rather than in the agent prompt?
- [ ] Why four tools instead of one?
- [ ] What does the tool refuse to answer, and why is refusing correct?
- [ ] What would break if the snapshot were a week stale?

## Do not

- Open a personal vault, or one containing anything confidential
- Show `.env`, API keys, or the Obsidian token on screen
- Claim a simulated break-even figure is a forecast — it is a condition, not a prediction
