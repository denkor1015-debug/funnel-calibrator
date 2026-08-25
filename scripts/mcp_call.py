#!/usr/bin/env python3
"""Call one tool on the calibrator over real MCP, from the command line.

Why this exists. Importing `funnel_calibrator.server` and calling a function is
not the same thing as calling a tool, and this project has the scar to prove it:
a `NotRequired` key in an output contract once left all 56 tests passing — they
call the functions directly — while every call over the protocol came back an
error, because the SDK marks every published property required. A demonstration
that only ever calls Python functions therefore demonstrates the arithmetic, not
the server.

The MCP Inspector shows the same thing with a GUI. This is the typed-command
form: no browser, no clicking, one line per case, and the part that matters
printed first — whether the protocol classed the result as an error.

Usage
-----
    uv run python scripts/mcp_call.py --list

    uv run python scripts/mcp_call.py measure_sku_funnel sku=21-154
    uv run python scripts/mcp_call.py measure_sku_funnel sku=21-999
    uv run python scripts/mcp_call.py measure_sku_funnel sku=21-183 maturity_days=45

Add `--json` to print only the payload, which makes the output composable:

    uv run python scripts/mcp_call.py measure_sku_funnel sku=21-183 maturity_days=45 --json

Arguments are `name=value`. Values are parsed as JSON when they parse and kept
as strings when they do not, so `maturity_days=45` arrives as a number and
`sku=21-154` as a string.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_VERSION = "2024-11-05"


class ServerGone(RuntimeError):
    """The server closed the pipe before answering."""


def _coerce(raw: str) -> object:
    """`maturity_days=45` should arrive as a number, `sku=21-154` as a string."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _parse_args(pairs: list[str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"Argument {pair!r} is not in name=value form.")
        name, _, raw = pair.partition("=")
        out[name] = _coerce(raw)
    return out


def _request(proc: subprocess.Popen[str], payload: dict[str, object]) -> dict:
    """Send one JSON-RPC request and return the first reply carrying an id.

    Notifications and log lines are skipped rather than treated as answers,
    which is what any conforming client does.
    """
    assert proc.stdin and proc.stdout
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if not line:
            raise ServerGone("The server closed stdout before replying.")
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" in message:
            return message


def _notify(proc: subprocess.Popen[str], method: str) -> None:
    assert proc.stdin
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
    proc.stdin.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tool", nargs="?", help="Tool name, e.g. measure_sku_funnel")
    parser.add_argument("arguments", nargs="*", help="name=value pairs")
    parser.add_argument("--list", action="store_true", help="List the tools the server publishes and exit")
    parser.add_argument("--json", action="store_true", help="Print only the payload, so the output composes with other commands")
    args = parser.parse_args()

    if not args.list and not args.tool:
        parser.error("give a tool name, or --list")

    # The same launch line any MCP host uses — a separate process over stdio.
    proc = subprocess.Popen(
        ["uv", "run", "funnel-calibrator"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    try:
        hello = _request(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcp_call", "version": "1"},
            },
        })
        server = hello.get("result", {}).get("serverInfo", {})
        if not args.json:
            print(f"→ connected to {server.get('name', '?')} {server.get('version', '')}".rstrip())
        _notify(proc, "notifications/initialized")

        if args.list:
            reply = _request(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            for tool in reply.get("result", {}).get("tools", []):
                published = len(tool.get("outputSchema", {}).get("properties", {}))
                print(f"  {tool['name']:<24} output schema: {published} fields")
            return 0

        call = _parse_args(args.arguments)
        if not args.json:
            print(f"→ tools/call {args.tool} {json.dumps(call, ensure_ascii=False)}\n")
        reply = _request(proc, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": args.tool, "arguments": call},
        })

        # A transport-level error is a different animal from a tool that ran
        # and reported a problem; conflating them is exactly what this prints
        # its way out of.
        if "error" in reply:
            print(f"isError: (protocol error) {reply['error'].get('message')}")
            return 2

        result = reply.get("result", {})
        is_error = bool(result.get("isError"))
        if not args.json:
            print(f"isError: {is_error}\n")
        for block in result.get("content", []):
            if block.get("type") == "text":
                print(block["text"])
        return 1 if is_error else 0
    except ServerGone as exc:
        print(f"isError: (no reply) {exc}", file=sys.stderr)
        return 2
    finally:
        proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
