"""Test the real Solebox API endpoints (double /v1/v1/ path)."""
import json, sys
sys.path.insert(0, '.')
from curl_cffi import requests as cffi_requests

BASE = "https://api.solebox.com/sni-pl-prd-stor-we-char/v1"

# Warm session to get Cloudflare cookies
session = cffi_requests.Session()
session.get("https://www.solebox.com/en-eu/", impersonate="chrome", timeout=15)

h = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.solebox.com/",
    "x-shop-id": "1039",
    "x-locale": "en_EU",
    "x-country": "GB",
}

tests = [
    "/v1/base",
    "/v1/products/94471",
    "/v1/products/94471?with=variants,stock,attributes,images,priceRange",
    "/v1/pages/productDetails?pageType=productDetailPage&slug=nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471",
    "/v1/products?where[slug]=nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471&with=variants,stock",
]

for path in tests:
    url = BASE + path
    resp = session.get(url, headers=h, impersonate="chrome", timeout=10)
    print(f"\n{resp.status_code} | {path}")
    text = resp.text[:600]
    try:
        obj = json.loads(resp.text)
        print(json.dumps(obj, indent=2)[:600])
    except:
        print(text)
