"""Test the new referenceKey-based Solebox fetcher."""
import logging
import json
import sys
sys.path.insert(0, '.')

logging.basicConfig(level=logging.DEBUG, format='%(name)s %(levelname)s %(message)s')

from fetchers.solebox import fetch_solebox_product

URL = "https://www.solebox.com/en-eu/p/nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471"

result = fetch_solebox_product(URL)

print("\n=== RESULT ===")
print(f"Name:     {result['name']}")
print(f"Brand:    {result['brand']}")
print(f"Price:    €{result['sale_price']} (was €{result['original_price']})")
print(f"In stock: {result['in_stock']}")
print(f"Images:   {len(result['images'])}")
print(f"Sizes ({len(result['sizes'])}) :")
for s in result['sizes']:
    status = 'IN STOCK' if s['in_stock'] else 'sold out'
    print(f"  {s['label']:15} {status:10} id={s['variant_id']}")
