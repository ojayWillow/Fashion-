"""Debug script to see exactly what AFEW returns."""
import requests
import json

url = "https://en.afew-store.com/products/converse-chuck-70-ox-light-dune-black-egret.json"
r = requests.get(url, timeout=15)
data = r.json()["product"]

print("=== IMAGES ===")
images = data.get("images", [])
print(f"Count: {len(images)}")
for img in images:
    print(f"  {img['src'][:120]}")

print()
print("=== FIRST 3 VARIANTS ===")
for v in data.get("variants", [])[:3]:
    print(json.dumps({
        "id": v["id"],
        "title": v.get("option1"),
        "available": v.get("available"),
        "price": v.get("price"),
        "compare_at_price": v.get("compare_at_price"),
    }, indent=2))

print()
print("=== VARIANT AVAILABILITY CHECK ===")
first_vid = str(data["variants"][0]["id"])
try:
    vr = requests.get(f"https://en.afew-store.com/variants/{first_vid}.json", timeout=5)
    print(f"Variant endpoint status: {vr.status_code}")
    if vr.ok:
        print(json.dumps(vr.json(), indent=2)[:500])
    else:
        print(f"Response: {vr.text[:300]}")
except Exception as e:
    print(f"Error: {e}")

print()
print("=== PAGE HTML TEST ===")
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
r2 = requests.get("https://en.afew-store.com/products/converse-chuck-70-ox-light-dune-black-egret", timeout=15, headers=headers)
print(f"Status: {r2.status_code}")
print(f"Length: {len(r2.text)}")
print(f"Has cdn.shopify: {'cdn.shopify.com' in r2.text}")

import re
cdn_matches = re.findall(r'(?:https?:)?//cdn\.shopify\.com/s/files/[^"\s)}>]+\.(?:jpg|jpeg|png|webp)', r2.text, re.IGNORECASE)
print(f"CDN image URLs found: {len(cdn_matches)}")
product_imgs = [u for u in cdn_matches if '/products/' in u]
print(f"Product image URLs: {len(product_imgs)}")
for u in product_imgs[:10]:
    print(f"  {u[:120]}")

print()
print(f"First 500 chars of HTML:")
print(r2.text[:500])
