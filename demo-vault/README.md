# Demo vault

A deliberately small Obsidian vault, committed so the demonstration is
reproducible on any machine. **It is not a personal vault** — it contains
nothing but the two files the agent flow uses, per the assignment's requirement
to keep a demonstration vault free of anything sensitive.

- `Objective.md` — the day's advertising objective and the previous session's
  conclusions. The agent reads this first, and its contents determine which
  products are measured and which proposals are audited.
- `Decisions/` — where the agent writes `YYYY-MM-DD.md`, the calibrated verdict
  with its evidence chain. Empty until a run completes.

## One-time setup

1. Open Obsidian → **Open folder as vault** → select this `demo-vault` folder.
2. **Settings → Community plugins → Browse** → install and enable
   **Local REST API** ([coddingtonbear/obsidian-local-rest-api](https://github.com/coddingtonbear/obsidian-local-rest-api)).
3. In the plugin's settings, copy the generated API key.
4. Put it in the repository's `.env` as `OBSIDIAN_API_KEY=…`. The key is a
   secret: `.env` is git-ignored and the value never appears in source.

The plugin serves HTTPS on `127.0.0.1:27124` with a self-signed certificate, and
plain HTTP on `27123`. `agent/run_agent.py` uses 27124 by default and falls back
to 27123 if the certificate is rejected — set `OBSIDIAN_PORT=27123` to force it.

## Resetting between runs

Delete the files under `Decisions/` (keep `.gitkeep`). The agent creates the
day's note fresh on each run.
