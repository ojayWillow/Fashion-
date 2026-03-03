"""Fetch product data from Shopify stores (e.g., AFEW Store).

Usage:
    from fetchers.shopify import fetch_shopify_product
    product_data = fetch_shopify_product("https://en.afew-store.com/products/nike-air-max-1-sc")
"""
import re
import json as _json
import requests
from urllib.parse import urlparse

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})


def fetch_shopify_product(product_url: str) -> dict:
    parsed = urlparse(product_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    handle = parsed.path.rstrip("/").split("/")[-1]
    if not handle:
        raise ValueError(f"Could not extract product handle from URL: {product_url}")

    # Step 1: Fetch product data from .js endpoint (has real availability)
    js_url = f"{base_url}/products/{handle}.js"
    resp = SESSION.get(js_url, timeout=15)
    resp.raise_for_status()
    js_data = resp.json()

    # Step 2: Also fetch .json for richer data (description, tags, etc.)
    json_url = f"{base_url}/products/{handle}.json"
    resp2 = SESSION.get(json_url, timeout=15)
    resp2.raise_for_status()
    json_data = resp2.json()["product"]

    colorway = _extract_tag(json_data.get("tags", []), "color")

    # Use .js variants for availability (has true/false, not null)
    js_variants = js_data.get("variants", [])
    json_variants = json_data.get("variants", [])

    if not js_variants:
        raise ValueError(f"Product has no variants: {product_url}")

    # Pricing — use .json variants for compare_at_price
    original_price = None
    sale_price = None
    for v in json_variants:
        cap = v.get("compare_at_price")
        price = v.get("price")
        if cap and price and float(cap) > float(price):
            original_price = float(cap)
            sale_price = float(price)
            break

    if original_price is None:
        sale_price = float(str(js_variants[0]["price"]) if js_variants[0]["price"] > 100 else js_variants[0]["price"])
        # .js prices are in cents for some stores
        if sale_price > 1000:
            sale_price = sale_price / 100
        original_price = sale_price

    discount_pct = round((1 - sale_price / original_price) * 100) if original_price > sale_price else 0

    # Images — combine .js images + .js media
    all_image_urls = []
    seen = set()

    # From .js images array (usually strings)
    for img in js_data.get("images", []):
        url = img if isinstance(img, str) else img.get("src", "")
        if url:
            if url.startswith("//"):
                url = "https:" + url
            normalized = _normalize_image_url(url)
            if normalized not in seen:
                seen.add(normalized)
                all_image_urls.append(url)

    # From .js media array (has more detail)
    for m in js_data.get("media", []):
        if m.get("media_type") == "image":
            url = m.get("src") or ""
            if not url:
                preview = m.get("preview_image", {})
                url = preview.get("src", "")
            if url:
                if url.startswith("//"):
                    url = "https:" + url
                normalized = _normalize_image_url(url)
                if normalized not in seen:
                    seen.add(normalized)
                    all_image_urls.append(url)

    # From .json images (backup)
    for img in json_data.get("images", []):
        url = img.get("src", "")
        if url:
            normalized = _normalize_image_url(url)
            if normalized not in seen:
                seen.add(normalized)
                all_image_urls.append(url)

    print(f"[FASHION-] Images: {len(all_image_urls)} total")

    images = []
    for i, url in enumerate(all_image_urls):
        images.append({
            "url": url,
            "alt": f"{json_data['title']} - image {i + 1}",
        })

    # Sizes — use .js variants for availability
    js_avail_map = {}
    for v in js_variants:
        js_avail_map[str(v["id"])] = v.get("available", False)

    sizes = []
    for v in json_variants:
        vid = str(v["id"])
        in_stock = js_avail_map.get(vid, False)

        sizes.append({
            "label": v.get("option1", v.get("title", "?")),
            "in_stock": in_stock,
            "variant_id": vid,
        })

    in_stock_count = sum(1 for s in sizes if s["in_stock"])
    any_in_stock = in_stock_count > 0
    print(f"[FASHION-] Sizes: {in_stock_count}/{len(sizes)} in stock")

    return {
        "name": json_data["title"],
        "brand": json_data.get("vendor", "Unknown"),
        "slug": handle,
        "sku": json_variants[0].get("sku") if json_variants else None,
        "colorway": colorway,
        "original_price": original_price,
        "sale_price": sale_price,
        "discount_pct": discount_pct,
        "description": json_data.get("body_html", ""),
        "product_url": product_url,
        "images": images,
        "sizes": sizes,
        "in_stock": any_in_stock,
        "_raw_tags": json_data.get("tags", []),
        "_base_url": base_url,
    }


def _normalize_image_url(url: str) -> str:
    url = url.split("?")[0]
    url = re.sub(r'_(pico|icon|thumb|small|compact|medium|large|grande|original|master|\d+x\d*|\d*x\d+)\.', '.', url)
    if url.startswith('//'):
        url = 'https:' + url
    return url.lower()


def _extract_tag(tags, prefix: str) -> str | None:
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    values = []
    for tag in tags:
        if tag.lower().startswith(f"{prefix}:"):
            values.append(tag.split(":", 1)[1].strip())
    return " / ".join(values) if values else None


if __name__ == "__main__":
    test_url = "https://en.afew-store.com/products/converse-chuck-70-ox-light-dune-black-egret"
    result = fetch_shopify_product(test_url)
    print(f"\nName: {result['name']}")
    print(f"In stock: {result['in_stock']}")
    print(f"Images: {len(result['images'])}")
    for i, img in enumerate(result['images']):
        print(f"  {i+1}. {img['url'][:120]}")
    print(f"\nSizes:")
    for s in result['sizes']:
        status = 'YES' if s['in_stock'] else 'NO '
        print(f"  [{status}] {s['label']}")
