"""Migration: convert existing product sizes to EU format.

Run once: python -m scripts.migrate_eu_sizes
(from the backend/ directory)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import get_db
from utils.size_converter import convert_to_eu


def migrate():
    conn = get_db()
    
    # Add size_original column if it doesn't exist
    try:
        conn.execute("SELECT size_original FROM product_sizes LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE product_sizes ADD COLUMN size_original TEXT")
        conn.commit()
        print("Added size_original column")
    
    # Get all sizes with their product category
    rows = conn.execute("""
        SELECT ps.id, ps.size_label, ps.size_original, p.category
        FROM product_sizes ps
        JOIN products p ON ps.product_id = p.id
    """).fetchall()
    
    converted = 0
    skipped = 0
    
    for row in rows:
        raw = row["size_original"] or row["size_label"]
        eu = convert_to_eu(raw, row["category"])
        
        if eu != row["size_label"] or row["size_original"] is None:
            conn.execute(
                "UPDATE product_sizes SET size_label = ?, size_original = ? WHERE id = ?",
                (eu, raw, row["id"]),
            )
            converted += 1
            if eu != raw:
                print(f"  {raw} -> {eu} ({row['category']})")
        else:
            skipped += 1
    
    conn.commit()
    conn.close()
    print(f"\nDone! Converted: {converted}, Already EU: {skipped}")


if __name__ == "__main__":
    migrate()
