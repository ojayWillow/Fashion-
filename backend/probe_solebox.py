"""Extract ShopKey value and Authorization header construction from main.js."""
import re, sys
sys.path.insert(0, '.')
from curl_cffi import requests as cffi_requests

session = cffi_requests.Session()
session.get("https://www.solebox.com/en-eu/", impersonate="chrome", timeout=15)

resp = session.get("https://www.solebox.com/main.js", impersonate="chrome", timeout=20)
js = resp.text

# Find context around StoreAvailableShopKey
print("=== StoreAvailableShopKey contexts ===")
for m in re.finditer(r'StoreAvailableShopKey', js):
    pos = m.start()
    print(f"\npos {pos}: ...{js[max(0,pos-120):pos+120]}...")

# Find context around Authorization header assignment
print("\n=== Authorization header construction ===")
for m in re.finditer(r'Authorization', js):
    pos = m.start()
    chunk = js[max(0,pos-80):pos+200]
    if any(k in chunk for k in ['Bearer', 'token', 'key', 'shop', 'header']):
        print(f"\npos {pos}: ...{chunk}...")

# Find SCAYLE_PASSWORD full context
print("\n=== SCAYLE_PASSWORD context ===")
for m in re.finditer(r'SCAYLE_PASSWORD', js):
    pos = m.start()
    print(f"\npos {pos}: ...{js[max(0,pos-50):pos+150]}...")

# Find 'ShopKey' header string (lowercase or camel)
print("\n=== 'shopkey' header string ===")
for m in re.finditer(r'[Ss]hop.{0,3}[Kk]ey', js):
    pos = m.start()
    chunk = js[max(0,pos-60):pos+150]
    if any(k in chunk.lower() for k in ['header', 'bearer', 'token', 'set', 'append']):
        print(f"\npos {pos}: ...{chunk}...")
