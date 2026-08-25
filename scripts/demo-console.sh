#!/usr/bin/env bash
# An MCP host connected to this server and nothing else.
#
# Two locks, both worth stating out loud during a demonstration:
#   --strict-mcp-config  ignores every other MCP server configured on the
#                        machine, so only the calibrator is reachable — and no
#                        unrelated credentials appear on screen.
#   --disallowedTools    removes file, shell and web access from the session.
#                        What is left is the five tools this repository defines.
#
# The point is not convenience. A host that could also read the source could be
# answering from the source; one that cannot must be calling the tools.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Запускаю MCP-хост:"
echo "  · підключений лише funnel-calibrator (--strict-mcp-config)"
echo "  · без доступу до файлів, шелу й мережі (--disallowedTools)"
echo

exec claude \
  --strict-mcp-config \
  --mcp-config agent/demo.mcp.json \
  --allowedTools "mcp__funnel-calibrator" \
  --disallowedTools "Read Write Edit Bash Glob Grep WebFetch WebSearch Task NotebookEdit"
