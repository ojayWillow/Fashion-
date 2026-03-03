"""Debug script v3 - try all Shopify endpoints."""
import requests
import json

BASE = "https://en.afew-store.com"
HANDLE = "converse-chuck-70-ox-light-dune-black-egret"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# Get product ID and variant IDs from JSON
print("=== PRODUCT JSON ===")
r = requests.get(f"{BASE}/products/{HANDLE}.json", timeout=15)
data = r.json()["product"]
product_id = data["id"]
print(f"Product ID: {product_id}")
print(f"Images in JSON: {len(data.get('images', []))}")
print(f"Variants: {len(data.get('variants', []))}")
first_available = data['variants'][0].get('available')
print(f"First variant available field: {first_available} (type: {type(first_available).__name__})")

# Test 1: /products/{handle}/variants.json
print()
print("=== TEST 1: variants.json ===")
try:
    r = requests.get(f"{BASE}/products/{HANDLE}/variants.json", timeout=5, headers=HEADERS)
    print(f"Status: {r.status_code}")
    if r.ok:
        vdata = r.json()
        print(f"Keys: {list(vdata.keys()) if isinstance(vdata, dict) else 'list'}")
        if 'variants' in vdata:
            v0 = vdata['variants'][0]
            print(f"First variant available: {v0.get('available')}")
except Exception as e:
    print(f"Error: {e}")

# Test 2: /products/{handle}.js
print()
print("=== TEST 2: product.js ===")
try:
    r = requests.get(f"{BASE}/products/{HANDLE}.js", timeout=5, headers=HEADERS)
    print(f"Status: {r.status_code}")
    if r.ok:
        jdata = r.json()
        print(f"Keys: {list(jdata.keys())}")
        print(f"Images: {len(jdata.get('images', []))}")
        print(f"Media: {len(jdata.get('media', []))}")
        if jdata.get('media'):
            for m in jdata['media'][:3]:
                print(f"  type={m.get('media_type')}, src={m.get('src', m.get('preview_image', {}).get('src', '?'))[:100]}")
        if jdata.get('images'):
            for img in jdata['images'][:5]:
                if isinstance(img, str):
                    print(f"  {img[:120]}")
                elif isinstance(img, dict):
                    print(f"  {img.get('src', '?')[:120]}")
        if jdata.get('variants'):
            print(f"Variants: {len(jdata['variants'])}")
            for v in jdata['variants'][:3]:
                print(f"  id={v.get('id')} title={v.get('option1', v.get('title'))} available={v.get('available')}")
except Exception as e:
    print(f"Error: {e}")

# Test 3: Check a single variant
print()
print("=== TEST 3: single variant JSON ===")
vid = data['variants'][0]['id']
try:
    r = requests.get(f"{BASE}/variants/{vid}.json", timeout=5, headers=HEADERS)
    print(f"Status: {r.status_code}")
    if r.ok:
        vd = r.json()
        # Look for available field anywhere
        flat = json.dumps(vd)
        print(f"Contains 'available': {'available' in flat}")
        print(f"Contains 'inventory': {'inventory' in flat}")
        print(f"Full response ({len(flat)} chars): {flat[:500]}")
except Exception as e:
    print(f"Error: {e}")

# Test 4: Cart add test (check if variant is purchasable)
print()
print("=== TEST 4: cart availability check ===")
for v in data['variants'][:5]:
    vid = v['id']
    title = v.get('option1', '?')
    try:
        r = requests.post(f"{BASE}/cart/add.js",
            json={"id": vid, "quantity": 1},
            headers={**HEADERS, "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
            timeout=5)
        available = r.status_code == 200
        print(f"  Size {title}: {r.status_code} -> {'IN STOCK' if available else 'OUT OF STOCK'}")
    except Exception as e:
        print(f"  Size {title}: Error - {e}")
