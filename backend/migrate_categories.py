"""Migration: auto-detect category for all existing products.

Reads each product's URL, fetches the Shopify .json, and assigns
a category based on product type, tags, and name keywords.

Usage:
    cd backend && python migrate_categories.py
"""
import time
import sqlite3
import requests
from pathlib import Path
from urllib.parse import urlparse

DB_PATH = Path(__file__).parent.parent / "data" / "catalog.db"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
})

# Keywords to detect category
SNEAKER_WORDS = ['sneaker', 'shoe', 'footwear', 'runner', 'trainer', 'boot', 'slide', 'sandal', 'clog', 'mule', 'slipper', 'foam', 'yeezy', 'dunk', 'jordan', 'air max', 'gel-', 'chuck', '550', '530', '2002r', '990', '1906', 'ultraboost', 'ozweego', 'forum', 'samba', 'gazelle', 'campus', 'old skool', 'sk8', 'classic leather']
CLOTHING_WORDS = ['hoodie', 'jacket', 'shirt', 't-shirt', 'tee', 'pants', 'jogger', 'shorts', 'sweater', 'crewneck', 'crew neck', 'pullover', 'vest', 'coat', 'parka', 'windbreaker', 'tracksuit', 'sweatshirt', 'sweatpant', 'jersey', 'polo', 'cardigan', 'fleece', 'puffer', 'anorak', 'dress', 'skirt', 'legging', 'trouser', 'cargo', 'denim', 'jeans', 'tank top', 'longsleeve', 'apparel', 'clothing']
ACCESSORY_WORDS = ['cap', 'hat', 'beanie', 'bag', 'backpack', 'wallet', 'belt', 'sock', 'scarf', 'glove', 'sunglasses', 'watch', 'keychain', 'headband', 'wristband', 'accessory', 'accessories', 'case', 'pouch', 'tote', 'duffle']
KIDS_WORDS = ['kids', 'junior', 'youth', 'gs ', ' gs', 'grade school', 'big kid', 'little kid']
TODDLER_WORDS = ['toddler', 'infant', 'baby', 'td ', ' td', 'crib']


def detect_category(name: str, product_type: str, tags: list) -> str:
    """Detect category from product metadata."""
    text = f"{name} {product_type} {' '.join(tags)}".lower()

    # Check toddler first (most specific)
    if any(w in text for w in TODDLER_WORDS):
        return 'toddler'

    # Then kids
    if any(w in text for w in KIDS_WORDS):
        return 'kids'

    # Check product type field (most reliable when present)
    ptype = product_type.lower().strip()
    if ptype in ['footwear', 'shoes', 'sneakers']:
        return 'sneakers'
    if ptype in ['apparel', 'clothing', 'tops', 'bottoms', 'outerwear']:
        return 'clothing'
    if ptype in ['accessories', 'bags', 'hats', 'socks']:
        return 'accessories'

    # Check type tags
    for tag in tags:
        tl = tag.lower()
        if tl.startswith('type:'):
            val = tl.split(':', 1)[1].strip()
            if val in ['footwear', 'shoes', 'sneakers', 'sneaker']:
                return 'sneakers'
            if val in ['apparel', 'clothing', 'tops', 'bottoms']:
                return 'clothing'
            if val in ['accessories', 'accessory']:
                return 'accessories'

    # Keyword matching
    if any(w in text for w in ACCESSORY_WORDS):
        return 'accessories'
    if any(w in text for w in CLOTHING_WORDS):
        return 'clothing'
    if any(w in text for w in SNEAKER_WORDS):
        return 'sneakers'

    return 'sneakers'  # default


def migrate():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Ensure category column exists
    try:
        conn.execute("SELECT category FROM products LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT 'sneakers'")
        conn.commit()
        print("Added category column")

    products = conn.execute("SELECT id, name, product_url FROM products").fetchall()
    print(f"Found {len(products)} products to categorize\n")

    stats = {'sneakers': 0, 'clothing': 0, 'accessories': 0, 'kids': 0, 'toddler': 0, 'error': 0}

    for i, p in enumerate(products):
        url = p['product_url']
        name = p['name']
        parsed = urlparse(url)
        handle = parsed.path.rstrip('/').split('/')[-1]
        base = f"{parsed.scheme}://{parsed.netloc}"

        try:
            resp = SESSION.get(f"{base}/products/{handle}.json", timeout=10)
            if resp.status_code == 429:
                print(f"  Rate limited, waiting 5s...")
                time.sleep(5)
                resp = SESSION.get(f"{base}/products/{handle}.json", timeout=10)

            resp.raise_for_status()
            data = resp.json()['product']

            product_type = data.get('product_type', '')
            tags = data.get('tags', [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(',')]

            category = detect_category(name, product_type, tags)

            conn.execute("UPDATE products SET category = ? WHERE id = ?", (category, p['id']))
            stats[category] = stats.get(category, 0) + 1
            print(f"  [{i+1}/{len(products)}] {category.upper():12s} | {name[:60]}")

            time.sleep(0.3)  # be nice to the API

        except Exception as e:
            print(f"  [{i+1}/{len(products)}] ERROR        | {name[:60]} -> {e}")
            stats['error'] += 1

    conn.commit()
    conn.close()

    print(f"\n=== DONE ===")
    for cat, count in sorted(stats.items()):
        if count > 0:
            print(f"  {cat}: {count}")


if __name__ == '__main__':
    migrate()
