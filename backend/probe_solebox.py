"""Find actual referenceKey format and the correct variants block."""
import re, json, sys
sys.path.insert(0, '.')
from curl_cffi import requests as cffi_requests

URL = "https://www.solebox.com/en-eu/p/nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471"

session = cffi_requests.Session()
session.get("https://www.solebox.com/en-eu/", impersonate="chrome", timeout=15)
resp = session.get(URL, impersonate="chrome", timeout=20)
html = resp.text
print(f"HTML length: {len(html)}")

# 1. Find ALL referenceKey values in the HTML
print("\n--- All referenceKey values ---")
for m in re.finditer(r'referenceKey[\\"]+:?[\\"]+([\w]+)', html):
    print(f"  pos {m.start()}: {m.group(0)[:60]}")

# 2. Show raw context around image ID 02549461
print("\n--- Raw context around '02549461' (first 3 occurrences) ---")
count = 0
start = 0
while count < 3:
    idx = html.find('02549461', start)
    if idx == -1:
        break
    print(f"  pos {idx}: ...{html[max(0,idx-30):idx+60]}...")
    start = idx + 1
    count += 1

# 3. Find all 'variants':[{ blocks and show how many items each has
print("\n--- All variants blocks (count of items) ---")
for i, m in enumerate(re.finditer(r'\"variants\":\[\{', html)):
    pos = m.start() + len('"variants":')
    depth = 0
    end = pos
    for j, ch in enumerate(html[pos:pos+500000], start=pos):
        if ch == '[': depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                end = j + 1
                break
    try:
        arr = json.loads(html[pos:end])
        first_keys = list(arr[0].keys())[:6] if arr else []
        ref = arr[0].get('referenceKey', 'N/A') if arr else 'N/A'
        print(f"  Block {i} at {m.start()}: {len(arr)} items | keys: {first_keys} | referenceKey: {ref}")
    except Exception as e:
        print(f"  Block {i} at {m.start()}: parse error: {e}")
    if i > 10:
        print("  (stopping at 10)")
        break
