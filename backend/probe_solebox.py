"""Temporary probe script — inspect Solebox page structure."""
import re
import json
from curl_cffi import requests as r

URL = "https://www.solebox.com/en-eu/p/nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471"

resp = r.get(URL, impersonate="chrome", timeout=15)
print(f"STATUS: {resp.status_code}")
print(f"Content-Length: {len(resp.text)}")

# Extract all JSON-LD blocks
matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', resp.text, re.DOTALL)
print(f"\nFound {len(matches)} JSON-LD block(s)")

for i, m in enumerate(matches):
    try:
        data = json.loads(m.strip())
        print(f"\n--- JSON-LD block {i} (@type={data.get('@type', '?')}) ---")
        print(json.dumps(data, indent=2)[:3000])
    except Exception as e:
        print(f"block {i}: parse error - {e}")
        print(m[:300])

# Also check for any inline JS with price/size data
print("\n--- Checking inline JS patterns ---")
for pattern, label in [
    (r'"price"\s*:\s*["\d]', "price"),
    (r'"sizes?"\s*:', "sizes"),
    (r'"variants?"\s*:', "variants"),
    (r'"availability"', "availability"),
    (r'"sku"\s*:', "sku"),
    (r'"offers"\s*:', "offers"),
]:
    found = re.search(pattern, resp.text)
    print(f"  {label}: {'FOUND' if found else 'not found'}")
