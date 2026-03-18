from curl_cffi import requests as cffi_requests
import re
import json

URL = "https://www.solebox.com/en-eu/p/47-nhl-anaheim-ducks-clean-up-cap-black-85706"

r = cffi_requests.get(
    URL,
    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"},
    impersonate="chrome",
    timeout=20,
)
html = r.text
print(f"Page size: {len(html)} chars")

# --- Search for description text ---
print("\n=== DESCRIPTION CANDIDATES ===")
for m in re.finditer(r'["\']description["\']\s*:\s*["\']([^\'"]{20,500})', html):
    print(repr(m.group(1)[:200]))
    print("---")

# Also check all JSON-LD blocks
print("\n=== ALL JSON-LD BLOCKS ===")
for i, m in enumerate(re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)):
    try:
        data = json.loads(m.group(1).strip())
        print(f"Block {i}: @type={data.get('@type')}")
        if 'description' in data:
            print(f"  description: {repr(data['description'][:300])}")
        if data.get('@type') == 'Product':
            print(json.dumps(data, indent=2)[:800])
    except Exception as e:
        print(f"Block {i}: parse error {e}")
    print("---")

# Check for shortDescription or longDescription keys
print("\n=== SHORT/LONG DESCRIPTION ===")
for key in ['shortDescription', 'longDescription', 'productDescription', 'body_html']:
    matches = re.findall(rf'["\x27]{key}["\x27]\s*:\s*["\x27]([^"\x27]{{10,}})', html)
    if matches:
        print(f"{key}: {repr(matches[0][:300])}")
    else:
        print(f"{key}: not found")
