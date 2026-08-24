#!/usr/bin/env python3
"""Print the Obsidian MCP server's tool contracts, exactly as it exposes them.

Documenting an external server's schema by transcription invites drift: the
doc says one thing, the server does another, and the difference only shows up
under questioning. This connects to the running plugin and prints what it
actually advertises, so `docs/tool-contracts.md` can be checked against it at
any time.

Run:
    uv run python scripts/capture_obsidian_contract.py            # all tools
    uv run python scripts/capture_obsidian_contract.py vault_read # one tool
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

REPO = Path(__file__).resolve().parent.parent
load_dotenv(REPO / ".env")


async def main(wanted: set[str]) -> int:
    token = os.environ.get("OBSIDIAN_API_KEY", "").strip()
    if not token:
        print(
            "OBSIDIAN_API_KEY is not set. See demo-vault/README.md.",
            file=sys.stderr,
        )
        return 2

    host = os.environ.get("OBSIDIAN_HOST", "127.0.0.1")
    port = os.environ.get("OBSIDIAN_PORT", "27124")
    scheme = "https" if port == "27124" else "http"
    url = f"{scheme}://{host}:{port}/mcp/"

    # The plugin generates a self-signed certificate for 127.0.0.1, so
    # verification is switched off for this loopback connection only.
    async with (
        streamablehttp_client(
            url,
            headers={"Authorization": f"Bearer {token}"},
            httpx_client_factory=lambda **kw: httpx.AsyncClient(**{**kw, "verify": False}),
        ) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        init = await session.initialize()
        print(f"# {init.server_info.name} {init.server_info.version}")
        print(f"# endpoint: {url}\n")
        tools = await session.list_tools()
        for tool in tools.tools:
            if wanted and tool.name not in wanted:
                continue
            print(f"## {tool.name}")
            print(f"\n**Model-facing description:** {tool.description}\n")
            print("**Input schema:**\n")
            print("```json")
            print(json.dumps(tool.input_schema, indent=2, ensure_ascii=False))
            print("```\n")
            if getattr(tool, "output_schema", None):
                print("**Output schema:**\n")
                print("```json")
                print(json.dumps(tool.output_schema, indent=2, ensure_ascii=False))
                print("```\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(set(sys.argv[1:]))))
