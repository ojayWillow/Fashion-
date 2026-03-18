"""Locate the correct product's variants block using image public_id as anchor."""
import re
import json
from curl_cffi import requests as r

URL = "https://www.solebox.com/en-eu/p/nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471"
# From JSON-LD image: https://asset.solebox.com/images/f_auto,q_100/02549461_1/...
IMAGE_ID = "02549461"

resp = r.get(URL, impersonate="chrome", timeout=15)
html = resp.text

# Find the image public_id anchor closest to a 'variants' key
print(f"Searching for image anchor: {IMAGE_ID}")
positions = [m.start() for m in re.finditer(re.escape(IMAGE_ID), html)]
print(f"Found {len(positions)} occurrences")

for pos in positions[:5]:
    # Look for 'variants' within 50000 chars after this anchor
    chunk = html[pos:pos+50000]
    var_idx = chunk.find('"variants"')
    print(f"\n  Occurrence at {pos}: 'variants' found {var_idx} chars ahead")
    if 0 < var_idx < 50000:
        print(f"  Context around anchor: {html[pos-50:pos+100]}")
        # Show the variants array start
        var_start = pos + var_idx
        print(f"  Variants at {var_start}: {html[var_start:var_start+400]}")
        break
