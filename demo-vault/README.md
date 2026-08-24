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
5. In the same settings pane, enable **Enable Non-encrypted (HTTP) Server**,
   and set `OBSIDIAN_PORT=27123` in `.env`. See below for why this is needed
   rather than optional.

To write the key without it appearing on screen or in shell history, copy it in
Obsidian and then:

```bash
grep -v '^OBSIDIAN_API_KEY=' .env > .env.new && printf 'OBSIDIAN_API_KEY=%s\n' "$(pbpaste)" >> .env.new && mv .env.new .env && chmod 600 .env
```

## Why plain HTTP on 27123

The plugin's HTTPS listener on 27124 presents a certificate it generated
itself. Node — which runs the Claude Code CLI hosting the MCP client — rejects
it, so the connection fails. The symptoms are confusing: a request with
verification disabled succeeds while the agent's own connection does not.

Two ways out, and `agent/run_agent.py` supports both:

- **`OBSIDIAN_PORT=27123`** with the plugin's plain-HTTP listener enabled. The
  traffic never leaves the loopback interface and the API key is still
  required, so this is a reasonable trade on a local machine. This is what the
  committed configuration uses.
- **`OBSIDIAN_CA_CERT=/path/to/cert.pem`**, pointing at the certificate the
  plugin offers to export. This is passed to the CLI as `NODE_EXTRA_CA_CERTS`,
  which makes Node trust that one certificate and nothing else.

Disabling Node's certificate verification wholesale is deliberately not
offered: it would apply to every connection the CLI makes, not just this one.

## Resetting between runs

Delete the files under `Decisions/` (keep `.gitkeep`). The agent creates the
day's note fresh on each run.
