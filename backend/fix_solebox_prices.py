"""One-time migration: fix Solebox product prices that were stored as cents instead of euros.

Run from the backend/ directory:
    python fix_solebox_prices.py

What it does:
    - Finds all products from the Solebox store in the DB
    - If sale_price > 1000, it was stored as cents (e.g. 21399 instead of 213.99)
    - Divides both sale_price and original_price by 100 and updates the DB
    - Recalculates discount_pct
    - Prints a summary of every product changed

Safe to re-run: products already at correct price (< 1000) are skipped.
"""
import sqlite3
from pathlib import Path
import os

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).parent.parent / "data" / "catalog.db"))


def fix_prices():
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Get the Solebox store ID
    store = conn.execute(
        "SELECT id, name FROM stores WHERE base_url LIKE '%solebox%'"
    ).fetchone()

    if not store:
        print("ERROR: Solebox store not found in DB. Check the stores table.")
        conn.close()
        return

    store_id = store["id"]
    print(f"Found Solebox store: id={store_id}, name={store['name']}")

    # Find all Solebox products where price looks like cents (> 1000)
    products = conn.execute(
        "SELECT id, name, sale_price, original_price, discount_pct FROM products WHERE store_id = ?",
        (store_id,)
    ).fetchall()

    if not products:
        print("No Solebox products found in DB.")
        conn.close()
        return

    print(f"\nFound {len(products)} Solebox products total.")
    print("-" * 70)

    fixed = 0
    skipped = 0

    for p in products:
        sale    = p["sale_price"]
        original = p["original_price"]

        if sale > 1000:
            new_sale     = round(sale / 100, 2)
            new_original = round(original / 100, 2)
            new_discount = round((1 - new_sale / new_original) * 100) if new_original > new_sale else 0

            conn.execute(
                "UPDATE products SET sale_price=?, original_price=?, discount_pct=? WHERE id=?",
                (new_sale, new_original, new_discount, p["id"])
            )
            conn.commit()

            print(f"  FIXED  [{p['id']:>4}] {p['name'][:45]:<45}  €{sale:.2f} -> €{new_sale:.2f}")
            fixed += 1
        else:
            print(f"  OK     [{p['id']:>4}] {p['name'][:45]:<45}  €{sale:.2f} (no change)")
            skipped += 1

    print("-" * 70)
    print(f"Done. Fixed: {fixed}  |  Already correct: {skipped}")
    conn.close()


if __name__ == "__main__":
    fix_prices()
