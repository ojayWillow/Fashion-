"""Diagnose referenceKey anchor and variants extraction."""
import re, json, time, sys
sys.path.insert(0, '.')
from curl_cffi import requests as cffi_requests
from fetchers.solebox import _extract_image_id, _extract_variants_by_reference_key, _extract_variants_fallback

URL = "https://www.solebox.com/en-eu/p/nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471"

print("Fetching page...")
session = cffi_requests.Session()
session.get("https://www.solebox.com/en-eu/", impersonate="chrome", timeout=15)
resp = session.get(URL, impersonate="chrome", timeout=20)
html = resp.text
print(f"HTML length: {len(html)}")

# Step 1: get image_id from JSON-LD
json_ld = None
for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL):
    try:
        d = json.loads(m.group(1).strip())
        if d.get('@type') == 'Product':
            json_ld = d
            break
    except: continue

image_id = _extract_image_id(json_ld) if json_ld else None
print(f"Image ID: {image_id}")

# Step 2: check referenceKey anchor exists
if image_id:
    anchor = f'"referenceKey":"{image_id}'
    idx = html.find(anchor)
    print(f"referenceKey anchor at position: {idx}")
    if idx != -1:
        print(f"Context: {html[idx:idx+80]}")

# Step 3: time the extraction
print("\nExtracting variants (primary)...")
t = time.time()
variants = _extract_variants_by_reference_key(html, image_id) if image_id else None
print(f"Primary extraction: {time.time()-t:.2f}s -> {len(variants) if variants else None} variants")

if variants:
    v = variants[0]
    print(f"First variant keys: {list(v.keys())[:10]}")
    print(f"referenceKey: {v.get('referenceKey')}")
    print(f"stock: {v.get('stock')}")
    print(f"sizeMap: {v.get('sizeMap')}")
else:
    print("\nTrying fallback...")
    t = time.time()
    variants = _extract_variants_fallback(html)
    print(f"Fallback: {time.time()-t:.2f}s -> {len(variants) if variants else None} variants")
    if variants:
        print(f"First variant keys: {list(variants[0].keys())[:10]}")
