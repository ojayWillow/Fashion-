"""Decode full product/variants/stock from ngsw cache in HTML."""
import re, json, sys
from urllib.parse import unquote
sys.path.insert(0, '.')
from curl_cffi import requests as cffi_requests

session = cffi_requests.Session()
session.get("https://www.solebox.com/en-eu/", impersonate="chrome", timeout=15)
html = session.get(
    "https://www.solebox.com/en-eu/p/nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471",
    impersonate="chrome", timeout=20
).text

pattern = r'api\.solebox\.com[^"\s]{20,}'
matches = re.findall(pattern, html)
print(f"Found {len(matches)} cached API blobs")

for m in matches:
    decoded = unquote(m)
    # get URL slug
    url_part = decoded.split('%22')[0].split('"')[0]
    print(f"\n=== {url_part[:100]} ===")
    # find body
    body_idx = decoded.find('"body":')
    if body_idx < 0:
        print("  no body")
        continue
    body_str = decoded[body_idx + 7:]
    # balance braces
    depth = 0
    end = 0
    for i, ch in enumerate(body_str):
        if ch == '{': depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    try:
        body = json.loads(body_str[:end])
        # Print key fields
        print(f"  id: {body.get('id')} | referenceKey: {body.get('referenceKey')} | isSoldOut: {body.get('isSoldOut')}")
        variants = body.get('variants', [])
        print(f"  variants count: {len(variants)}")
        for v in variants[:3]:
            print(f"    variant {v.get('referenceKey')}: stock={v.get('stock')} sizeMap={v.get('sizeMap')} price={v.get('price')}")
        # also check if stock is top-level
        if 'stock' in body:
            print(f"  top-level stock: {body['stock']}")
        print(f"  all keys: {list(body.keys())}")
    except Exception as e:
        print(f"  parse error: {e} | raw: {body_str[:200]}")
