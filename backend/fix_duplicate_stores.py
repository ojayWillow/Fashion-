"""Fix duplicate stores in the database."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "catalog.db"

def fix_duplicate_stores():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    
    print("Current stores:")
    stores = conn.execute("SELECT id, name, base_url FROM stores ORDER BY id").fetchall()
    for s in stores:
        print(f"  {s['id']}: {s['name']} - {s['base_url']}")
    
    print(f"\nTotal stores: {len(stores)}")
    
    # Find unique stores
    unique_stores = {}
    for store in stores:
        key = (store['name'], store['base_url'])
        if key not in unique_stores:
            unique_stores[key] = store['id']
    
    print(f"Unique stores: {len(unique_stores)}")
    
    # Create mapping of duplicate IDs to keep ID
    id_mapping = {}
    for store in stores:
        key = (store['name'], store['base_url'])
        keep_id = unique_stores[key]
        if store['id'] != keep_id:
            id_mapping[store['id']] = keep_id
    
    print(f"\nDuplicates to merge: {len(id_mapping)}")
    
    if not id_mapping:
        print("No duplicates found!")
        conn.close()
        return
    
    # Update products to use correct store_id
    conn.execute("BEGIN")
    for old_id, new_id in id_mapping.items():
        conn.execute(
            "UPDATE products SET store_id = ? WHERE store_id = ?",
            (new_id, old_id)
        )
        print(f"  Moved products from store {old_id} to {new_id}")
    
    # Delete duplicate stores
    for old_id in id_mapping.keys():
        conn.execute("DELETE FROM stores WHERE id = ?", (old_id,))
        print(f"  Deleted store {old_id}")
    
    conn.execute("COMMIT")
    conn.close()
    
    print("\n✅ Done! Database cleaned.")

if __name__ == "__main__":
    fix_duplicate_stores()
