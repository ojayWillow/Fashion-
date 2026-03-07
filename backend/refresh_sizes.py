"""Refresh sizes for existing products with correct conversion.

Re-fetches size data from store APIs and updates the database with
correctly converted sizes.

Usage:
    python refresh_sizes.py              # Refresh all products
    python refresh_sizes.py --store afew # AFEW only
    python refresh_sizes.py --store end  # END only
"""
import sys
import time
import logging
from database import get_db, insert_sizes
from utils.size_converter import convert_to_eu, detect_gender_from_tags
from utils.category_detector import detect_category

logger = logging.getLogger("refresh_sizes")


def refresh_afew_sizes(conn) -> dict:
    """Re-fetch sizes from Shopify .js and re-convert with correct gender."""
    from utils.http_retry import request_with_retry
    import requests

    SESSION = requests.Session()
    SESSION.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })

    products = conn.execute("""
        SELECT p.id, p.name, p.product_url, p.slug, p.category
        FROM products p
        JOIN stores s ON p.store_id = s.id
        WHERE s.base_url = 'https://en.afew-store.com'
        AND p.status != 'removed'
    """).fetchall()

    total = len(products)
    updated = 0
    failed = 0

    logger.info(f"Refreshing sizes for {total} AFEW products...")

    for p in products:
        try:
            slug = p["slug"]
            js_url = f"https://en.afew-store.com/products/{slug}.js"
            resp = request_with_retry(js_url, session=SESSION, timeout=15)

            if resp.status_code != 200:
                logger.warning(f"  {p['name']}: HTTP {resp.status_code}, skipping")
                failed += 1
                continue

            data = resp.json()

            tags = data.get("tags", [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",")]

            gender = detect_gender_from_tags(tags=tags, name=p["name"])
            category = p["category"]

            conn.execute("DELETE FROM product_sizes WHERE product_id = ?", (p["id"],))

            new_sizes = []
            for v in data.get("variants", []):
                raw_label = v.get("option1", v.get("title", "?"))
                eu_label = convert_to_eu(raw_label, category, gender=gender)
                new_sizes.append({
                    "label": eu_label,
                    "original_label": raw_label,
                    "in_stock": v.get("available", False),
                    "variant_id": str(v["id"]),
                })

            insert_sizes(conn, p["id"], new_sizes)

            any_in_stock = any(s["in_stock"] for s in new_sizes)
            conn.execute(
                "UPDATE products SET in_stock = ? WHERE id = ?",
                (1 if any_in_stock else 0, p["id"]),
            )

            in_stock_count = sum(1 for s in new_sizes if s["in_stock"])
            logger.info(f"  {p['name']}: {len(new_sizes)} sizes, {in_stock_count} in stock (gender={gender}) \u2705")
            updated += 1

        except Exception as e:
            logger.error(f"  {p['name']}: FAILED - {e}")
            failed += 1

        time.sleep(0.5)

    conn.commit()
    return {"total": total, "updated": updated, "failed": failed}


def refresh_end_sizes(conn) -> dict:
    """Re-fetch sizes from END Algolia and re-convert UK -> EU.

    Uses the updated _end_worker which:
    - Finds products via SKU or name fallback
    - Returns footwear_size_label (only available sizes)
    - Labels are UK-prefixed ('UK 8') so convert_to_eu handles them
    """
    from fetchers._end_worker import _find_product_in_algolia, _parse_sizes

    products = conn.execute("""
        SELECT p.id, p.name, p.product_url, p.category
        FROM products p
        JOIN stores s ON p.store_id = s.id
        WHERE s.base_url = 'https://www.endclothing.com'
        AND p.status != 'removed'
    """).fetchall()

    total = len(products)
    updated = 0
    failed = 0
    skipped = 0

    logger.info(f"Refreshing sizes for {total} END products...")

    for p in products:
        try:
            hit = _find_product_in_algolia(p["product_url"])

            if not hit:
                logger.warning(f"  {p['name']}: not found in Algolia, skipping")
                skipped += 1
                continue

            raw_sizes = _parse_sizes(hit)

            if not raw_sizes:
                logger.warning(f"  {p['name']}: no sizes from Algolia, skipping")
                skipped += 1
                continue

            # Detect gender from Algolia hit
            gender_field = (hit.get("gender") or "").lower().strip()
            if gender_field in ("women", "womens", "woman"):
                gender = "women"
            elif gender_field in ("kids", "youth", "junior"):
                gender = "kids"
            else:
                gender = "men"

            category = p["category"] or detect_category(
                p["name"], breadcrumbs=hit.get("department_hierarchy", [])
            )

            # Delete old sizes
            conn.execute("DELETE FROM product_sizes WHERE product_id = ?", (p["id"],))

            # Convert and insert new sizes
            new_sizes = []
            for s in raw_sizes:
                raw_label = s["raw_label"]
                eu_label = convert_to_eu(raw_label, category, gender=gender)
                new_sizes.append({
                    "label": eu_label,
                    "original_label": raw_label,
                    "in_stock": s["in_stock"],
                    "variant_id": s.get("variant_id"),
                })

            insert_sizes(conn, p["id"], new_sizes)

            # Update product in_stock status
            any_in_stock = any(s["in_stock"] for s in new_sizes)
            conn.execute(
                "UPDATE products SET in_stock = ? WHERE id = ?",
                (1 if any_in_stock else 0, p["id"]),
            )

            in_stock_count = sum(1 for s in new_sizes if s["in_stock"])
            logger.info(
                f"  {p['name']}: {len(new_sizes)} sizes, "
                f"{in_stock_count} in stock (gender={gender}) \u2705"
            )
            updated += 1

        except Exception as e:
            logger.error(f"  {p['name']}: FAILED - {e}")
            failed += 1

        time.sleep(1)

    conn.commit()
    return {"total": total, "updated": updated, "failed": failed, "skipped": skipped}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
    )

    store_filter = None
    if "--store" in sys.argv:
        idx = sys.argv.index("--store")
        if idx + 1 < len(sys.argv):
            store_filter = sys.argv[idx + 1].lower()

    conn = get_db()

    if store_filter in (None, "afew"):
        result = refresh_afew_sizes(conn)
        print(f"\nAFEW: {result}")

    if store_filter in (None, "end"):
        result = refresh_end_sizes(conn)
        print(f"\nEND: {result}")

    conn.close()
    print("\nDone!")
