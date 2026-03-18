"""Find the async API routes Solebox uses for product/variant data."""
import re, json, sys
sys.path.insert(0, '.')
from curl_cffi import requests as cffi_requests

session = cffi_requests.Session()
session.get("https://www.solebox.com/en-eu/", impersonate="chrome", timeout=15)

# 1. Fetch ngsw.json - this lists all URLs the service worker caches
print("=== ngsw.json ===")
resp = session.get("https://www.solebox.com/en-eu/ngsw.json", impersonate="chrome", timeout=15)
ngsw = resp.json()
# Print all URL groups
for group in ngsw.get('dataGroups', []):
    print(f"\nData group: {group.get('name')} | strategy: {group.get('cacheConfig', {}).get('strategy')}")
    for url in group.get('urls', [])[:5]:
        print(f"  {url}")
for group in ngsw.get('assetGroups', []):
    print(f"\nAsset group: {group.get('name')}")
    for url in list(group.get('urls', []))[:3]:
        print(f"  {url}")

# 2. Fetch the product page and find any XHR/fetch URLs in the JS
print("\n=== Scanning page JS for API endpoint patterns ===")
resp2 = session.get(
    "https://www.solebox.com/en-eu/p/nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471",
    impersonate="chrome", timeout=20
)
html = resp2.text

# Find all script src URLs
scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html)
print(f"Script tags: {len(scripts)}")
for s in scripts[:10]:
    print(f"  {s}")

# Look for charybdis/backbone/api patterns directly in HTML
for pattern in [
    r'charybdis[^"\s]{5,80}',
    r'backbone-api[^"\s]{5,80}',
    r'/v1/[^"\s]{5,60}',
    r'api\.solebox[^"\s]{5,60}',
]:
    matches = re.findall(pattern, html)
    if matches:
        print(f"\nPattern '{pattern[:30]}': {matches[:5]}")
