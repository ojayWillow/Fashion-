"""Stock checker — periodically verify product availability.

Supports multiple store platforms via a dispatcher pattern.
Each store has its own check function but returns a standardized result.

Safety: products are NOT marked offline on first failure.
Requires 3 consecutive failures before marking unavailable.

Run directly: python stock_checker.py
Or import run_stock_check() — auto-scheduled via APScheduler in app.py.
"""
import time
import logging
from datetime import datetime, timezone
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


# ── Standardized result format ────────────────────────────────────
#
#   {
#       "success": True/False,       — did the check itself work?
#       "online": True/False/None,   — is the product page still live? (None = unknown)
#       "any_in_stock": True/False,  — is anything available?
#       "sizes_available": int,      — how many sizes in stock
#       "sizes": [...],              — per-size details (optional)
#       "error": str or None,        — error message if success=False
#   }


# ── Shopify stock check (AFEW etc.) ──────────────────────────────

def check_shopify_stock(product_url: str, handle: str) -> dict:
    """Check stock for a Shopify product via .js endpoint.

    Uses shared retry logic to handle rate limits and transient errors.
    """
    base = product_url.split("/products/")[0]
    js_url = f"{base}/products/{handle}.js"

    try:
        resp = request_with_retry(js_url, max_retries=3, timeout=15)

        if resp.status_code == 404:
            return {
                "success": True,
                "online": False,
                "any_in_stock": False,
                "sizes_available": 0,
                "sizes": [],
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

        return {
            "success": True,
            "online": True,
            "any_in_stock": any(s["in_stock"] for s in sizes),
            "sizes_available": sum(1 for s in sizes if s["in_stock"]),
            "sizes": sizes,
            "error": None,
        }

    except Exception as e:
        return {
            "success": False,
            "online": None,
            "any_in_stock": None,
            "sizes_available": 0,
            "sizes": [],
            "error": str(e),
        }


# ── END Clothing stock check (Algolia) ───────────────────────────

def check_end_stock(product_url: str, sku: str | None) -> dict:
    """Check stock for an END Clothing product via Algolia.

    Re-queries the same Algolia proxy used during initial fetch.
    Returns per-size stock status.
    """
    if not sku:
        # Try to extract SKU from URL
        import re
        from urllib.parse import urlparse
        slug = urlparse(product_url).path.rstrip("/").split("/")[-1].replace(".html", "")
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
            timeout=15,
        )

        if resp.status_code != 200:
            return {
                "success": False,
                "online": None,
                "any_in_stock": None,
                "sizes_available": 0,
                "sizes": [],
                "error": f"Algolia HTTP {resp.status_code}",
            }

        hits = resp.json().get("hits", [])

        # Find exact SKU match
        hit = None
        for h in hits:
            if h.get("sku", "").upper() == sku.upper():
                hit = h
                break
        if not hit and hits:
            hit = hits[0]

        if not hit:
            # Product not found in Algolia — might be removed
            return {
                "success": True,
                "online": False,
                "any_in_stock": False,
                "sizes_available": 0,
                "sizes": [],
                "error": None,
            }

        # Parse sizes from Algolia hit
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

        return {
            "success": True,
            "online": True,
            "any_in_stock": any_available,
            "sizes_available": sum(1 for s in sizes if s["in_stock"]),
            "sizes": sizes,
            "error": None,
        }

    except Exception as e:
        return {
            "success": False,
            "online": None,
            "any_in_stock": None,
            "sizes_available": 0,
            "sizes": [],
            "error": str(e),
        }


# ── Dispatcher ───────────────────────────────────────────────────

def check_product_stock(platform: str, product_url: str, slug: str, sku: str | None) -> dict:
    """Route stock check to the correct store-specific function.

    Every new store just needs a new elif branch here and its own
    check function that returns the standardized result dict.
    """
    if platform == "shopify":
        handle = product_url.rstrip("/").split("/products/")[-1].split("?")[0]
        return check_shopify_stock(product_url, handle)

    elif platform == "custom":
        # END Clothing (and future custom stores)
        if "endclothing.com" in product_url:
            return check_end_stock(product_url, sku)

    # Unknown platform — don't assume anything
    return {
        "success": False,
        "online": None,
        "any_in_stock": None,
        "sizes_available": 0,
        "sizes": [],
        "error": f"No stock checker for platform: {platform}",
    }


# ── Main stock check loop ────────────────────────────────────────

def run_stock_check():
    """Check all products and update the database.

    Safety rules:
    - Failed checks (network errors, timeouts) do NOT change product status
    - Products need 3 consecutive failures before being marked unavailable
    - Only confident "online=False" results mark products offline
    - Successful checks reset the fail counter
    """
    global last_run, last_result

    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()

    products = conn.execute(
        """SELECT p.id, p.slug, p.product_url, p.sku, p.in_stock,
                  p.fail_count, s.platform
        FROM products p
        JOIN stores s ON p.store_id = s.id"""
    ).fetchall()

    total = len(products)
    checked = 0
    updated = 0
    failed = 0
    marked_offline = 0

    logger.info(f"Stock check started — {total} products")

    for p in products:
        product_id = p["id"]
        platform = p["platform"]
        current_fail_count = p["fail_count"] or 0

        result = check_product_stock(
            platform=platform,
            product_url=p["product_url"],
            slug=p["slug"],
            sku=p["sku"],
        )
        checked += 1

        if result["success"]:
            # ✅ Check succeeded — reset fail counter
            new_fail_count = 0

            if result["online"] is False:
                # Product confirmed gone from store
                new_fail_count = current_fail_count + 1

                if new_fail_count >= MAX_FAIL_COUNT:
                    # Confirmed offline after multiple checks
                    conn.execute(
                        """UPDATE products
                        SET in_stock = 0, status = 'removed',
                            fail_count = ?, last_checked = ?, updated_at = ?
                        WHERE id = ?""",
                        (new_fail_count, now, now, product_id),
                    )
                    marked_offline += 1
                    logger.warning(f"  {p['slug']}: REMOVED (confirmed after {new_fail_count} checks)")
                else:
                    # Not yet confirmed — increment but don't change stock
                    conn.execute(
                        """UPDATE products
                        SET fail_count = ?, last_checked = ?, updated_at = ?
                        WHERE id = ?""",
                        (new_fail_count, now, now, product_id),
                    )
                    logger.info(f"  {p['slug']}: not found ({new_fail_count}/{MAX_FAIL_COUNT} strikes)")
            else:
                # Product is online — update stock status
                in_stock = 1 if result["any_in_stock"] else 0
                conn.execute(
                    """UPDATE products
                    SET in_stock = ?, status = 'active',
                        fail_count = 0, last_checked = ?, updated_at = ?
                    WHERE id = ?""",
                    (in_stock, now, now, product_id),
                )

                # Update per-size stock (Shopify: by variant_id, END: by size_label)
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
                        # Match by size label (END Clothing, manual)
                        conn.execute(
                            """UPDATE product_sizes
                            SET in_stock = ?, last_checked = ?
                            WHERE product_id = ? AND size_label = ?""",
                            (in_stock_val, now, product_id, size["label"]),
                        )

                status = "in stock" if result["any_in_stock"] else "SOLD OUT"
                logger.info(f"  {p['slug']}: {status} ({result['sizes_available']} sizes)")
                updated += 1

        else:
            # ❌ Check failed (network error, timeout, etc.)
            # Do NOT change product status — just log and increment fail count
            new_fail_count = current_fail_count + 1
            conn.execute(
                "UPDATE products SET fail_count = ?, last_checked = ? WHERE id = ?",
                (new_fail_count, now, product_id),
            )
            failed += 1
            logger.error(
                f"  {p['slug']}: CHECK FAILED ({new_fail_count}/{MAX_FAIL_COUNT}) — {result['error']}"
            )

        # Log to stock_checks table
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

        time.sleep(CHECK_DELAY)

    conn.commit()
    conn.close()

    last_run = now
    last_result = {
        "total": total,
        "checked": checked,
        "updated": updated,
        "failed_checks": failed,
        "marked_offline": marked_offline,
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
