"""Find the correct product variants block in Solebox JS blob."""
import re
import json
from curl_cffi import requests as r

URL = "https://www.solebox.com/en-eu/p/nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471"
IMAGE_ID = "02549461"  # from JSON-LD image URL

resp = r.get(URL, impersonate="chrome", timeout=15)
html = resp.text

# Strategy: find ALL variants blocks, check which one has referenceKey starting with IMAGE_ID
all_var_positions = [m.start() for m in re.finditer(r'"variants":\[\{"id":', html)]
print(f"Found {len(all_var_positions)} 'variants' blocks")

for i, pos in enumerate(all_var_positions):
    chunk = html[pos:pos+300]
    print(f"\n--- Block {i} at {pos} ---")
    print(chunk[:300])
    if IMAGE_ID in chunk:
        print("  ^^^ CONTAINS OUR IMAGE ID ^^^")

# Also: try finding by the specific referenceKey format
# referenceKey for our product should contain 02549461
ref_search = f'"referenceKey":"0254946'
idx = html.find(ref_search)
print(f"\n\nreferenceKey search '{ref_search}': at {idx}")
if idx != -1:
    print(html[max(0,idx-200):idx+500])
