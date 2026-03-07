"""Debug script: dump raw Algolia response for an END product.

Usage:
    python debug_end_algolia.py <END_PRODUCT_URL>
    python debug_end_algolia.py  # uses default test URL

Prints all size-related fields so we can build a correct
label -> stock mapping instead of guessing offsets.
"""
import sys
import json
import re
from urllib.parse import urlparse
from curl_cffi import requests as cffi_requests

ALGOLIA_URL = (
    "https://search1web.endclothing.com"
    "/1/indexes/Catalog_products_v3_gb_products/query"
)
ALGOLIA_HEADERS = {
    "X-Algolia-Application-Id": "KO4W2GBINK",
    "X-Algolia-API-Key": "f0cc49399fc8922337e40fb5fc3ab2a4",
    "Content-Type": "application/json",
    "Origin": "https://www.endclothing.com",
    "Referer": "https://www.endclothing.com/",
}


def extract_sku(url: str):
    slug = urlparse(url).path.rstrip("/").split("/")[-1].replace(".html", "")
    m = re.search(r"([a-zA-Z]{1,5}\d{3,5}-\d{2,4})$", slug)
    if m:
        return m.group(1).upper()
    m = re.search(r"([a-zA-Z]{1,5}\d{3,5}[-_]\d{2,4})", slug)
    if m:
        return m.group(1).upper().replace("_", "-")
    return slug.upper()


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.endclothing.com/eu/air-jordan-11-retro-ra-sneaker-fv1565-101.html"
    sku = extract_sku(url)
    print(f"\n{'='*70}")
    print(f"URL: {url}")
    print(f"SKU: {sku}")
    print(f"{'='*70}\n")

    resp = cffi_requests.post(
        ALGOLIA_URL,
        headers=ALGOLIA_HEADERS,
        json={"query": sku, "hitsPerPage": 5},
        impersonate="chrome",
        timeout=15,
    )
    resp.raise_for_status()
    hits = resp.json().get("hits", [])

    if not hits:
        print("NO HITS FOUND")
        return

    # Find exact match
    hit = None
    for h in hits:
        if h.get("sku", "").upper() == sku:
            hit = h
            break
    if not hit:
        hit = hits[0]
        print(f"[!] No exact SKU match, using first hit: {hit.get('sku')}")

    print(f"Product: {hit.get('name')}")
    print(f"SKU: {hit.get('sku')}")
    print(f"Brand: {hit.get('brand')}")
    print(f"Gender: {hit.get('gender')}")
    print(f"Stock total: {hit.get('stock')}")
    print()

    # === SIZE-RELATED FIELDS ===
    print("=" * 40)
    print("SIZE-RELATED FIELDS")
    print("=" * 40)

    size_fields = [
        'size', 'footwear_size', 'footwear_size_label',
        'clothing_size', 'clothing_size_label',
        'size_label', 'size_stock', 'size_availability',
        'variants', 'children', 'configurable_children',
        'sku_stock', 'sku_availability',
    ]

    for field in size_fields:
        val = hit.get(field)
        if val is not None:
            print(f"\n--- {field} ---")
            if isinstance(val, dict) and len(val) > 20:
                print(f"  (dict with {len(val)} entries, showing first 30)")
                for i, (k, v) in enumerate(sorted(val.items())):
                    if i >= 30:
                        print(f"  ... ({len(val) - 30} more)")
                        break
                    print(f"  {k}: {v}")
            else:
                print(f"  {json.dumps(val, indent=2)}")

    # === ALL FIELDS WITH 'size' or 'stock' or 'variant' in name ===
    print(f"\n{'='*40}")
    print("ALL FIELDS CONTAINING 'size', 'stock', 'variant', 'avail'")
    print("=" * 40)

    for key in sorted(hit.keys()):
        kl = key.lower()
        if any(w in kl for w in ['size', 'stock', 'variant', 'avail', 'qty', 'quantity', 'inventory']):
            if key not in size_fields:
                val = hit[key]
                print(f"\n--- {key} ---")
                if isinstance(val, (dict, list)) and len(str(val)) > 200:
                    print(f"  {json.dumps(val, indent=2)[:500]}...")
                else:
                    print(f"  {json.dumps(val, indent=2)}")

    # === DUMP ALL KEYS (for discovery) ===
    print(f"\n{'='*40}")
    print(f"ALL {len(hit)} KEYS IN HIT:")
    print("=" * 40)
    for key in sorted(hit.keys()):
        val = hit[key]
        type_name = type(val).__name__
        if isinstance(val, (list, dict)):
            print(f"  {key}: {type_name}[{len(val)}]")
        elif isinstance(val, str) and len(val) > 80:
            print(f"  {key}: str({len(val)}) = {val[:80]}...")
        else:
            print(f"  {key}: {val}")


if __name__ == "__main__":
    main()
