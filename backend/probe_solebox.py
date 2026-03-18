"""Temporary probe — test the new Solebox fetcher end-to-end."""
import json
import logging
logging.basicConfig(level=logging.INFO)

from fetchers.solebox import fetch_solebox_product

URL = "https://www.solebox.com/en-eu/p/nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471"

try:
    data = fetch_solebox_product(URL)
    print(f"Name:          {data['name']}")
    print(f"Brand:         {data['brand']}")
    print(f"Category:      {data['category']}")
    print(f"Gender:        {data['gender']}")
    print(f"Color:         {data['colorway']}")
    print(f"Sale price:    €{data['sale_price']}")
    print(f"Orig price:    €{data['original_price']}")
    print(f"Discount:      {data['discount_pct']}%")
    print(f"In stock:      {data['in_stock']}")
    print(f"Images:        {len(data['images'])}")
    print(f"\nSizes ({len(data['sizes'])} total):")
    for s in data['sizes']:
        stock = 'IN STOCK' if s['in_stock'] else 'sold out'
        print(f"  {s['label']:<12} {stock}")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback; traceback.print_exc()
