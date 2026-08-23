# Snapshot dataset

The server's primary data source: an anonymised, point-in-time export of order cohorts from the business CRM, produced by [`scripts/export_snapshot.py`](../scripts/export_snapshot.py).

No network access and no authentication are required at runtime. The snapshot is the deterministic demonstration input — the same file produces the same results on any machine, offline.

## Anonymisation policy

Stripped at export, never written to disk:

- customer names, phone numbers, email addresses
- delivery addresses and post-office branch identifiers
- waybill (TTN) numbers and any CRM record identifiers that link back to a person

Retained, because calibration requires it:

- product code, manufacturer tag, price band
- order status and status-change timestamps
- order and upsell amounts
- unit-economics inputs (cost of goods, fees) per product

Aggregate commercial figures — costs, margins, buyout rates — are retained deliberately: the calibration is meaningless without them, and the defence requires tracing a value from source to output. They describe products, not people.

## Files

| File | Contents |
|---|---|
| `snapshot.json` | Anonymised cohort export *(added at build)* |
| `economics.json` | Per-product price and cost inputs *(added at build)* |

`data/raw/` is git-ignored and holds unprocessed exports. **Never commit its contents.**
