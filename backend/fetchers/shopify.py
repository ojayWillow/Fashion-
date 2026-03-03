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

    # Step 1: Fetch product JSON
    json_url = f"{base_url}/products/{handle}.json"
    resp = SESSION.get(json_url, timeout=15)
    resp.raise_for_status()
    data = resp.json()["product"]

    colorway = _extract_tag(data.get("tags", []), "color")

    variants = data.get("variants", [])
    if not variants:
        raise ValueError(f"Product has no variants: {product_url}")

    # Pricing
    original_price = None
    sale_price = None
    for v in variants:
        cap = v.get("compare_at_price")
        price = v.get("price")
        if cap and price and float(cap) > float(price):
            original_price = float(cap)
            sale_price = float(price)
            break

    if original_price is None:
        sale_price = float(variants[0]["price"])
        original_price = sale_price

    discount_pct = round((1 - sale_price / original_price) * 100) if original_price > sale_price else 0

    # Step 2: Scrape the actual product page for images AND availability
    page_data = _scrape_product_page(product_url)

    # Build images: JSON images + page images
    json_image_urls = [img["src"] for img in data.get("images", [])]
    page_image_urls = page_data.get("images", [])
    all_image_urls = _merge_images(json_image_urls, page_image_urls)

    print(f"[FASHION-] Images: {len(json_image_urls)} from JSON, {len(page_image_urls)} from page, {len(all_image_urls)} total")

    images = []
    for i, url in enumerate(all_image_urls):
        images.append({
            "url": url,
            "alt": f"{data['title']} - image {i + 1}",
        })

    # Step 3: Build sizes with page availability data
    page_availability = page_data.get("availability", {})

    sizes = []
    for v in variants:
        vid = str(v["id"])
        # Priority: page HTML data > JSON available field > default False
        if page_availability:
            in_stock = page_availability.get(vid, False)
        elif v.get("available") is not None:
            in_stock = v.get("available", False)
        else:
            in_stock = False

        sizes.append({
            "label": v.get("option1", v.get("title", "?")),
            "in_stock": in_stock,
            "variant_id": vid,
        })

    in_stock_count = sum(1 for s in sizes if s["in_stock"])
    print(f"[FASHION-] Sizes: {in_stock_count}/{len(sizes)} in stock")

    return {
        "name": data["title"],
        "brand": data.get("vendor", "Unknown"),
        "slug": handle,
        "sku": variants[0].get("sku"),
        "colorway": colorway,
        "original_price": original_price,
        "sale_price": sale_price,
        "discount_pct": discount_pct,
        "description": data.get("body_html", ""),
        "product_url": product_url,
        "images": images,
        "sizes": sizes,
        "_raw_tags": data.get("tags", []),
        "_base_url": base_url,
    }


def _scrape_product_page(product_url: str) -> dict:
    """Scrape the product page HTML for images and variant availability.

    Returns dict with:
        images: list of image URLs
        availability: dict of variant_id -> bool
    """
    result = {"images": [], "availability": {}}

    try:
        resp = SESSION.get(product_url, timeout=15)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"[FASHION-] Could not scrape page: {e}")
        return result

    # === IMAGES ===
    seen_images = set()

    # Find ALL Shopify CDN image URLs (not just /products/ path)
    cdn_pattern = r'(?:https?:)?//cdn\.shopify\.com/s/files/[^"\s)}\'><]+\.(?:jpg|jpeg|png|webp)'
    for match in re.findall(cdn_pattern, html, re.IGNORECASE):
        url = match if match.startswith('http') else 'https:' + match
        clean_url = url.split('?')[0]

        # Filter out tiny icons/logos by checking for common non-product patterns
        skip_patterns = ['/icons/', '/logo', '/badge', '/flag', '/payment', '/social',
                        '/favicon', '/arrow', '/cart', '/search', '/close', '/menu',
                        '/check', '/star', '/heart', '/footer', '/header', '/banner']
        if any(p in clean_url.lower() for p in skip_patterns):
            continue

        normalized = _normalize_image_url(clean_url)
        if normalized not in seen_images:
            seen_images.add(normalized)
            result["images"].append(clean_url)

    # === AVAILABILITY ===
    # Look for variant availability in embedded script tags
    # Shopify themes typically embed product data in JS
    script_pattern = r'<script[^>]*>(.*?)</script>'
    for script_content in re.findall(script_pattern, html, re.DOTALL):
        if '"available"' not in script_content or '"variants"' not in script_content:
            continue

        # Try to extract variant data from various common formats
        # Format 1: "variants":[{..."id":123,"available":true...},...]
        variant_pattern = r'"id"\s*:\s*(\d+).*?"available"\s*:\s*(true|false)'
        for vid, avail in re.findall(variant_pattern, script_content):
            result["availability"][vid] = avail == "true"

        # Format 2: Sometimes available comes before id
        variant_pattern2 = r'"available"\s*:\s*(true|false).*?"id"\s*:\s*(\d+)'
        for avail, vid in re.findall(variant_pattern2, script_content):
            if vid not in result["availability"]:
                result["availability"][vid] = avail == "true"

        if result["availability"]:
            break

    avail_count = sum(1 for v in result["availability"].values() if v)
    print(f"[FASHION-] Scraped {len(result['images'])} images, {avail_count}/{len(result['availability'])} available variants from page")

    return result


def _normalize_image_url(url: str) -> str:
    url = url.split('?')[0]
    url = re.sub(r'_(pico|icon|thumb|small|compact|medium|large|grande|original|master|\d+x\d*|\d*x\d+)\.', '.', url)
    if url.startswith('//'):
        url = 'https:' + url
    return url.lower()


def _merge_images(json_images: list[str], page_images: list[str]) -> list[str]:
    seen = set()
    result = []

    for url in json_images:
        clean = _normalize_image_url(url)
        if clean not in seen:
            seen.add(clean)
            result.append(url)

    for url in page_images:
        clean = _normalize_image_url(url)
        if clean not in seen:
            seen.add(clean)
            result.append(url)

    return result


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
    print(f"Images found: {len(result['images'])}")
    for i, img in enumerate(result['images']):
        print(f"  {i+1}. {img['url'][:120]}")
    print(f"\nSizes:")
    for s in result['sizes']:
        status = 'YES' if s['in_stock'] else 'NO'
        print(f"  [{status}] {s['label']}")
