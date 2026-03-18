"""Extract SCAYLE creds + OAuth endpoint, then get Bearer token and hit products API."""
import re, json, sys
sys.path.insert(0, '.')
from curl_cffi import requests as cffi_requests

session = cffi_requests.Session()
session.get("https://www.solebox.com/en-eu/", impersonate="chrome", timeout=15)
js = session.get("https://www.solebox.com/main.js", impersonate="chrome", timeout=20).text
print(f"main.js length: {len(js)}")

for label, pattern in [
    ("SCAYLE_NAME",     r'SCAYLE_NAME["\s:=,}]{0,10}["\']([^"\'`\s]{2,80})'),
    ("SCAYLE_PASSWORD", r'SCAYLE_PASSWORD["\s:=,}]{0,10}["\']([^"\'`\s]{2,80})'),
    ("client_id",       r'client_id["\s:=,}]{0,10}["\']([^"\'`\s]{2,80})'),
    ("client_secret",   r'client_secret["\s:=,}]{0,10}["\']([^"\'`\s]{2,80})'),
    ("oauth_token_url", r'(https?://[^\s"\']{5,80}(?:oauth|token)[^\s"\']{0,40})'),
    ("scayleShopId",    r'scayleShopId["\s:=,}]{0,10}["\']?(\w+)'),
]:
    hits = re.findall(pattern, js, re.IGNORECASE)
    if hits:
        print(f"\n{label}: {hits[:5]}")

# Check if the ngsw-cached product page HTML contains the full API response
html = session.get(
    "https://www.solebox.com/en-eu/p/nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471",
    impersonate="chrome", timeout=20
).text

idx = html.find('products/94471')
if idx > 0:
    print(f"\nContext around 'products/94471' in HTML (pos {idx}):")
    print(html[idx:idx+800])
else:
    print("\n'products/94471' not found in HTML")
