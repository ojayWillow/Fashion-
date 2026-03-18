"""One-time fix: Naked CPH prices were overwritten in DKK instead of EUR.

The stock checker wrote raw DKK values directly to the DB without the
DKK_TO_EUR (0.134) conversion that naked.py applies at fetch time.

This script:
1. Re-fetches each Naked CPH product page live to get the correct EUR price
2. Updates sale_price, original_price, discount_pct in the DB
3. Logs what was fixed

Run once, then delete.
"""
import sys
import logging
from database import get_db
from fetchers.naked import fetch_naked_product

logging.basicConfig(level=logging.WARNING)  # suppress noisy fetcher logs
logger = logging.getLogger("fix_naked_prices")

conn = get_db()

products = conn.execute(
    """SELECT p.id, p.slug, p.product_url, p.sale_price, p.original_price, p.discount_pct
    FROM products p
    JOIN stores s ON p.store_id = s.id
    WHERE s.name = 'Naked Copenhagen'
    AND p.status != 'removed'"""
).fetchall()
products = [dict(p) for p in products]

print(f"Found {len(products)} Naked CPH products to fix.\n")
print(f"{'SLUG':<60} {'OLD SALE':>9} {'NEW SALE':>9} {'STATUS'}")
print("-" * 100)

fixed = 0
failed = 0

for p in products:
    try:
        data = fetch_naked_product(p["product_url"])
        new_sale = data["sale_price"]
        new_original = data["original_price"]
        new_discount = data["discount_pct"]

        conn.execute(
            """UPDATE products
            SET sale_price = ?, original_price = ?, discount_pct = ?
            WHERE id = ?""",
            (new_sale, new_original, new_discount, p["id"]),
        )
        print(f"{p['slug']:<60} {p['sale_price']:>9.2f} {new_sale:>9.2f}  FIXED")
        fixed += 1
    except Exception as e:
        print(f"{p['slug']:<60} {p['sale_price']:>9.2f} {'ERROR':>9}  {e}")
        failed += 1

conn.commit()
conn.close()

print(f"\nDone. Fixed: {fixed}, Failed: {failed}")
if failed:
    print("Re-run for failed products or fix manually.")
