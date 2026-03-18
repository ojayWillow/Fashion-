from curl_cffi import requests as cffi_requests
import re
from urllib.parse import unquote

URL = "https://www.solebox.com/en-eu/p/47-nhl-anaheim-ducks-clean-up-cap-black-85706"

r = cffi_requests.get(
    URL,
    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"},
    impersonate="chrome",
    timeout=20,
)
html = r.text
print(f"Page size: {len(html)} chars")

pattern = re.compile(r'https://[^"\s\\]+\.(?:jpg|jpeg|png|webp)[^"\s\\]*', re.IGNORECASE)
all_urls = pattern.findall(html)

seen = set()
unique = []
for u in all_urls:
    base = u.split("?")[0]
    if base not in seen:
        seen.add(base)
        unique.append(u)

print(f"\n--- {len(unique)} unique image URLs ---")
for u in unique:
    print(u[:150])

# Also check what JSON-LD contains
import json
for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL):
    try:
        data = json.loads(m.group(1).strip())
        if data.get("@type") == "Product":
            print("\n--- JSON-LD image field ---")
            print(json.dumps(data.get("image"), indent=2))
            print("\n--- JSON-LD description ---")
            print(data.get("description", "(none)"))
    except:
        pass
