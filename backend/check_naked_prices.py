"""Temporary script — check current Naked CPH prices in DB, then delete."""
from database import get_db

conn = get_db()
rows = conn.execute(
    """SELECT p.slug, p.sale_price, p.original_price, p.discount_pct
    FROM products p
    JOIN stores s ON p.store_id = s.id
    WHERE s.name = 'Naked Copenhagen'"""
).fetchall()

if not rows:
    print("No Naked Copenhagen products found.")
else:
    print(f"{'SLUG':<60} {'SALE':>8} {'ORIGINAL':>10} {'DISC%':>6}")
    print("-" * 90)
    for r in rows:
        print(f"{r['slug']:<60} {r['sale_price']:>8.2f} {r['original_price']:>10.2f} {r['discount_pct']:>6}%")

conn.close()
