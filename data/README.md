# Snapshot dataset

The server's primary data source: an anonymised, point-in-time export of order cohorts from the business CRM, produced by [`scripts/export_snapshot.py`](../scripts/export_snapshot.py).

No network access and no authentication are required at runtime. The snapshot is the deterministic demonstration input — the same file produces the same results on any machine, offline. The export step needs CRM credentials; **running the server does not**, and the two are deliberately separate programs.

## Anonymisation policy

Stripped at export, never written to disk:

- customer names, phone numbers, email addresses
- delivery addresses and post-office branch identifiers
- waybill (TTN) numbers and any CRM record identifiers that link back to a person
- call-centre operator names — employees are people too, and nothing here needs them

Retained, because calibration requires it:

- product code, manufacturer tag, price band
- order status and creation date
- order amount
- campaign and creative identifiers (ad-account labels, not people)
- unit-economics inputs (cost of goods, fees) per product

The filter is a whitelist, not a blacklist: `anonymise()` constructs a new record from named fields, so a field the CRM adds later cannot leak by default.

Aggregate commercial figures — costs, margins, buyout rates — are retained deliberately: the calibration is meaningless without them, and the defence requires tracing a value from source to output. They describe products, not people.

## Files

| File | Contents |
|---|---|
| `snapshot.json` | 4 132 anonymised orders, 1 June – 24 August 2026, 51 products |
| `economics.json` | Price and cost per product (53), plus the portfolio constants |
| `offer_map.json` | 1 920 offer SKUs → product code. See below |

`data/raw/` is git-ignored and holds unprocessed exports. **Never commit its contents.**

### Why `offer_map.json` exists

An order line carries the *offer's* SKU — a bare serial like `1256` identifying one colour and size — not the product code the business advertises and prices by, like `2614`. Both are plain numbers and neither contains the other, so a code parsed straight out of the order string attributes orders to the wrong product **silently**: the resulting rates still look plausible.

The map is built once from the catalogue and is authoritative. Each order records which route produced its code:

| `sku_source` | Orders | Meaning |
|---|---:|---|
| `offer_map` | 3 943 | The product actually sold, from the catalogue map |
| `campaign` | 189 | Documented fallback: the business names campaigns `<code> \| <subdomain> \| …`, so this is the product *advertised* |

Fifteen orders carried neither and were dropped; the count is recorded in `snapshot.json` under `counts.dropped_without_product_code`.

## Regenerating

```bash
# offline, no credentials — rebuilds economics.json from the business repo
uv run python scripts/export_snapshot.py --economics-only

# full export; needs KEYCRM_MCP_SECRET, throttled and resumable
uv run python scripts/export_snapshot.py --from 2026-06-01 --to 2026-08-24
```

The exporter throttles to one request every 0.5 s and backs off exponentially on HTTP 429, per the assignment's rate-limit requirement. The offer map is checkpointed after every product, so an interrupted run resumes instead of restarting.
