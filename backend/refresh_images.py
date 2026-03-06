"""Refresh images for existing products.

Re-fetches images from store pages and updates the database.
Useful after upgrading the image scraping logic (e.g., AFEW CDN packshots).

Usage:
    python refresh_images.py              # Refresh all AFEW products
    python refresh_images.py --store all  # Refresh all stores
    python refresh_images.py --store end  # Refresh END products only
"""
import time
import logging
import argparse
from database import get_db, insert_images
from fetchers.shopify import _scrape_afew_cdn_images

logger = logging.getLogger("refresh_images")


def refresh_afew_images(conn, product_ids: list[int] | None = None) -> dict:
    """Re-scrape AFEW CDN images for existing AFEW products."""
    query = """
        SELECT p.id, p.name, p.product_url, p.slug
        FROM products p
        JOIN stores s ON p.store_id = s.id
        WHERE s.base_url = 'https://en.afew-store.com'
        AND p.status != 'removed'
    """
    params = []
    if product_ids:
        placeholders = ",".join("?" for _ in product_ids)
        query += f" AND p.id IN ({placeholders})"
        params = product_ids

    products = conn.execute(query, params).fetchall()
    total = len(products)
    updated = 0
    skipped = 0
    failed = 0

    logger.info(f"Refreshing images for {total} AFEW products...")

    for p in products:
        product_id = p["id"]
        name = p["name"]
        url = p["product_url"]

        try:
            cdn_images = _scrape_afew_cdn_images(url)

            if not cdn_images:
                logger.info(f"  {name}: no CDN images found, keeping existing")
                skipped += 1
                continue

            # Check current image count
            current = conn.execute(
                "SELECT COUNT(*) as cnt FROM product_images WHERE product_id = ?",
                (product_id,),
            ).fetchone()["cnt"]

            if current >= len(cdn_images):
                logger.info(f"  {name}: already has {current} images, skipping")
                skipped += 1
                continue

            # Delete old images and insert new ones
            conn.execute(
                "DELETE FROM product_images WHERE product_id = ?",
                (product_id,),
            )

            images = [
                {"url": url, "alt": f"{name} - image {i+1}"}
                for i, url in enumerate(cdn_images)
            ]
            insert_images(conn, product_id, images)

            logger.info(f"  {name}: {current} -> {len(cdn_images)} images \u2705")
            updated += 1

        except Exception as e:
            logger.error(f"  {name}: FAILED - {e}")
            failed += 1

        time.sleep(0.5)  # Be nice to AFEW's server

    conn.commit()

    result = {
        "total": total,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
    }
    logger.info(f"Image refresh complete: {result}")
    return result


def refresh_all_images(store_filter: str = "afew") -> dict:
    """Main entry point for image refresh."""
    conn = get_db()
    results = {}

    if store_filter in ("afew", "all"):
        results["afew"] = refresh_afew_images(conn)

    # END images come from Algolia and are already good,
    # but we can add a refresh here later if needed
    if store_filter in ("end", "all"):
        logger.info("END Clothing images are fetched via Algolia - no refresh needed")
        results["end"] = {"status": "skipped", "reason": "Algolia images are already high quality"}

    conn.close()
    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="Refresh product images")
    parser.add_argument(
        "--store",
        choices=["afew", "end", "all"],
        default="afew",
        help="Which store to refresh (default: afew)",
    )
    args = parser.parse_args()

    results = refresh_all_images(args.store)
    print(f"\nResults: {results}")
