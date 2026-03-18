"""Temporary probe — test Solebox Scayle API and extract variant structure."""
import re
import json
from curl_cffi import requests as r

PRODUCT_URL = "https://www.solebox.com/en-eu/p/nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471"
PRODUCT_ID = "94471"
SCAYLE_API = "https://api.solebox.com/sni-pl-prd-stor-we-char/v1"
SHOP_ID = "1039"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.solebox.com/",
    "Origin": "https://www.solebox.com",
    "x-shop-id": SHOP_ID,
}

print("=" * 60)
print("1. Testing Scayle API directly")
print("=" * 60)

# Try Scayle product endpoint
for endpoint in [
    f"{SCAYLE_API}/products/{PRODUCT_ID}",
    f"{SCAYLE_API}/products?where[referenceKey]={PRODUCT_ID}&with=variants,attributes",
    f"{SCAYLE_API}/products/{PRODUCT_ID}?with=variants,attributes,images,priceRange",
]:
    resp = r.get(endpoint, headers=HEADERS, impersonate="chrome", timeout=10)
    print(f"\n  {endpoint}")
    print(f"  Status: {resp.status_code}")
    if resp.status_code == 200:
        print(f"  Response: {resp.text[:800]}")
    else:
        print(f"  Response: {resp.text[:200]}")

print("\n" + "=" * 60)
print("2. Extracting variant structure from embedded JS")
print("=" * 60)

page = r.get(PRODUCT_URL, impersonate="chrome", timeout=15)
html = page.text

# Extract the variants array from the big JS block
m = re.search(r'"variants":\[(.*?)\],"attributes"', html, re.DOTALL)
if m:
    # Parse first 2 variants to understand structure
    raw = '[' + m.group(1) + ']'
    try:
        # Find first complete variant object
        variant_match = re.search(r'(\{"id":\d+.*?"available":(true|false).*?\})', raw, re.DOTALL)
        if variant_match:
            v = json.loads(variant_match.group(1))
            print(json.dumps(v, indent=2)[:2000])
    except Exception as e:
        print(f"Parse error: {e}")
        print(raw[:1000])
else:
    # Try simpler extraction - just show the first 1000 chars after "variants":
    m2 = re.search(r'"variants":(\[\{.{0,1500})', html, re.DOTALL)
    if m2:
        print(m2.group(1)[:1500])
    else:
        print("Could not find variants array")
