"""Probe: dump the raw variant+availability chunk from Solebox embedded JS."""
import re
from curl_cffi import requests as r

URL = "https://www.solebox.com/en-eu/p/nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471"

resp = r.get(URL, impersonate="chrome", timeout=15)
html = resp.text

# Find the position of the first 'variants' occurrence and dump 3000 chars around it
idx = html.find('"variants"')
if idx == -1:
    print("'variants' not found in page")
else:
    print(f"Found 'variants' at position {idx}")
    chunk = html[idx:idx+3000]
    print(chunk)

# Also find 'available' near a size label
idx2 = html.find('"available"')
if idx2 != -1:
    print("\n\n--- 'available' context ---")
    print(html[max(0, idx2-200):idx2+500])
