"""Diagnose why product blob extraction fails — inspect surroundings of 'variants'."""
import re
from curl_cffi import requests as r

URL = "https://www.solebox.com/en-eu/p/nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471"
resp = r.get(URL, impersonate="chrome", timeout=15)
html = resp.text

idx = html.find('"variants"')
print(f"'variants' at index: {idx}")

# Show 300 chars BEFORE variants to understand parent structure
print("\n--- 300 chars before 'variants' ---")
print(repr(html[max(0, idx-300):idx]))

# Show 200 chars after variants key
print("\n--- 200 chars after 'variants' key ---")
print(repr(html[idx:idx+200]))

# How many times does 'product' key appear near variants?
print("\n--- searching for 'product' key before variants ---")
search_back = html[max(0, idx-5000):idx]
product_positions = [m.start() for m in re.finditer(r'"product":', search_back)]
print(f"Found 'product': {len(product_positions)} times in 5000 chars before 'variants'")
if product_positions:
    last = product_positions[-1]
    print(f"Last 'product' at offset {last} from search start")
    print(repr(search_back[last:last+100]))
