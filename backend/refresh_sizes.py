"""Refresh sizes for existing products with correct gender-aware EU conversion.

Re-fetches size data from store APIs and updates the database with
correctly converted EU sizes.

Usage:
    python refresh_sizes.py              # Refresh all products
    python refresh_sizes.py --store afew # AFEW only
"""
import time
import logging
from database import get_db, insert_sizes
from utils.size_converter import convert_to_eu, detect_gender_from_tags
from utils.http_retry import request_with_retry
import requests

logger = logging.getLogger("refresh_sizes")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
})


def refresh_afew_sizes(conn) -> dict:
    """Re-fetch sizes from Shopify .js and re-convert with correct gender."""
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

            # Get tags for gender detection
            tags = data.get("tags", [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",")]

            gender = detect_gender_from_tags(tags=tags, name=p["name"])
            category = p["category"]

            # Delete old sizes
            conn.execute("DELETE FROM product_sizes WHERE product_id = ?", (p["id"],))

            # Re-insert with correct conversion
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

            # Update overall in_stock
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    conn = get_db()
    result = refresh_afew_sizes(conn)
    conn.close()
    print(f"\nResults: {result}")
