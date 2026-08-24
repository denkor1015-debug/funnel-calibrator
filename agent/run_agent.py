#!/usr/bin/env python3
"""End-to-end agent flow across both MCP connections.

    vault (Obsidian)  ──►  measure  ──►  recalibrate  ──►  recommend
                                                              │
                       ◄── written back to the vault ◄── audit ┘

The Obsidian vault is the input, not a sink: the objective note names which
products are examined and which proposed decisions are audited. The custom
server supplies the numbers those decisions are judged against.

Run:
    uv run python agent/run_agent.py
    uv run python agent/run_agent.py --dry-run     # check connections only

The Claude Agent SDK inherits the Claude Code CLI's own authentication, so no
Anthropic API key is set or needed here. The only secret in play is the
Obsidian plugin's token, which is read from the environment.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    query,
)
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent
VAULT = REPO / "demo-vault"

load_dotenv(REPO / ".env")


class ConnectionFailure(RuntimeError):
    """An MCP server did not come up. Reported, never worked around."""


def obsidian_config() -> dict[str, object]:
    """Streamable-HTTP config for the Local REST API plugin's MCP server.

    The plugin serves HTTPS on 27124 behind a self-signed certificate and plain
    HTTP on 27123. Set OBSIDIAN_PORT=27123 when the certificate is rejected —
    it is a local loopback connection either way.
    """
    token = os.environ.get("OBSIDIAN_API_KEY", "").strip()
    if not token:
        raise ConnectionFailure(
            "OBSIDIAN_API_KEY is not set. Copy the key from Obsidian → "
            "Settings → Local REST API into .env. See demo-vault/README.md."
        )
    host = os.environ.get("OBSIDIAN_HOST", "127.0.0.1")
    port = os.environ.get("OBSIDIAN_PORT", "27124")
    scheme = "https" if port == "27124" else "http"
    return {
        "type": "http",
        "url": f"{scheme}://{host}:{port}/mcp/",
        "headers": {"Authorization": f"Bearer {token}"},
    }


def preflight_obsidian(config: dict[str, object]) -> None:
    """Reach the plugin directly before the agent starts.

    Diagnosing a dead connection from inside an agent transcript is miserable:
    the model reports "the tool failed" and the actual cause — plugin off,
    wrong port, stale token — stays hidden. One request here names it.
    """
    import ssl
    import urllib.error
    import urllib.request

    url = str(config["url"])
    headers = dict(config["headers"])  # type: ignore[arg-type]
    # The plugin ships a self-signed certificate for 127.0.0.1. Verification is
    # skipped for this probe only, on a loopback address; the agent's own
    # connection is made by the CLI and is unaffected by this.
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    request = urllib.request.Request(url.rstrip("/"), headers=headers, method="GET")
    try:
        urllib.request.urlopen(request, timeout=5, context=context)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ConnectionFailure(
                f"Obsidian rejected the API key at {url} (HTTP {exc.code}). "
                "Copy the current key from Settings → Local REST API into .env."
            ) from exc
        # Anything else means something answered, which is all this checks.
    except urllib.error.URLError as exc:
        raise ConnectionFailure(
            f"Nothing is listening at {url} ({exc.reason}). Start Obsidian "
            "with the Local REST API plugin enabled, or set OBSIDIAN_PORT="
            "27123 to use the plugin's plain-HTTP port."
        ) from exc


def cli_env() -> dict[str, str]:
    """Environment for the Claude Code CLI process that hosts the MCP client.

    The plugin's HTTPS listener uses a certificate it generates itself, which
    Node rejects — the connection fails while a curl with verification off
    succeeds, which is a confusing pair of symptoms. Two ways out, and this
    supports both:

      · point OBSIDIAN_CA_CERT at the certificate the plugin offers to export,
        which makes Node trust that one certificate and nothing else; or
      · set OBSIDIAN_PORT=27123 and enable the plugin's plain-HTTP listener.
        The traffic never leaves the loopback interface and the key is still
        required, so this is a reasonable trade on a local machine.

    Disabling Node's certificate verification wholesale is deliberately not
    offered: it would apply to every connection the CLI makes, not just this one.
    """
    env = {"OBSIDIAN_VAULT_PATH": str(VAULT)}
    ca_cert = os.environ.get("OBSIDIAN_CA_CERT", "").strip()
    if ca_cert:
        path = Path(ca_cert).expanduser()
        if not path.exists():
            raise ConnectionFailure(
                f"OBSIDIAN_CA_CERT points at {path}, which does not exist. "
                "Export the certificate from the plugin's settings, or unset "
                "the variable and use OBSIDIAN_PORT=27123 instead."
            )
        env["NODE_EXTRA_CA_CERTS"] = str(path)
    return env


def calibrator_config() -> dict[str, object]:
    """The custom server, launched as a separate process over stdio.

    Started by the agent here for convenience; `uv run funnel-calibrator`
    starts the identical process by hand, which is what the defence shows
    first to make the process separation visible.
    """
    return {
        "type": "stdio",
        "command": "uv",
        "args": ["--directory", str(REPO), "run", "funnel-calibrator"],
        "env": {"FC_SNAPSHOT_PATH": os.environ.get("FC_SNAPSHOT_PATH", "data/snapshot.json")},
    }


PROMPT = f"""\
You are calibrating today's advertising decisions for a cash-on-delivery
clothing business. Two MCP servers are connected: `obsidian` (the decision
journal) and `funnel-calibrator` (the measurement and economics server).

Work through these steps in order. Each step depends on the previous one.

1. Read `Objective.md` from the Obsidian vault. It names the products in play,
   their current cost per lead, and the action the daily watchdog has proposed
   for each. Everything you do next comes from that note — do not assume which
   products to look at.

2. For each product named in the note, call `measure_sku_funnel` to get its own
   approval and buyout rates. Note the sample size and reliability flag.

3. For each product, call `recalibrate_cpl_bounds` to get its true Stop and Goal
   CPL from those measured rates, and the drift against the assumed baseline.
   Pay attention to `target_above_breakeven`: when it is true, the target the
   business is steering by sits above the point where the product stops paying.

4. For each product, call `audit_ad_verdict` with the watchdog's proposed action
   and the current CPL from the note, passing `source` so the record shows where
   the proposal came from. Where the note mentions a competitor on a product,
   pass `competitor_active` and `cpl_trend_days` — the remedy for a contested
   auction differs from the remedy for a weak product.

5. Write the result to `Decisions/{date.today().isoformat()}.md` in the vault,
   creating the file. Structure it as:

   - a one-paragraph summary of what changed against the assumptions;
   - a table with one row per product: proposed action, verdict, assumed Goal
     CPL, observed Stop CPL, sample size, reliability;
   - for each product, two or three sentences on the evidence, quoting the
     actual numbers the tools returned;
   - a short "what to do" list.

Rules. Use only numbers the tools returned — never compute a rate or a bound
yourself, and never fill a gap with the portfolio assumptions. Where a tool
reports `insufficient`, say the evidence is too thin rather than choosing an
action. If a tool call fails, report the failure and what it prevented; do not
continue as though it succeeded.
"""


def render_status(data: dict) -> list[tuple[str, str]]:
    servers = data.get("mcp_servers") or []
    rows = []
    for entry in servers:
        if isinstance(entry, dict):
            rows.append((str(entry.get("name", "?")), str(entry.get("status", "?"))))
        else:
            rows.append((str(getattr(entry, "name", "?")), str(getattr(entry, "status", "?"))))
    return rows


def check_connections(rows: list[tuple[str, str]]) -> None:
    """Both servers must be connected before anything is trusted.

    A failed connection that the agent talks past produces an answer with
    nothing behind it — the exact failure mode the defence has to rule out.
    """
    print("\nMCP connections discovered:")
    for name, status in rows:
        mark = "ok" if status == "connected" else "FAILED"
        print(f"  [{mark:>6}]  {name:<20} {status}")

    broken = [f"{n} ({s})" for n, s in rows if s != "connected"]
    if broken:
        raise ConnectionFailure(
            "Not every MCP server connected: " + ", ".join(broken) + ". "
            "Nothing below this point would be trustworthy, so the run stops "
            "here. For `obsidian`: check Obsidian is running with the Local "
            "REST API plugin enabled, and that OBSIDIAN_API_KEY matches the "
            "key in its settings."
        )
    if len(rows) < 2:
        raise ConnectionFailure(
            f"Expected two MCP servers, found {len(rows)}: " + ", ".join(n for n, _ in rows)
        )


async def run(dry_run: bool) -> int:
    obsidian = obsidian_config()
    preflight_obsidian(obsidian)

    options = ClaudeAgentOptions(
        mcp_servers={
            "funnel-calibrator": calibrator_config(),
            "obsidian": obsidian,
        },
        allowed_tools=["mcp__funnel-calibrator__*", "mcp__obsidian__*"],
        # Exactly these two servers, and nothing the host happens to have
        # configured. Without this the run inherits whatever connectors the
        # developer's own CLI holds — noise in the demonstration, and a real
        # privacy problem in a business account.
        strict_mcp_config=True,
        # The agent's only permitted side effect is the vault note. It has no
        # file, shell, or network tools, so it cannot touch the business.
        tools=[],
        permission_mode="acceptEdits",
        cwd=str(REPO),
        max_turns=40,
        setting_sources=None,
        env=cli_env(),
    )

    prompt = "List the tools available from both MCP servers, then stop." if dry_run else PROMPT

    checked = False
    failure: ConnectionFailure | None = None
    exit_code = 0

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, SystemMessage) and message.subtype == "init":
                checked = True
                try:
                    check_connections(render_status(message.data))
                except ConnectionFailure as exc:
                    # Recorded and raised after the stream, not here: raising
                    # mid-iteration tears the generator down while it is still
                    # running, and that cleanup error would bury the real cause.
                    failure = exc
                    break
                print("\n─── agent flow ───")
                continue

            exit_code = handle(message) or exit_code
    except RuntimeError as exc:
        # Abandoning the SDK's stream makes it complain while tearing down its
        # own task group. When we already know why we stopped, that noise must
        # not replace the diagnosis.
        if failure is None or "aclose" not in str(exc):
            raise

    if failure is not None:
        raise failure
    if not checked:
        raise ConnectionFailure(
            "The agent never reported an init message, so no MCP connection "
            "was established. Check that the Claude Code CLI is installed and "
            "authenticated."
        )
    return exit_code


def handle(message: object) -> int | None:
    """Print one streamed message. Returns a non-zero code only on failure.

    Tool calls are printed as they happen, with the arguments that carry
    meaning — the defence has to show which product each call was made for.
    """
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, ToolUseBlock):
                args = {
                    k: v
                    for k, v in (block.input or {}).items()
                    if k in ("sku", "proposed_action", "current_cpl", "filename", "path", "source")
                }
                print(f"  → {block.name}({args})")
            elif isinstance(block, TextBlock) and block.text.strip():
                print(f"\n{block.text.strip()}\n")

    elif isinstance(message, ResultMessage):
        print("─── done ───")
        if message.is_error:
            print("Run ended in error.", file=sys.stderr)
            return 1
        note = VAULT / "Decisions" / f"{date.today().isoformat()}.md"
        print(f"Vault note: {note} — {'written' if note.exists() else 'NOT written'}")
        if message.total_cost_usd:
            print(f"Cost: ${message.total_cost_usd:.4f}")

    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Connect and list tools from both servers, then stop.",
    )
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(run(args.dry_run)))
    except ConnectionFailure as exc:
        print(f"\nConnection failure: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
