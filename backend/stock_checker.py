"""Stock checker - periodically verify product availability.

Run directly: python stock_checker.py
Or import run_stock_check() — auto-scheduled via APScheduler in app.py.
"""
import logging
import requests
from datetime import datetime, timezone
from database import get_db

logger = logging.getLogger("stock_checker")

# Module-level state for status reporting
last_run = None
last_result = None


def check_shopify_product(product_url: str, handle: str) -> dict:
    """Check stock for a single Shopify product.

    Uses the .js endpoint because .json does NOT include the
    `available` field for many Shopify stores (returns None).
    """
    base = product_url.split("/products/")[0]
    js_url = f"{base}/products/{handle}.js"

    resp = requests.get(js_url, timeout=15)
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
        "any_in_stock": any(s["in_stock"] for s in sizes),
        "sizes": sizes,
        "sizes_available": sum(1 for s in sizes if s["in_stock"]),
    }


def run_stock_check():
    """Check all products and update the database.

    - Shopify products: auto-checked via .js endpoint
    - Non-Shopify products: skipped, flagged for manual review
    - 404 responses: product marked as offline/removed
    """
    global last_run, last_result

    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()

    products = conn.execute(
        """SELECT p.id, p.slug, p.product_url, p.in_stock, s.platform
        FROM products p
        JOIN stores s ON p.store_id = s.id"""
    ).fetchall()

    total = len(products)
    checked = 0
    skipped = 0
    offline = 0
    errors = 0
    updated = 0

    logger.info(f"Stock check started — {total} products")

    for p in products:
        product_id = p["id"]
        platform = p["platform"]

        # --- Non-Shopify: skip and flag ---
        if platform != "shopify":
            skipped += 1
            conn.execute(
                """INSERT INTO stock_checks
                (product_id, was_in_stock, sizes_available, raw_response)
                VALUES (?, ?, 0, ?)""",
                (product_id, p["in_stock"], "SKIPPED: non-Shopify, needs manual review"),
            )
            logger.info(f"  {p['slug']}: SKIPPED (platform={platform})")
            continue

        # --- Shopify: auto-check ---
        try:
            handle = p["product_url"].rstrip("/").split("/products/")[-1].split("?")[0]
            result = check_shopify_product(p["product_url"], handle)
            checked += 1

            conn.execute(
                "UPDATE products SET in_stock = ?, last_checked = ?, updated_at = ? WHERE id = ?",
                (1 if result["any_in_stock"] else 0, now, now, product_id),
            )

            for size in result["sizes"]:
                conn.execute(
                    """UPDATE product_sizes
                    SET in_stock = ?, last_checked = ?
                    WHERE product_id = ? AND variant_id = ?""",
                    (1 if size["in_stock"] else 0, now, product_id, size["variant_id"]),
                )

            conn.execute(
                """INSERT INTO stock_checks
                (product_id, was_in_stock, sizes_available)
                VALUES (?, ?, ?)""",
                (product_id, 1 if result["any_in_stock"] else 0, result["sizes_available"]),
            )

            status = "in stock" if result["any_in_stock"] else "SOLD OUT"
            logger.info(f"  {p['slug']}: {status} ({result['sizes_available']} sizes)")
            updated += 1

        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                offline += 1
                conn.execute(
                    "UPDATE products SET in_stock = 0, last_checked = ?, updated_at = ? WHERE id = ?",
                    (now, now, product_id),
                )
                conn.execute(
                    """INSERT INTO stock_checks
                    (product_id, was_in_stock, sizes_available, raw_response)
                    VALUES (?, 0, 0, ?)""",
                    (product_id, "OFFLINE: product returned 404 — removed from store"),
                )
                logger.warning(f"  {p['slug']}: OFFLINE (404)")
            else:
                errors += 1
                conn.execute(
                    """INSERT INTO stock_checks
                    (product_id, was_in_stock, sizes_available, raw_response)
                    VALUES (?, ?, 0, ?)""",
                    (product_id, p["in_stock"], f"HTTP_ERROR: {e}"),
                )
                logger.error(f"  {p['slug']}: HTTP ERROR - {e}")

        except Exception as e:
            errors += 1
            conn.execute(
                """INSERT INTO stock_checks
                (product_id, was_in_stock, sizes_available, raw_response)
                VALUES (?, ?, 0, ?)""",
                (product_id, p["in_stock"], f"ERROR: {e}"),
            )
            logger.error(f"  {p['slug']}: ERROR - {e}")

    conn.commit()
    conn.close()

    last_run = now
    last_result = {
        "total": total,
        "checked": checked,
        "updated": updated,
        "skipped_non_shopify": skipped,
        "marked_offline": offline,
        "errors": errors,
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
