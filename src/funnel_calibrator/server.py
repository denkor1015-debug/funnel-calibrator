"""MCP server entrypoint.

Exposes the calibration toolset over stdio. Runs as a process separate from
the agent; see README for independent start instructions.

STATUS: scaffold. Tool implementations land 24 August 2026.
"""

from __future__ import annotations


def main() -> None:
    """Start the MCP server on stdio."""
    raise NotImplementedError(
        "Funnel Calibrator server is not implemented yet. "
        "See the build plan in README.md."
    )


if __name__ == "__main__":
    main()
