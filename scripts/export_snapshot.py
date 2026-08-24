#!/usr/bin/env python3
"""Export an anonymised snapshot of order cohorts from the business CRM.

Run offline, ahead of a demonstration. Strips all personally identifiable
information (names, phone numbers, addresses, waybill numbers) and retains
only the fields calibration requires. See data/README.md for the policy.

The CRM is reached through the same JSON-RPC worker that `keycrm_bridge.py`
talks to, with the shared secret taken from the environment — never from
source. Orders are collected page by page (`list_orders`, one page per call)
rather than in one sweep, because the worker runs on Cloudflare and a wide
window exceeds its subrequest budget.

Usage
-----
    export KEYCRM_MCP_SECRET=...          # or leave it in ~/.config/malvia/mcp.key
    uv run python scripts/export_snapshot.py --from 2026-06-01 --to 2026-08-24

    uv run python scripts/export_snapshot.py --probe
        One page, printed raw. Use it to check the CRM's field shapes before
        trusting the parser.

    uv run python scripts/export_snapshot.py --build-offer-map
        Rebuild data/offer_map.json (offer SKU → product code). Cached; the
        main export reuses it unless it is missing.

    uv run python scripts/export_snapshot.py --economics-only
        Rebuild data/economics.json from the local price/cost files. No
        network access at all.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"

# The business repository holding prices, costs and exchange rates. The
# snapshot is built from it once, offline; the server never reads it.
BUSINESS = Path(os.environ.get("FC_BUSINESS_REPO", Path.home() / "Malvia" / "Malvia Business"))

WORKER_URL = os.environ.get("KEYCRM_MCP_URL", "https://keycrm-mcp.malviainua.workers.dev/mcp")
SECRET_FILE = Path.home() / ".config" / "malvia" / "mcp.key"

# One page per request keeps each worker invocation to a single subrequest.
PAGE_LIMIT = 50
WINDOW_DAYS = 7

# KeyCRM answers 429 under sustained polling. A short pause between calls keeps
# the export inside the limit; the backoff below recovers when it does not.
THROTTLE_SECONDS = 0.5
MAX_RETRIES = 5

# Product codes as the business writes them: «Сукня софт 21-154» → 21-154,
# «Халат 2486» → 2486. Hyphenated forms are tried first because a bare
# four-digit code would also match the tail of a hyphenated one.
ARTICLE_HYPHEN = re.compile(r"\b(\d{1,2}-\d{2,4})\b")
ARTICLE_BARE = re.compile(r"\b(\d{3,4})\b")

MANUFACTURERS = ("KORA", "Minova", "Seven", "Lotran")

# Retained from each order. Everything else the CRM returns — buyer, phone,
# address, waybill, operator name — is dropped here and never written to disk.
KEEP_FIELDS = (
    "order_id",
    "sku",
    "created_at",
    "status_id",
    "amount",
    "manufacturer",
    "campaign",
    "creative",
    "sku_source",
)


def secret() -> str:
    """Shared worker secret, from the environment or the 600-mode key file."""
    from_env = os.environ.get("KEYCRM_MCP_SECRET", "").strip()
    if from_env:
        return from_env
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text(encoding="utf-8").strip()
    sys.exit(
        f"No worker secret. Set KEYCRM_MCP_SECRET, or place it in {SECRET_FILE} with mode 600."
    )


def call_worker(tool: str, arguments: dict[str, Any], key: str, req_id: int) -> Any:
    """One JSON-RPC tools/call against the worker.

    Throttled, and retried with exponential backoff when the CRM answers 429.
    Any other error is fatal: a partial export that looks complete is worse
    than one that stops and says why.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    request = urllib.request.Request(
        WORKER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-MCP-Key": key,
            # Matches keycrm_bridge.py: a bare client trips Cloudflare's WAF.
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        },
        method="POST",
    )

    for attempt in range(MAX_RETRIES):
        time.sleep(THROTTLE_SECONDS)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise SystemExit(f"Worker HTTP {exc.code} on {tool}: {detail}") from exc

        error = body.get("error")
        if error:
            # The worker relays the CRM's status inside the JSON-RPC error, so
            # rate limiting has to be recognised from the message text.
            if "429" in str(error.get("message", "")) and attempt < MAX_RETRIES - 1:
                pause = 5 * 2**attempt
                print(
                    f"  rate limited on {tool}; waiting {pause}s "
                    f"(attempt {attempt + 1}/{MAX_RETRIES})",
                    file=sys.stderr,
                )
                time.sleep(pause)
                continue
            raise SystemExit(f"Worker error on {tool}: {error}")

        content = body.get("result", {}).get("content", [])
        if not content:
            raise SystemExit(f"Worker returned no content for {tool}")
        return json.loads(content[0]["text"])

    raise SystemExit(f"Worker still rate limiting {tool} after {MAX_RETRIES} attempts")


def extract_article(text: str) -> str | None:
    """Product code from a free-text field, or None if it holds none."""
    if not text:
        return None
    match = ARTICLE_HYPHEN.search(text)
    if match:
        return match.group(1)
    match = ARTICLE_BARE.search(text)
    return match.group(1) if match else None


def build_offer_map(key: str, existing: dict[str, str], path: Path) -> dict[str, str]:
    """Map every offer SKU in the catalogue to its product code.

    An order line carries the *offer's* SKU — a bare serial like `1256` that
    identifies one colour and size — not the product code the business
    advertises and prices by (`2614`). The two look alike and neither is a
    prefix of the other, so guessing from the order alone silently attributes
    orders to the wrong product. This map removes the guess.

    Written after every product so a rate-limit stop loses nothing; a rerun
    skips whatever is already covered.
    """
    catalogue = call_worker("get_all_products", {}, key, 1)
    products = catalogue.get("products", [])
    print(f"  catalogue: {len(products)} products", file=sys.stderr)

    articles: list[str] = []
    for product in products:
        article = extract_article(nfc(product.get("name", "")))
        if article and article not in articles:
            articles.append(article)

    mapping = dict(existing)
    covered = set(mapping.values())
    todo = [a for a in articles if a not in covered]
    print(
        f"  {len(articles)} product codes, {len(todo)} still to fetch",
        file=sys.stderr,
    )

    for index, article in enumerate(todo, start=2):
        result = call_worker("get_product_offers", {"query": article}, key, index)
        for product in result.get("products", []):
            # A query for `21-18` also matches `21-183`; trust the matched
            # product's own name, not the string that found it.
            owner = extract_article(nfc(product.get("product_name", "")))
            if not owner:
                continue
            for offer in product.get("offers", []):
                sku = str(offer.get("sku") or "").strip()
                if sku:
                    mapping.setdefault(sku, owner)
        path.write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(
            f"  [{index - 1}/{len(todo)}] {article}: {len(mapping)} offer SKUs",
            file=sys.stderr,
        )
    return mapping


def resolve_sku(order: dict[str, Any], offer_map: dict[str, str]) -> tuple[str | None, str]:
    """Product code for an order, and how it was determined.

    Preference order matters. The offer map is authoritative — it says which
    product was actually sold, which is what price and cost attach to. The
    campaign name is a documented fallback: the business names campaigns
    `<code> | <subdomain> | …`, so it identifies the product *advertised*,
    which is the same thing except when a customer switched item on the call.
    """
    for token in str(order.get("products") or "").split(","):
        token = token.strip()
        if token in offer_map:
            return offer_map[token], "offer_map"

    from_campaign = extract_article(nfc(order.get("utm_campaign") or ""))
    if from_campaign:
        return from_campaign, "campaign"

    return None, "unresolved"


def extract_manufacturer(tags: str) -> str | None:
    lowered = (tags or "").lower()
    for name in MANUFACTURERS:
        if name.lower() in lowered:
            return name
    return None


def anonymise(order: dict[str, Any], offer_map: dict[str, str]) -> dict[str, Any] | None:
    """Whitelist the calibration fields. Orders without a code are dropped."""
    sku, source = resolve_sku(order, offer_map)
    if not sku:
        return None

    created = str(order.get("created_at", ""))[:10]
    if not created:
        return None

    try:
        amount = round(float(order.get("grand_total") or 0), 2)
    except (TypeError, ValueError):
        amount = 0.0

    campaign = order.get("utm_campaign") or ""
    creative = order.get("utm_content") or ""

    return {
        "order_id": order.get("id"),
        "sku": sku,
        "created_at": created,
        "status_id": int(order.get("status_id") or 0),
        "amount": amount,
        "manufacturer": extract_manufacturer(order.get("tags", "")),
        # The CRM writes an em dash where a UTM is absent; normalise to null so
        # "unattributed" is one value rather than two.
        "campaign": None if campaign in ("", "—") else campaign,
        "creative": None if creative in ("", "—") else creative,
        "sku_source": source,
    }


def windows(start: date, end: date, days: int) -> list[tuple[date, date]]:
    out = []
    cursor = start
    while cursor <= end:
        stop = min(cursor + timedelta(days=days - 1), end)
        out.append((cursor, stop))
        cursor = stop + timedelta(days=1)
    return out


def fetch_window(start: date, end: date, key: str, counter: list[int]) -> list[dict]:
    """Every order created in one window, collected a page at a time."""
    collected: list[dict] = []
    page = 1
    while True:
        counter[0] += 1
        result = call_worker(
            "list_orders",
            {
                "date_from": start.isoformat(),
                "date_to": end.isoformat(),
                "limit": PAGE_LIMIT,
                "page": page,
            },
            key,
            counter[0],
        )
        collected.extend(result.get("orders", []))
        last_page = result.get("last_page") or 1
        print(
            f"  {start} → {end}  page {page}/{last_page}  (+{result.get('returned', 0)})",
            file=sys.stderr,
        )
        if not result.get("has_next") or page >= last_page:
            break
        page += 1
    return collected


def nfc(text: str) -> str:
    """macOS stores Cyrillic decomposed; comparisons fail silently without this."""
    return unicodedata.normalize("NFC", text)


def build_economics() -> dict[str, Any]:
    """Per-product price and cost, from the business repo's canonical files.

    `econ.json` is generated by the business's own `econ.py` from product
    configs and dated cost history. Reading its output rather than recomputing
    it keeps one definition of price and cost in the system.
    """
    econ_path = BUSINESS / "tools" / "econ.json"
    if not econ_path.exists():
        raise SystemExit(
            f"No economics source at {econ_path}. Set FC_BUSINESS_REPO to the "
            "business repository, or run its tools/econ.py first."
        )
    econ = json.loads(econ_path.read_text(encoding="utf-8"))

    cost_dates: dict[str, str] = {}
    cogs_csv = BUSINESS / "finance" / "config" / "cogs_history.csv"
    if cogs_csv.exists():
        with cogs_csv.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                article = row["артикул"].strip()
                effective = row["від_дати"]
                if article not in cost_dates or effective >= cost_dates[article]:
                    cost_dates[article] = effective

    products = {}
    for item in econ.get("товари", []):
        article = item["артикул"]
        products[article] = {
            "sku": article,
            "name": nfc(item.get("назва", "")),
            "manufacturer": item.get("виробник"),
            "price_uah": item["ціна"],
            "cogs_uah": item["собівартість"],
            "usd_uah": item.get("курс"),
            "cost_effective_from": cost_dates.get(article),
            # False where the cost came from a stale landing-page config rather
            # than dated cost history, or where contribution is already ≤ 0.
            "economics_reliable": bool(item.get("економіка_надійна")),
            "source": item.get("собівартість_джерело"),
        }

    constants = econ.get("константи", {})
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "business repo tools/econ.json + finance/config/cogs_history.csv",
        "econ_computed_at": econ.get("порахано"),
        "assumed": {
            "approval_rate": constants.get("наскрізний_апрув", 0.65),
            "buyout_rate": constants.get("викуп", 0.525),
            "return_fee_uah": constants.get("повернення_нп", 94),
            "call_centre_fee_uah": constants.get("кц_за_замовлення", 23),
            "upsell_uah": constants.get("апсейл_на_викуп", 95),
            "goal_ratio": constants.get("goal_від_stop", 0.70),
            "daily_budget_usd": constants.get("бюджет_usd_день", 25),
        },
        "products": products,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="date_from", default="2026-06-01")
    parser.add_argument("--to", dest="date_to", default=date.today().isoformat())
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Fetch one page and print it raw, to verify field shapes.",
    )
    parser.add_argument(
        "--build-offer-map",
        action="store_true",
        help="Rebuild data/offer_map.json (offer SKU → product code) and stop.",
    )
    parser.add_argument(
        "--economics-only",
        action="store_true",
        help="Rebuild data/economics.json only. No network access.",
    )
    args = parser.parse_args()

    DATA.mkdir(exist_ok=True)

    if args.economics_only:
        economics = build_economics()
        (DATA / "economics.json").write_text(
            json.dumps(economics, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"economics.json — {len(economics['products'])} products")
        return

    key = secret()

    if args.probe:
        result = call_worker(
            "list_orders",
            {
                "date_from": args.date_from,
                "date_to": args.date_from,
                "limit": 5,
                "page": 1,
            },
            key,
            1,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2)[:4000])
        return

    offer_map_path = DATA / "offer_map.json"
    existing = (
        json.loads(offer_map_path.read_text(encoding="utf-8")) if offer_map_path.exists() else {}
    )
    if args.build_offer_map or not existing:
        print("Building offer map…", file=sys.stderr)
        offer_map = build_offer_map(key, existing, offer_map_path)
        print(f"offer_map.json — {len(offer_map)} offer SKUs")
        if args.build_offer_map:
            return
    else:
        offer_map = existing

    start = date.fromisoformat(args.date_from)
    end = date.fromisoformat(args.date_to)
    if start > end:
        raise SystemExit(f"--from {start} is after --to {end}")

    counter = [0]
    raw: list[dict] = []
    for window_start, window_end in windows(start, end, WINDOW_DAYS):
        raw.extend(fetch_window(window_start, window_end, key, counter))

    # The CRM can return the same order in two windows when a boundary falls
    # mid-day; de-duplicate on id before anything counts it twice.
    seen: set[Any] = set()
    orders: list[dict] = []
    dropped_no_sku = 0
    for row in raw:
        if row.get("id") in seen:
            continue
        seen.add(row.get("id"))
        clean = anonymise(row, offer_map)
        if clean is None:
            dropped_no_sku += 1
            continue
        orders.append(clean)

    orders.sort(key=lambda o: (o["created_at"], o["order_id"] or 0))

    snapshot = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "KeyCRM via MCP worker (list_orders)",
        "window": {"from": start.isoformat(), "to": end.isoformat()},
        "anonymisation": (
            "Order-level rows only. Buyer names, phone numbers, addresses, "
            "waybill numbers and operator names are never requested into this "
            "file; see data/README.md."
        ),
        "fields": list(KEEP_FIELDS),
        "counts": {
            "orders": len(orders),
            "fetched": len(raw),
            "dropped_without_product_code": dropped_no_sku,
            "distinct_skus": len({o["sku"] for o in orders}),
            "sku_from_offer_map": sum(1 for o in orders if o["sku_source"] == "offer_map"),
            "sku_from_campaign": sum(1 for o in orders if o["sku_source"] == "campaign"),
        },
        "orders": orders,
    }
    (DATA / "snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    economics = build_economics()
    (DATA / "economics.json").write_text(
        json.dumps(economics, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        f"snapshot.json — {len(orders)} orders, "
        f"{snapshot['counts']['distinct_skus']} products, "
        f"{args.date_from} → {args.date_to} ({counter[0]} worker calls)"
    )
    print(f"economics.json — {len(economics['products'])} products")


if __name__ == "__main__":
    main()
