"""Extract Charybdis required headers from main.js bootstrap code."""
import re, json, sys
sys.path.insert(0, '.')
from curl_cffi import requests as cffi_requests

session = cffi_requests.Session()
session.get("https://www.solebox.com/en-eu/", impersonate="chrome", timeout=15)

print("=== Fetching main.js ===")
resp = session.get("https://www.solebox.com/main.js", impersonate="chrome", timeout=20)
js = resp.text
print(f"main.js length: {len(js)}")

# Find charybdis/header config blocks
for pattern, label in [
    (r'charybdis[^}]{0,50}headers[^}]{0,200}', 'headers near charybdis'),
    (r'x-request-token[^,;"]{0,100}', 'x-request-token'),
    (r'x-api-key[^,;"]{0,100}', 'x-api-key'),
    (r'x-shop-id[^,;"]{0,100}', 'x-shop-id'),
    (r'Authorization[^,;"]{0,100}', 'Authorization'),
    (r'Bearer [A-Za-z0-9._\-]{10,80}', 'Bearer token'),
    (r'generateToken[^}]{0,200}', 'generateToken'),
    (r'shopKey[^,;"]{0,100}', 'shopKey'),
    (r'apiToken[^,;"]{0,100}', 'apiToken'),
    (r'SCAYLE_[A-Z_]+[^,;"]{0,80}', 'SCAYLE env vars'),
    (r'"token":\s*"[A-Za-z0-9._\-]{10,80}"', 'hardcoded token'),
    (r'country_id[^,;"]{0,100}', 'country_id'),
]:
    matches = re.findall(pattern, js, re.IGNORECASE)
    if matches:
        print(f"\n--- {label} ---")
        for m in matches[:3]:
            print(f"  {m[:200]}")

# Also find the ngsw-state key in the HTML (sometimes contains bootstrap token)
resp2 = session.get("https://www.solebox.com/en-eu/", impersonate="chrome", timeout=15)
html = resp2.text
for pattern, label in [
    (r'ngsw[^"]{0,30}token[^"]{0,80}', 'ngsw token'),
    (r'__SCAYLE[^<]{0,200}', 'SCAYLE state'),
    (r'window\.__[A-Z]{3,}[^<]{0,200}', 'window globals'),
]:
    matches = re.findall(pattern, html, re.IGNORECASE)
    if matches:
        print(f"\n--- HTML: {label} ---")
        for m in matches[:3]:
            print(f"  {m[:200]}")
