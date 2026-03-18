"""Temporary probe script — inspect Solebox inline JS variant/size structure."""
import re
import json
from curl_cffi import requests as r

URL = "https://www.solebox.com/en-eu/p/nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471"

resp = r.get(URL, impersonate="chrome", timeout=15)
html = resp.text

# Find all <script> blocks and look for size/variant data
scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
print(f"Total script blocks: {len(scripts)}")

for i, s in enumerate(scripts):
    if not s.strip():
        continue
    has_size = 'size' in s.lower()
    has_variant = 'variant' in s.lower()
    has_avail = 'availab' in s.lower()
    has_price = '"price"' in s
    if has_size and (has_variant or has_avail):
        print(f"\n=== Script block {i} (size+variant/avail, {len(s)} chars) ===")
        # Try to find the most relevant JSON chunk
        # Look for variations / sizes array
        for pattern, label in [
            (r'"sizes"\s*:\s*(\[.*?\])', 'sizes array'),
            (r'"variants"\s*:\s*(\[.*?\])', 'variants array'),
            (r'"variations"\s*:\s*(\[.*?\])', 'variations array'),
            (r'"availability"\s*:\s*"[^"]+"', 'availability string'),
            (r'"price"\s*:\s*[\d.]+', 'price'),
        ]:
            m = re.search(pattern, s, re.DOTALL)
            if m:
                snippet = m.group(0)[:600]
                print(f"  [{label}]: {snippet}")
        print(f"  --- first 500 chars of block ---")
        print(s.strip()[:500])
