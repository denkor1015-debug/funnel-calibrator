"""Snapshot dataset loading and cohort selection.

The snapshot is an anonymised, point-in-time export of order cohorts. It is
the server's primary data source and requires no network access at runtime.

Cohort maturity is enforced here rather than in the tools, so that every
measurement in the system shares one definition of "resolved".
"""

from __future__ import annotations
