"""Stock checker - periodically verify product availability.

Run directly: python stock_checker.py
Or import and schedule with APScheduler.
"""
import requests
from datetime import datetime
from database import get_db


def check_shopify_product(product_url: str, handle: str) -> dict:
    """Check stock for a single Shopify product."""
    base = product_url.split("/products/")[0]
    json_url = f"{base}/products/{handle}.json"

    resp = requests.get(json_url, timeout=15)
    resp.raise_for_status()
    data = resp.json()["product"]

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
    """Check all Shopify products and update the database."""
    conn = get_db()
    now = datetime.utcnow().isoformat()

    products = conn.execute(
        """SELECT p.id, p.slug, p.product_url, p.in_stock
        FROM products p
        JOIN stores s ON p.store_id = s.id
        WHERE s.platform = 'shopify'"""
    ).fetchall()

    print(f"[{now}] Checking {len(products)} Shopify products...")

    for p in products:
        product_id = p["id"]
        try:
            result = check_shopify_product(p["product_url"], p["slug"])

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
                """INSERT INTO stock_checks (product_id, was_in_stock, sizes_available)
                VALUES (?, ?, ?)""",
                (product_id, 1 if result["any_in_stock"] else 0, result["sizes_available"]),
            )

            status = "in stock" if result["any_in_stock"] else "SOLD OUT"
            print(f"  {p['slug']}: {status} ({result['sizes_available']} sizes)")

        except Exception as e:
            print(f"  {p['slug']}: ERROR - {e}")
            conn.execute(
                "INSERT INTO stock_checks (product_id, was_in_stock, sizes_available, raw_response) VALUES (?, ?, 0, ?)",
                (product_id, p["in_stock"], str(e)),
            )

    conn.commit()
    conn.close()
    print("Stock check complete.")


if __name__ == "__main__":
    run_stock_check()
