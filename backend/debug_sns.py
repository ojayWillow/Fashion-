"""Debug script: dump raw SNS .json + .js variant data for a product.

Usage:
    python debug_sns.py <SNS_PRODUCT_URL>
    python debug_sns.py  # uses default test URL
"""
import sys
import json
import logging
from fetchers._sns_worker import fetch_sns_page, _extract_handle_from_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.sneakersnstuff.com/en-eu/products/adidas-adistar-hrmy-jr4369"
    handle = _extract_handle_from_url(url)

    print(f"\n{'='*70}")
    print(f"URL: {url}")
    print(f"Handle: {handle}")
    print(f"{'='*70}")

    raw = fetch_sns_page(url)

    json_data = raw["json_data"]
    js_data = raw["js_data"]

    # === .json variants ===
    json_variants = json_data.get("variants", [])
    print(f"\n{'='*40}")
    print(f".json: {len(json_variants)} variants")
    print("=" * 40)
    for v in json_variants:
        print(
            f"  id={v['id']} | option1={v.get('option1','?'):>6} "
            f"| available={str(v.get('available', '?')):>5} "
            f"| price={v.get('price','?')} "
            f"| sku={v.get('sku','?')}"
        )

    # === .js variants ===
    if js_data:
        js_variants = js_data.get("variants", [])
        print(f"\n{'='*40}")
        print(f".js: {len(js_variants)} variants")
        print("=" * 40)
        for v in js_variants:
            print(
                f"  id={v['id']} | option1={v.get('option1','?'):>6} "
                f"| available={str(v.get('available', '?')):>5} "
                f"| title={v.get('title','?')}"
            )

        # === Compare ===
        print(f"\n{'='*40}")
        print("COMPARISON: .json vs .js availability")
        print("=" * 40)
        js_avail = {str(v["id"]): v.get("available", False) for v in js_variants}

        mismatches = 0
        for v in json_variants:
            vid = str(v["id"])
            json_avail = v.get("available", "?")
            js_a = js_avail.get(vid, "MISSING")
            marker = " " if json_avail == js_a else " <-- MISMATCH"
            if json_avail != js_a:
                mismatches += 1
            print(
                f"  {v.get('option1','?'):>6} | .json={str(json_avail):>5} | .js={str(js_a):>5}{marker}"
            )
        print(f"\nMismatches: {mismatches}")

        json_in_stock = sum(1 for v in json_variants if v.get("available"))
        js_in_stock = sum(1 for v in js_variants if v.get("available"))
        print(f".json in stock: {json_in_stock}/{len(json_variants)}")
        print(f".js in stock:   {js_in_stock}/{len(js_variants)}")
    else:
        print("\n[!] .js endpoint returned no data")

    # === SNS website display (EU sizes shown) ===
    print(f"\n{'='*40}")
    print("SIZE CONVERSION PREVIEW (US -> EU)")
    print("=" * 40)
    from utils.size_converter import convert_to_eu, detect_gender_from_tags
    from utils.category_detector import detect_category

    tags = json_data.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    gender = detect_gender_from_tags(tags=tags, name=json_data.get("title", ""))
    product_type = json_data.get("product_type", "")
    category = detect_category(json_data.get("title", ""), product_type=product_type, tags=tags)

    print(f"Gender: {gender}, Category: {category}")
    print(f"Tags: {tags[:15]}{'...' if len(tags) > 15 else ''}")

    js_avail_map = {}
    if js_data:
        js_avail_map = {str(v["id"]): v.get("available", False) for v in js_data.get("variants", [])}

    for v in json_variants:
        vid = str(v["id"])
        raw_label = v.get("option1", v.get("title", "?"))
        eu = convert_to_eu(raw_label, category, gender=gender)
        avail = js_avail_map.get(vid, v.get("available", "?"))
        stock_str = "IN STOCK" if avail else "SOLD OUT"
        print(f"  US {raw_label:>5} -> EU {eu:>5} | {stock_str}")


if __name__ == "__main__":
    main()
