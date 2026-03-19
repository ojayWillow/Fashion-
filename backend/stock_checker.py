"""Stock checker — periodically verify product availability and live prices.

Supports multiple store platforms via a dispatcher pattern.
Each store has its own check function but returns a standardized result.

Safety: products are NOT marked offline on first failure.
Requires 3 consecutive failures before marking unavailable.

Price tracking: live price is scraped on every check. If it differs from
the stored sale_price, the DB is updated and a row is written to price_history.

Naked Copenhagen NOTE: nakedcph.com blocks the Shopify .js endpoint.
Stock is checked via HTML scraping (fetchers/naked.py). Prices are stored
in DKK→EUR converted form and must NOT be overwritten from the .js endpoint.

Run directly: python stock_checker.py
Or import run_stock_check() — auto-scheduled via APScheduler in app.py.
"""
import csv
import time
import logging
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from database import get_db
from utils.http_retry import request_with_retry

logger = logging.getLogger("stock_checker")

# Module-level state for status reporting
last_run = None
last_result = None

# How many consecutive failures before we mark a product unavailable
MAX_FAIL_COUNT = 3

# Delay between products to avoid hammering stores
CHECK_DELAY = 1.0

REMOVAL_LOG = Path(__file__).resolve().parent.parent / "data" / "removed_products.csv"

# Domains that block the standard Shopify .js endpoint.
# These stores are checked via HTML scraping — their prices must NOT be
# overwritten from the .js endpoint (which may be blocked or return wrong currency).
SHOPIFY_HTML_ONLY_DOMAINS = {
    "nakedcph.com",
    "www.nakedcph.com",
}

# Solebox domains — use dedicated SoleboxScraper, not Shopify .js
SOLEBOX_DOMAINS = {
    "www.solebox.com",
    "solebox.com",
}


# ── Removal audit log ────────────────────────────────────────────

def _log_removal(slug: str, product_url: str, reason: str, fail_count: int, last_known_price: float):
    """Append a row to the removal audit CSV."""
    write_header = not REMOVAL_LOG.exists()
    REMOVAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(REMOVAL_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["timestamp", "slug", "product_url", "store_domain", "reason", "fail_count", "last_known_price"])
        domain = urlparse(product_url).netloc
        writer.writerow([
            datetime.now(timezone.utc).isoformat(),
            slug,
            product_url,
            domain,
            reason,
            fail_count,
            last_known_price,
        ])


def read_removal_log() -> list[dict]:
    """Read the removal audit CSV and return as list of dicts."""
    if not REMOVAL_LOG.exists():
        return []
    with open(REMOVAL_LOG, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


# ── Standardized result format ────────────────────────────────────
#
#   {
#       "success": True/False,          — did the check itself work?
#       "online": True/False/None,      — is the product page still live? (None = unknown)
#       "any_in_stock": True/False,     — is anything available?
#       "sizes_available": int,         — how many sizes in stock
#       "sizes": [...],                 — per-size details (optional)
#       "live_price": float or None,    — current sale price from the store (None = don't update)
#       "live_original": float or None, — current compare-at / original price
#       "error": str or None,           — error message if success=False
#   }


# ── Naked Copenhagen stock check (HTML scraping) ─────────────────

def check_naked_stock(product_url: str) -> dict:
    """Check stock for Naked Copenhagen via HTML scraping.

    nakedcph.com blocks the Shopify .js endpoint, so we scrape the HTML page.
    Prices are intentionally NOT returned here — they are stored in EUR
    (converted from DKK at fetch time) and must not be overwritten by this check.
    """
    try:
        from fetchers.naked import check_product_still_online
        result = check_product_still_online(product_url)
        return {
            "success": True,
            "online": result.get("online", True),
            "any_in_stock": result.get("in_stock", False),
            "sizes_available": result.get("sizes_available", 0),
            "sizes": [],          # naked checker doesn't return per-size variant IDs
            "live_price": None,   # never overwrite — price stored in EUR already
            "live_original": None,
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "online": None,
            "any_in_stock": None,
            "sizes_available": 0,
            "sizes": [],
            "live_price": None,
            "live_original": None,
            "error": str(e),
        }


# ── Shopify stock check (SNS, AFEW etc.) ────────────────────────

def check_shopify_stock(product_url: str, handle: str) -> dict:
    """Check stock and live price for a Shopify product via .js endpoint.

    The Shopify .js endpoint returns price / compare_at_price in cents.
    Uses shared retry logic to handle rate limits and transient errors.
    Only called for stores that support the .js endpoint (not Naked CPH).
    """
    base = product_url.split("/products/")[0]
    js_url = f"{base}/products/{handle}.js"

    try:
        resp = request_with_retry(js_url, max_retries=2, timeout=8)

        if resp.status_code == 404:
            return {
                "success": True,
                "online": False,
                "any_in_stock": False,
                "sizes_available": 0,
                "sizes": [],
                "live_price": None,
                "live_original": None,
                "error": None,
            }

        resp.raise_for_status()
        data = resp.json()

        sizes = []
        for v in data.get("variants", []):
            sizes.append({
                "label": v.get("option1", v.get("title")),
                "in_stock": v.get("available", False),
                "variant_id": str(v["id"]),
            })

        # Shopify returns prices in cents — convert to euros
        price_cents = data.get("price")
        compare_cents = data.get("compare_at_price")
        live_price = round(price_cents / 100, 2) if price_cents else None
        live_original = round(compare_cents / 100, 2) if compare_cents else None

        return {
            "success": True,
            "online": True,
            "any_in_stock": any(s["in_stock"] for s in sizes),
            "sizes_available": sum(1 for s in sizes if s["in_stock"]),
            "sizes": sizes,
            "live_price": live_price,
            "live_original": live_original,
            "error": None,
        }

    except Exception as e:
        return {
            "success": False,
            "online": None,
            "any_in_stock": None,
            "sizes_available": 0,
            "sizes": [],
            "live_price": None,
            "live_original": None,
            "error": str(e),
        }


# ── Solebox stock check (ngsw HTML cache scraping) ───────────────

def check_solebox_stock(product_url: str) -> dict:
    """Check stock for Solebox via the dedicated SoleboxScraper.

    Solebox uses the Scayle/NGSW platform — not Shopify.
    The scraper extracts per-size stock from the ngsw HTML cache.
    """
    try:
        from scraper_solebox import SoleboxScraper

        # Extract the slug from the URL: /en-eu/p/{slug} or /en-eu/p/{slug}/{variantId}
        path = urlparse(product_url).path.rstrip("/")
        parts = path.split("/p/")
        if len(parts) < 2:
            raise ValueError(f"Cannot extract Solebox slug from URL: {product_url}")
        # Take only the slug part (first segment after /p/), drop any trailing variant ID
        slug = parts[1].split("/")[0]

        scraper = SoleboxScraper()
        data = scraper.get_product(slug)

        if not data:
            return {
                "success": True,
                "online": False,
                "any_in_stock": False,
                "sizes_available": 0,
                "sizes": [],
                "live_price": None,
                "live_original": None,
                "error": None,
            }

        sizes = []
        for s in data.get("sizes", []):
            sizes.append({
                "label": s.get("eu") or s.get("us") or s.get("referenceKey"),
                "in_stock": s.get("inStock", False),
                "variant_id": s.get("referenceKey"),
            })

        any_in_stock = not data.get("isSoldOut", True)
        sizes_available = sum(1 for s in sizes if s["in_stock"])

        # Use first in-stock size price as the live price
        live_price = None
        for s in data.get("sizes", []):
            if s.get("inStock") and s.get("price_eur"):
                live_price = float(s["price_eur"])
                break

        return {
            "success": True,
            "online": True,
            "any_in_stock": any_in_stock,
            "sizes_available": sizes_available,
            "sizes": sizes,
            "live_price": live_price,
            "live_original": None,
            "error": None,
        }

    except Exception as e:
        return {
            "success": False,
            "online": None,
            "any_in_stock": None,
            "sizes_available": 0,
            "sizes": [],
            "live_price": None,
            "live_original": None,
            "error": str(e),
        }


# ── END Clothing stock check (Algolia) ───────────────────────────

def check_end_stock(product_url: str, sku: str | None) -> dict:
    """Check stock and live price for an END Clothing product via Algolia.

    Re-queries the same Algolia proxy used during initial fetch.
    Returns per-size stock status and current price.
    """
    if not sku:
        import re
        from urllib.parse import urlparse as _urlparse
        slug = _urlparse(product_url).path.rstrip("/").split("/")[-1].replace(".html", "")
        m = re.search(r"([a-zA-Z]{1,5}\d{3,5}-\d{2,4})$", slug)
        if m:
            sku = m.group(1).upper()

    if not sku:
        return {
            "success": False,
            "online": None,
            "any_in_stock": None,
            "sizes_available": 0,
            "sizes": [],
            "live_price": None,
            "live_original": None,
            "error": "No SKU available for Algolia lookup",
        }

    try:
        from curl_cffi import requests as cffi_requests

        ALGOLIA_URL = (
            "https://search1web.endclothing.com"
            "/1/indexes/Catalog_products_v3_gb_products/query"
        )
        ALGOLIA_HEADERS = {
            "X-Algolia-Application-Id": "KO4W2GBINK",
            "X-Algolia-API-Key": "f0cc49399fc8922337e40fb5fc3ab2a4",
            "Content-Type": "application/json",
            "Origin": "https://www.endclothing.com",
            "Referer": "https://www.endclothing.com/",
        }

        resp = cffi_requests.post(
            ALGOLIA_URL,
            headers=ALGOLIA_HEADERS,
            json={"query": sku, "hitsPerPage": 5},
            impersonate="chrome",
            timeout=10,
        )

        if resp.status_code != 200:
            return {
                "success": False,
                "online": None,
                "any_in_stock": None,
                "sizes_available": 0,
                "sizes": [],
                "live_price": None,
                "live_original": None,
                "error": f"Algolia HTTP {resp.status_code}",
            }

        hits = resp.json().get("hits", [])

        hit = None
        for h in hits:
            if h.get("sku", "").upper() == sku.upper():
                hit = h
                break
        if not hit and hits:
            hit = hits[0]

        if not hit:
            return {
                "success": True,
                "online": False,
                "any_in_stock": False,
                "sizes_available": 0,
                "sizes": [],
                "live_price": None,
                "live_original": None,
                "error": None,
            }

        labels = hit.get("footwear_size_label") or hit.get("size") or []
        sku_stock = hit.get("sku_stock", {})
        stock_entries = sorted(sku_stock.items(), key=lambda x: x[0])
        all_stocks = [v for _, v in stock_entries]

        sizes = []
        if all_stocks and len(all_stocks) >= len(labels):
            best_offset = 0
            for offset in range(len(all_stocks) - len(labels) + 1):
                chunk = all_stocks[offset: offset + len(labels)]
                if any(x > 0 for x in chunk):
                    best_offset = offset
                    break
            for i, label in enumerate(labels):
                idx = best_offset + i
                qty = all_stocks[idx] if idx < len(all_stocks) else 0
                sizes.append({
                    "label": label,
                    "in_stock": qty > 0,
                    "variant_id": None,
                })
        else:
            for label in labels:
                sizes.append({"label": label, "in_stock": True, "variant_id": None})

        total_stock = hit.get("stock", 0)
        any_available = total_stock > 0 if total_stock is not None else any(s["in_stock"] for s in sizes)

        live_price = hit.get("sale_price") or hit.get("price")
        live_original = hit.get("original_price") or hit.get("compare_at_price")

        return {
            "success": True,
            "online": True,
            "any_in_stock": any_available,
            "sizes_available": sum(1 for s in sizes if s["in_stock"]),
            "sizes": sizes,
            "live_price": float(live_price) if live_price else None,
            "live_original": float(live_original) if live_original else None,
            "error": None,
        }

    except Exception as e:
        return {
            "success": False,
            "online": None,
            "any_in_stock": None,
            "sizes_available": 0,
            "sizes": [],
            "live_price": None,
            "live_original": None,
            "error": str(e),
        }


# ── Dispatcher ───────────────────────────────────────────────────

def check_product_stock(platform: str, product_url: str, slug: str, sku: str | None) -> dict:
    """Route stock check to the correct store-specific function."""
    domain = urlparse(product_url).netloc

    # Solebox uses its own scraper regardless of stored platform value
    if domain in SOLEBOX_DOMAINS:
        return check_solebox_stock(product_url)

    if platform == "shopify":
        # Naked CPH blocks .js — use HTML scraper, never overwrite price
        if domain in SHOPIFY_HTML_ONLY_DOMAINS:
            return check_naked_stock(product_url)
        handle = product_url.rstrip("/").split("/products/")[-1].split("?")[0]
        return check_shopify_stock(product_url, handle)

    elif platform == "custom":
        if "endclothing.com" in product_url:
            return check_end_stock(product_url, sku)

    return {
        "success": False,
        "online": None,
        "any_in_stock": None,
        "sizes_available": 0,
        "sizes": [],
        "live_price": None,
        "live_original": None,
        "error": f"No stock checker for platform: {platform}",
    }


# ── Worker: check all products for one domain ────────────────────

def _check_domain_batch(products_for_domain: list[dict]) -> list[tuple[dict, dict]]:
    """Check products for a single domain sequentially.
    Returns (product, result) tuples.
    Skips remaining products if domain is detected as down.
    """
    results = []
    domain_dead = False

    for p in products_for_domain:
        if domain_dead:
            results.append((p, {
                "success": False, "online": None, "any_in_stock": None,
                "sizes_available": 0, "sizes": [],
                "live_price": None, "live_original": None,
                "error": "SKIPPED — domain unreachable this run",
                "_skipped": True,
            }))
            continue

        result = check_product_stock(p["platform"], p["product_url"], p["slug"], p["sku"])
        result["_skipped"] = False

        if not result["success"] and result.get("error"):
            err = result["error"]
            if "NameResolution" in err or "timed out" in err or "ConnectTimeout" in err:
                domain_dead = True
                logger.warning(f"  Domain down: {urlparse(p['product_url']).netloc} — skipping remaining products")

        results.append((p, result))
        time.sleep(CHECK_DELAY)

    return results


# ── Price change helper ──────────────────────────────────────────

def _apply_price_update(
    conn,
    product_id: int,
    slug: str,
    old_sale: float,
    old_original: float,
    live_price: float,
    live_original: float | None,
    now: str,
):
    """Update sale_price / original_price / discount_pct if the live price differs.

    Logs a row to price_history on every change.
    """
    new_sale = round(live_price, 2)
    new_original = round(live_original, 2) if live_original else round(old_original, 2)

    if round(old_sale, 2) == new_sale:
        return  # No change, nothing to do

    old_discount = round((1 - round(old_sale, 2) / round(old_original, 2)) * 100) if old_original else 0
    new_discount = round((1 - new_sale / new_original) * 100) if new_original > new_sale else 0

    conn.execute(
        """UPDATE products
        SET sale_price = ?, original_price = ?, discount_pct = ?, updated_at = ?
        WHERE id = ?""",
        (new_sale, new_original, new_discount, now, product_id),
    )
    conn.execute(
        """INSERT INTO price_history
        (product_id, old_price, new_price, old_discount, new_discount, changed_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (product_id, round(old_sale, 2), new_sale, old_discount, new_discount, now),
    )
    logger.info(
        f"  {slug}: price updated €{old_sale:.2f} → €{new_sale:.2f} "
        f"(discount {old_discount}% → {new_discount}%)"
    )


# ── Main stock check loop ────────────────────────────────────────

def run_stock_check():
    """Check all active products, update stock status, and sync live prices.

    Safety rules:
    - Only checks products with status != 'removed' (prevents infinite removal loop)
    - Failed checks (network errors, timeouts) do NOT change product status or price
    - Network errors do NOT increment fail_count (prevents false removals)
    - Products need 3 consecutive "confirmed gone" results before removal
    - Only confident "online=False" results increment fail_count
    - Successful checks reset the fail counter
    - Domains that fail with DNS/timeout are skipped for remaining products

    Price tracking:
    - live_price from each check is compared to stored sale_price
    - Any change updates sale_price, recalculates discount_pct, and writes to price_history
    - Naked CPH prices are never touched (live_price=None returned by checker)
    """
    global last_run, last_result

    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # Only check active products — skip anything already confirmed removed
    products = conn.execute(
        """SELECT p.id, p.slug, p.product_url, p.sku, p.in_stock,
                  p.fail_count, p.sale_price, p.original_price, s.platform
        FROM products p
        JOIN stores s ON p.store_id = s.id
        WHERE p.status != 'removed'"""
    ).fetchall()

    products = [dict(p) for p in products]

    total = len(products)
    checked = 0
    updated = 0
    failed = 0
    skipped = 0
    marked_offline = 0
    price_updates = 0

    logger.info(f"Stock check started — {total} active products")

    # Group products by store domain
    domain_groups: dict[str, list[dict]] = {}
    for p in products:
        domain = urlparse(p["product_url"]).netloc
        domain_groups.setdefault(domain, []).append(p)

    # Run domains concurrently, products within each domain sequentially
    all_results: list[tuple[dict, dict]] = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_check_domain_batch, group): domain
            for domain, group in domain_groups.items()
        }
        for future in as_completed(futures):
            domain = futures[future]
            try:
                all_results.extend(future.result())
            except Exception as e:
                logger.error(f"  Domain batch failed for {domain}: {e}")

    for p, result in all_results:
        product_id = p["id"]
        current_fail_count = p["fail_count"] or 0

        if result.get("_skipped"):
            skipped += 1
            logger.info(f"  {p['slug']}: SKIPPED (domain down)")
            continue

        checked += 1

        if result["success"]:
            if result["online"] is False:
                new_fail_count = current_fail_count + 1

                if new_fail_count >= MAX_FAIL_COUNT:
                    conn.execute(
                        """UPDATE products
                        SET in_stock = 0, status = 'removed',
                            fail_count = ?, last_checked = ?, updated_at = ?
                        WHERE id = ?""",
                        (new_fail_count, now, now, product_id),
                    )
                    marked_offline += 1
                    _log_removal(
                        slug=p["slug"],
                        product_url=p["product_url"],
                        reason="Product page returned 404 / not found",
                        fail_count=new_fail_count,
                        last_known_price=p.get("sale_price", 0),
                    )
                    logger.warning(f"  {p['slug']}: REMOVED (confirmed after {new_fail_count} checks)")
                else:
                    conn.execute(
                        """UPDATE products
                        SET fail_count = ?, last_checked = ?, updated_at = ?
                        WHERE id = ?""",
                        (new_fail_count, now, now, product_id),
                    )
                    logger.info(f"  {p['slug']}: not found ({new_fail_count}/{MAX_FAIL_COUNT} strikes)")
            else:
                in_stock = 1 if result["any_in_stock"] else 0
                conn.execute(
                    """UPDATE products
                    SET in_stock = ?, status = 'active',
                        fail_count = 0, last_checked = ?, updated_at = ?
                    WHERE id = ?""",
                    (in_stock, now, now, product_id),
                )

                for size in result.get("sizes", []):
                    in_stock_val = 1 if size["in_stock"] else 0
                    if size.get("variant_id"):
                        conn.execute(
                            """UPDATE product_sizes
                            SET in_stock = ?, last_checked = ?
                            WHERE product_id = ? AND variant_id = ?""",
                            (in_stock_val, now, product_id, size["variant_id"]),
                        )
                    else:
                        conn.execute(
                            """UPDATE product_sizes
                            SET in_stock = ?, last_checked = ?
                            WHERE product_id = ? AND size_label = ?""",
                            (in_stock_val, now, product_id, size["label"]),
                        )

                # Live price sync — only if checker returned a price (Naked CPH returns None)
                live_price = result.get("live_price")
                live_original = result.get("live_original")
                if live_price and live_price > 0:
                    _apply_price_update(
                        conn=conn,
                        product_id=product_id,
                        slug=p["slug"],
                        old_sale=p["sale_price"],
                        old_original=p["original_price"],
                        live_price=live_price,
                        live_original=live_original,
                        now=now,
                    )
                    if round(live_price, 2) != round(p["sale_price"], 2):
                        price_updates += 1

                status = "in stock" if result["any_in_stock"] else "SOLD OUT"
                logger.info(f"  {p['slug']}: {status} ({result['sizes_available']} sizes)")
                updated += 1

        else:
            conn.execute(
                "UPDATE products SET last_checked = ? WHERE id = ?",
                (now, product_id),
            )
            failed += 1
            logger.error(f"  {p['slug']}: CHECK FAILED (network) — {result['error']}")

        conn.execute(
            """INSERT INTO stock_checks
            (product_id, was_in_stock, sizes_available, raw_response)
            VALUES (?, ?, ?, ?)""",
            (
                product_id,
                1 if result.get("any_in_stock") else 0,
                result.get("sizes_available", 0),
                result.get("error") or ("OK" if result["success"] else "FAILED"),
            ),
        )

    conn.commit()
    conn.close()

    last_run = now
    last_result = {
        "total": total,
        "checked": checked,
        "updated": updated,
        "failed_checks": failed,
        "skipped": skipped,
        "marked_offline": marked_offline,
        "price_updates": price_updates,
    }
    logger.info(f"Stock check complete: {last_result}")
    return last_result


def get_status() -> dict:
    """Return last run info for the status endpoint."""
    return {
        "last_run": last_run,
        "last_result": last_result,
        "scheduled": True,
        "interval_minutes": 30,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_stock_check()
