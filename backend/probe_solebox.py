"""Find the correct product object by productId in the Solebox JS blob."""
import re
from curl_cffi import requests as r

URL = "https://www.solebox.com/en-eu/p/nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471"
PRODUCT_ID = 94471

resp = r.get(URL, impersonate="chrome", timeout=15)
html = resp.text

# Search for the productId anchor
anchor = f'"productId":{PRODUCT_ID}'
idx = html.find(anchor)
print(f"productId anchor '{anchor}' at index: {idx}")

if idx != -1:
    # Show 500 chars before to find the opening brace
    print("\n--- 300 chars before productId ---")
    print(html[max(0,idx-300):idx])
    print("\n--- 500 chars after productId ---")
    print(html[idx:idx+500])

# Also try: how many times does this productId appear?
count = html.count(anchor)
print(f"\n'{anchor}' appears {count} times")

# Try alternate format
for alt in [f'"id":{PRODUCT_ID},', f'"id":{PRODUCT_ID}"', f'productId":{PRODUCT_ID}']:
    c = html.count(alt)
    if c:
        i = html.find(alt)
        print(f"\n'{alt}' appears {c} times, first at {i}:")
        print(html[max(0,i-100):i+300])
