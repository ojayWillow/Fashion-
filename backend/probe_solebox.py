"""Find the real product variants block (has stock + sizeMap)."""
import re, json, sys
sys.path.insert(0, '.')
from curl_cffi import requests as cffi_requests

URL = "https://www.solebox.com/en-eu/p/nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471"

session = cffi_requests.Session()
session.get("https://www.solebox.com/en-eu/", impersonate="chrome", timeout=15)
resp = session.get(URL, impersonate="chrome", timeout=20)
html = resp.text
print(f"HTML length: {len(html)}")

# Find ALL 'variants' occurrences (not just '[{'), look for ones with 'sizeMap' nearby
print("\n--- Searching for 'variants' with 'sizeMap' or 'stock' nearby ---")
for m in re.finditer(r'\"variants\":', html):
    pos = m.start()
    chunk = html[pos:pos+300]
    if 'sizeMap' in chunk or ('stock' in chunk and 'quantity' in chunk):
        print(f"\nFound at pos {pos}:")
        print(chunk[:300])
        print("---")
        # Try to parse the array
        arr_start = pos + len('"variants":')
        if html[arr_start] == '[':
            depth = 0
            end = arr_start
            for i, ch in enumerate(html[arr_start:arr_start+2000000], start=arr_start):
                if ch == '[': depth += 1
                elif ch == ']':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            try:
                arr = json.loads(html[arr_start:end])
                print(f"  -> Parsed {len(arr)} variants")
                if arr:
                    v0 = arr[0]
                    print(f"  -> keys: {list(v0.keys())}")
                    print(f"  -> stock: {v0.get('stock')}")
                    print(f"  -> sizeMap: {v0.get('sizeMap')}")
                    print(f"  -> price: {v0.get('price')}")
                    print(f"  -> referenceKey: {v0.get('referenceKey')}")
            except Exception as e:
                print(f"  -> parse error: {e}")
