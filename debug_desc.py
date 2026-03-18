from curl_cffi import requests as cffi_requests
import re

URL = "https://www.solebox.com/en-eu/p/47-nhl-anaheim-ducks-clean-up-cap-black-85706"

r = cffi_requests.get(
    URL,
    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"},
    impersonate="chrome",
    timeout=20,
)
html = r.text

# Search for the actual product text — cap/hat keywords
keywords = ['Anaheim', 'NHL', 'structured', 'cotton', 'adjustable', 'curved', 'embroid', 'one size', 'unstructured']
print("=== KEYWORD CONTEXT (300 chars around each hit) ===")
for kw in keywords:
    for m in re.finditer(re.escape(kw), html, re.IGNORECASE):
        start = max(0, m.start() - 100)
        end = min(len(html), m.end() + 200)
        snippet = html[start:end].replace('\n', ' ').replace('\r', '')
        print(f"[{kw}] ...{snippet}...")
        print("---")

# Also dump 500 chars around 'detail' or 'product-info'
print("\n=== DETAIL/INFO SECTIONS ===")
for kw in ['product-detail', 'product-info', 'product-description', 'pdp-description', 'accordion']:
    for m in re.finditer(kw, html, re.IGNORECASE):
        start = max(0, m.start() - 50)
        end = min(len(html), m.end() + 400)
        snippet = html[start:end].replace('\n', ' ')
        print(f"[{kw}] {snippet[:500]}")
        print("---")
        break  # just first hit per keyword
