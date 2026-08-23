"""Export an anonymised snapshot of order cohorts from the business CRM.

Run offline, ahead of a demonstration. Strips all personally identifiable
information (names, phone numbers, addresses, waybill numbers) and retains
only the fields calibration requires. See data/README.md for the policy.

STATUS: scaffold. Implementation lands 24 August 2026.
"""

from __future__ import annotations
