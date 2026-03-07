"""SQLite database connection and helpers."""
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).parent.parent / "data" / "catalog.db"))
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    # Add category column if upgrading from older schema
    try:
        conn.execute("SELECT category FROM products LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT 'sneakers'")
        conn.commit()
        print("[FASHION-] Added 'category' column to products table")
    # Add size_original column if upgrading from older schema
    try:
        conn.execute("SELECT size_original FROM product_sizes LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE product_sizes ADD COLUMN size_original TEXT")
        conn.commit()
        print("[FASHION-] Added 'size_original' column to product_sizes table")
    # Add status + fail_count columns if upgrading
    try:
        conn.execute("SELECT status FROM products LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE products ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        conn.commit()
        print("[FASHION-] Added 'status' column to products table")
    try:
        conn.execute("SELECT fail_count FROM products LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE products ADD COLUMN fail_count INTEGER NOT NULL DEFAULT 0")
        conn.commit()
        print("[FASHION-] Added 'fail_count' column to products table")
    # Fix END Clothing shipping cost if it was seeded with old value
    conn.execute(
        "UPDATE stores SET shipping_cost = 11.99 WHERE base_url = 'https://www.endclothing.com' AND shipping_cost != 11.99"
    )
    # Remove incorrect free_ship_min for END (they don't offer free shipping)
    conn.execute(
        "UPDATE stores SET free_ship_min = NULL WHERE base_url = 'https://www.endclothing.com'"
    )
    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")


def insert_product(conn: sqlite3.Connection, product: dict) -> int:
    cursor = conn.execute(
        """INSERT INTO products
        (store_id, name, brand, slug, sku, colorway, category,
         original_price, sale_price, discount_pct,
         description, product_url, in_stock)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            product["store_id"],
            product["name"],
            product["brand"],
            product["slug"],
            product.get("sku"),
            product.get("colorway"),
            product.get("category", "sneakers"),
            product["original_price"],
            product["sale_price"],
            product["discount_pct"],
            product.get("description"),
            product["product_url"],
            1 if product.get("in_stock", True) else 0,
        ),
    )
    return cursor.lastrowid


def insert_images(conn: sqlite3.Connection, product_id: int, images: list):
    for i, img in enumerate(images):
        conn.execute(
            """INSERT INTO product_images (product_id, image_url, position, alt_text)
            VALUES (?, ?, ?, ?)""",
            (product_id, img["url"], i, img.get("alt")),
        )


def insert_sizes(conn: sqlite3.Connection, product_id: int, sizes: list):
    for size in sizes:
        conn.execute(
            """INSERT OR REPLACE INTO product_sizes
            (product_id, size_label, size_original, in_stock, variant_id)
            VALUES (?, ?, ?, ?, ?)""",
            (
                product_id,
                size["label"],
                size.get("original_label"),
                1 if size["in_stock"] else 0,
                size.get("variant_id"),
            ),
        )


def get_store_by_platform(conn: sqlite3.Connection, base_url: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM stores WHERE base_url = ?", (base_url,)
    ).fetchone()
    return dict(row) if row else None


def get_all_products(conn: sqlite3.Connection, filters: dict = None) -> list:
    query = """SELECT p.*, s.name as store_name, s.shipping_cost
               FROM products p JOIN stores s ON p.store_id = s.id WHERE 1=1"""
    params = []

    if filters:
        if filters.get("in_stock"):
            query += " AND p.in_stock = 1"
        # Never show removed products (confirmed dead)
        query += " AND p.status != 'removed'"
        if filters.get("brand"):
            query += " AND p.brand = ?"
            params.append(filters["brand"])
        if filters.get("store_id"):
            query += " AND p.store_id = ?"
            params.append(filters["store_id"])
        if filters.get("category"):
            query += " AND p.category = ?"
            params.append(filters["category"])
        if filters.get("size"):
            query += """ AND p.id IN (
                SELECT product_id FROM product_sizes
                WHERE size_label = ? AND in_stock = 1
            )"""
            params.append(filters["size"])

    query += " ORDER BY p.featured DESC, p.sort_order ASC, p.added_at DESC"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_product_by_slug(conn: sqlite3.Connection, slug: str) -> dict | None:
    row = conn.execute(
        """SELECT p.*, s.name as store_name, s.shipping_cost, s.free_ship_min
        FROM products p JOIN stores s ON p.store_id = s.id
        WHERE p.slug = ?""",
        (slug,),
    ).fetchone()
    if not row:
        return None

    product = dict(row)
    product["images"] = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM product_images WHERE product_id = ? ORDER BY position",
            (product["id"],),
        ).fetchall()
    ]
    product["sizes"] = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM product_sizes WHERE product_id = ? ORDER BY size_label",
            (product["id"],),
        ).fetchall()
    ]
    return product


if __name__ == "__main__":
    init_db()
