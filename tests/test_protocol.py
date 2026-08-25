"""The tools, exercised over real MCP rather than as Python functions.

Every other test in this suite imports `server` and calls a function. That is
fast and it is where the arithmetic lives, but it skips the protocol entirely —
and the protocol is where this project's worst bug hid. A `NotRequired` key in
an output contract once left all of these tests green while every call over the
wire came back an error, because the MCP SDK marks every published property
required and the server's own responses then failed their own schema.

So this module speaks JSON-RPC to a spawned server the way any host does. It is
slower than the rest of the suite, and deliberately narrow: it checks that a
call succeeds, that a bad argument is classed as an error by the protocol and
not merely described as one in text, and that the published output schemas are
not the vacuous `additionalProperties: true` the SDK emits for a bare dict.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_VERSION = "2024-11-05"

# Field counts are pinned in tests/test_contracts.py against the TypedDicts;
# here we only assert the schema survived publication with its shape intact.
EXPECTED_TOOLS = {
    "measure_sku_funnel": 20,
    "recalibrate_cpl_bounds": 16,
    "recommend_next_action": 9,
    "audit_ad_verdict": 7,
    "list_covered_skus": 5,
}


class _Client:
    """The smallest MCP client that can hold a conversation."""

    def __init__(self) -> None:
        self._proc = subprocess.Popen(
            ["uv", "run", "funnel-calibrator"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._next_id = 0
        self.server_info = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1"},
        })["result"]["serverInfo"]
        self._notify("notifications/initialized")

    def _write(self, payload: dict) -> None:
        assert self._proc.stdin
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()

    def _notify(self, method: str) -> None:
        self._write({"jsonrpc": "2.0", "method": method})

    def _request(self, method: str, params: dict) -> dict:
        assert self._proc.stdout
        self._next_id += 1
        self._write({"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params})
        while True:
            line = self._proc.stdout.readline()
            if not line:
                raise AssertionError(f"server closed stdout during {method}")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue  # a log line, not an answer
            if message.get("id") == self._next_id:
                return message

    def list_tools(self) -> list[dict]:
        return self._request("tools/list", {})["result"]["tools"]

    def call(self, name: str, **arguments: object) -> dict:
        reply = self._request("tools/call", {"name": name, "arguments": arguments})
        assert "error" not in reply, f"transport-level failure: {reply['error']}"
        return reply["result"]

    def close(self) -> None:
        self._proc.terminate()
        self._proc.wait(timeout=10)


@pytest.fixture(scope="module")
def client():
    c = _Client()
    yield c
    c.close()


def test_server_starts_and_introduces_itself(client) -> None:
    assert client.server_info["name"] == "funnel-calibrator"


def test_every_tool_publishes_a_real_output_schema(client) -> None:
    """`-> dict[str, Any]` would publish `additionalProperties: true` and nothing else."""
    published = {t["name"]: t for t in client.list_tools()}
    assert set(published) == set(EXPECTED_TOOLS)
    for name, fields in EXPECTED_TOOLS.items():
        schema = published[name].get("outputSchema") or {}
        assert len(schema.get("properties", {})) == fields, (
            f"{name} publishes {len(schema.get('properties', {}))} output fields, expected {fields}"
        )


@pytest.mark.parametrize("name,arguments", [
    ("measure_sku_funnel", {"sku": "21-154"}),
    ("recalibrate_cpl_bounds", {"sku": "21-154"}),
    ("recommend_next_action", {"sku": "21-154", "current_cpl": 1.63}),
    ("audit_ad_verdict", {"sku": "21-154", "proposed_action": "scale", "current_cpl": 1.63}),
    ("list_covered_skus", {"min_orders": 50}),
])
def test_a_good_call_succeeds_over_the_wire(client, name: str, arguments: dict) -> None:
    """The regression guard. This is what `NotRequired` broke while the rest stayed green."""
    result = client.call(name, **arguments)
    assert not result.get("isError"), result.get("content")
    payload = json.loads(result["content"][0]["text"])
    assert len(payload) == EXPECTED_TOOLS[name], (
        f"{name} returned {sorted(payload)}, which does not match its published schema"
    )


def test_an_unknown_product_is_an_error_at_the_protocol_level(client) -> None:
    """Not merely a sentence saying so — a caller must be able to branch on it."""
    result = client.call("measure_sku_funnel", sku="21-999")
    assert result.get("isError") is True
    assert "21-999" in result["content"][0]["text"]


def test_a_window_with_no_orders_is_a_success(client) -> None:
    """Empty is a finding, and must not arrive dressed as a failure."""
    result = client.call(
        "measure_sku_funnel", sku="21-253", window_from="2026-06-01", window_to="2026-06-02"
    )
    assert not result.get("isError")
    payload = json.loads(result["content"][0]["text"])
    assert payload["resolved_orders"] == 0
    assert payload["buyout_rate"] is None
    assert payload["reliability"] == "insufficient"
