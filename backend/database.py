"""SQLite database connection and helpers."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "catalog.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_db() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Initialize database from schema.sql."""
    conn = get_db()
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    conn.close()
    print(f"Database initialized at {DB_PATH}")


def insert_product(conn: sqlite3.Connection, product: dict) -> int:
    """Insert a product and return its ID."""
    cursor = conn.execute(
        """INSERT INTO products
        (store_id, name, brand, slug, sku, colorway,
         original_price, sale_price, discount_pct,
         description, product_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            product["store_id"],
            product["name"],
            product["brand"],
            product["slug"],
            product.get("sku"),
            product.get("colorway"),
            product["original_price"],
            product["sale_price"],
            product["discount_pct"],
            product.get("description"),
            product["product_url"],
        ),
    )
    return cursor.lastrowid


def insert_images(conn: sqlite3.Connection, product_id: int, images: list):
    """Insert product images."""
    for i, img in enumerate(images):
        conn.execute(
            """INSERT INTO product_images (product_id, image_url, position, alt_text)
            VALUES (?, ?, ?, ?)""",
            (product_id, img["url"], i, img.get("alt")),
        )


def insert_sizes(conn: sqlite3.Connection, product_id: int, sizes: list):
    """Insert product sizes."""
    for size in sizes:
        conn.execute(
            """INSERT OR REPLACE INTO product_sizes
            (product_id, size_label, in_stock, variant_id)
            VALUES (?, ?, ?, ?)""",
            (
                product_id,
                size["label"],
                1 if size["in_stock"] else 0,
                size.get("variant_id"),
            ),
        )


def get_store_by_platform(conn: sqlite3.Connection, base_url: str) -> dict | None:
    """Find a store by its base URL."""
    row = conn.execute(
        "SELECT * FROM stores WHERE base_url = ?", (base_url,)
    ).fetchone()
    return dict(row) if row else None


def get_all_products(conn: sqlite3.Connection, filters: dict = None) -> list:
    """Get all products with optional filters."""
    query = "SELECT p.*, s.name as store_name, s.shipping_cost FROM products p JOIN stores s ON p.store_id = s.id WHERE 1=1"
    params = []

    if filters:
        if filters.get("in_stock"):
            query += " AND p.in_stock = 1"
        if filters.get("brand"):
            query += " AND p.brand = ?"
            params.append(filters["brand"])
        if filters.get("store_id"):
            query += " AND p.store_id = ?"
            params.append(filters["store_id"])
        if filters.get("min_discount"):
            query += " AND p.discount_pct >= ?"
            params.append(filters["min_discount"])

    query += " ORDER BY p.featured DESC, p.sort_order ASC, p.added_at DESC"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_product_by_slug(conn: sqlite3.Connection, slug: str) -> dict | None:
    """Get a single product by slug, including images and sizes."""
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
