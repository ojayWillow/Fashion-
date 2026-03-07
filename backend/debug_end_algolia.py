"""Debug script: dump raw Algolia response for an END product.

Usage:
    python debug_end_algolia.py <END_PRODUCT_URL>
    python debug_end_algolia.py  # uses default test URL
"""
import sys
import json
import re
from urllib.parse import urlparse
from curl_cffi import requests as cffi_requests

ALGOLIA_APP_ID = "KO4W2GBINK"
ALGOLIA_API_KEY = "f0cc49399fc8922337e40fb5fc3ab2a4"
ALGOLIA_HEADERS = {
    "X-Algolia-Application-Id": ALGOLIA_APP_ID,
    "X-Algolia-API-Key": ALGOLIA_API_KEY,
    "Content-Type": "application/json",
    "Origin": "https://www.endclothing.com",
    "Referer": "https://www.endclothing.com/",
}

INDICES = [
    "Catalog_products_v3_gb_products",
    "Catalog_products_v3_eu_products",
    "Catalog_products_v3_row_products",
    "Catalog_products_v3_us_products",
]


def extract_sku(url: str):
    slug = urlparse(url).path.rstrip("/").split("/")[-1].replace(".html", "")
    m = re.search(r"([a-zA-Z]{1,5}\d{3,5}-\d{2,4})$", slug)
    if m:
        return m.group(1).upper()
    m = re.search(r"([a-zA-Z]{1,5}\d{3,5}[-_]\d{2,4})", slug)
    if m:
        return m.group(1).upper().replace("_", "-")
    return slug.upper()


def extract_product_name(url: str):
    slug = urlparse(url).path.rstrip("/").split("/")[-1].replace(".html", "")
    slug = re.sub(r"-[a-zA-Z]{1,5}\d{3,5}-\d{2,4}$", "", slug)
    return slug.replace("-", " ")


def query_algolia(index: str, query: str, hits_per_page: int = 5):
    url = f"https://search1web.endclothing.com/1/indexes/{index}/query"
    resp = cffi_requests.post(
        url,
        headers=ALGOLIA_HEADERS,
        json={"query": query, "hitsPerPage": hits_per_page},
        impersonate="chrome",
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def dump_hit(hit):
    print(f"\nProduct: {hit.get('name')}")
    print(f"SKU: {hit.get('sku')}")
    print(f"Brand: {hit.get('brand')}")
    print(f"Gender: {hit.get('gender')}")
    print(f"Stock total: {hit.get('stock')}")

    print(f"\n{'='*40}")
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

    print(f"\n{'='*40}")
    print("FIELDS WITH 'size', 'stock', 'variant', 'avail'")
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


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.endclothing.com/eu/air-jordan-11-retro-ra-sneaker-fv1565-101.html"
    sku = extract_sku(url)
    product_name = extract_product_name(url)

    print(f"\n{'='*70}")
    print(f"URL: {url}")
    print(f"SKU: {sku}")
    print(f"Name search: {product_name}")
    print(f"{'='*70}")

    queries = [sku, product_name, sku.lower(), sku.replace("-", " ")]

    for index in INDICES:
        for query in queries:
            print(f"\n>>> index={index}, query='{query}'")
            try:
                result = query_algolia(index, query)
                hits = result.get("hits", [])
                print(f"    Hits: {len(hits)}")

                if hits:
                    for i, h in enumerate(hits):
                        print(f"    [{i}] {h.get('name')} | SKU: {h.get('sku')} | Stock: {h.get('stock')}")

                    hit = None
                    for h in hits:
                        if h.get("sku", "").upper() == sku:
                            hit = h
                            break
                    if not hit:
                        hit = hits[0]
                        print(f"    [!] No exact SKU match, using first hit")

                    dump_hit(hit)
                    return

            except Exception as e:
                print(f"    Error: {e}")

    print("\n[!] NO HITS FOUND in any index with any query")


if __name__ == "__main__":
    main()
