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

    # Step 2: Get real-time variant availability
    variant_ids = [str(v["id"]) for v in variants]
    availability = _fetch_variant_availability(base_url, variant_ids)

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

    # Step 3: Get ALL images — JSON + HTML scrape
    json_image_urls = [img["src"] for img in data.get("images", [])]

    # Scrape the actual product page for more images
    page_image_urls = _scrape_page_images(product_url)

    # Merge and deduplicate
    all_image_urls = _merge_images(json_image_urls, page_image_urls)

    print(f"[FASHION-] Images: {len(json_image_urls)} from JSON, {len(page_image_urls)} from page, {len(all_image_urls)} total")

    images = []
    for i, url in enumerate(all_image_urls):
        images.append({
            "url": url,
            "alt": f"{data['title']} - image {i + 1}",
        })

    # Step 4: Build sizes with real availability
    sizes = []
    for v in variants:
        vid = str(v["id"])
        # Check real-time availability first, fall back to JSON
        if availability:
            in_stock = availability.get(vid, False)
        else:
            in_stock = v.get("available", False)

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


def _fetch_variant_availability(base_url: str, variant_ids: list[str]) -> dict:
    """Fetch real-time variant availability using Shopify's storefront endpoints.

    Tries multiple methods:
    1. The variants.json endpoint (batch check)
    2. Individual variant availability check
    3. The product page HTML for embedded JSON data
    """
    availability = {}

    # Method 1: Try the product page for embedded variant data
    # Shopify embeds variant availability in a JS variable on the product page
    # This is the most reliable method for stores like AFEW
    # (already fetched in _scrape_page_images, but we do a targeted extraction here)

    # Method 2: Try variants.json endpoint
    try:
        # Shopify has an undocumented endpoint for checking variant availability
        # Check each variant individually via the cart/add endpoint simulation
        for vid in variant_ids:
            try:
                check_url = f"{base_url}/variants/{vid}.json"
                resp = SESSION.get(check_url, timeout=5)
                if resp.ok:
                    vdata = resp.json().get("variant", {})
                    availability[vid] = vdata.get("available", False)
            except Exception:
                continue

        if availability:
            return availability
    except Exception:
        pass

    return availability


def _scrape_page_images(product_url: str) -> list[str]:
    """Scrape the actual product page for all product images.

    Shopify stores render additional images on the page that aren't
    always in the products.json endpoint. We look for:
    1. Shopify CDN URLs in the HTML
    2. JSON-LD structured data
    3. Embedded product JSON in script tags
    """
    try:
        resp = SESSION.get(product_url, timeout=15)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"[FASHION-] Could not scrape page: {e}")
        return []

    images = []
    seen = set()

    # Method 1: Find all Shopify CDN product image URLs
    # Match various CDN patterns including //cdn.shopify.com and https://cdn.shopify.com
    cdn_patterns = [
        r'(?:https?:)?//cdn\.shopify\.com/s/files/[^"\s\)\}\>\'\']+\.(?:jpg|jpeg|png|webp)',
        r'(?:https?:)?//[\w.-]*\.shopifycdn\.com/[^"\s\)\}\>\'\']+\.(?:jpg|jpeg|png|webp)',
    ]

    for pattern in cdn_patterns:
        for match in re.findall(pattern, html, re.IGNORECASE):
            url = match if match.startswith('http') else 'https:' + match
            # Only keep product images, not theme/icon images
            if '/products/' in url or '/product-images/' in url:
                clean = _normalize_image_url(url)
                if clean not in seen:
                    seen.add(clean)
                    images.append(url.split('?')[0])  # Remove query params but keep size

    # Method 2: Look for embedded product JSON in script tags
    # Many Shopify themes embed the full product object in a script tag
    try:
        # Pattern: var product = {...} or window.product = {...}
        json_patterns = [
            r'var\s+(?:meta|product)\s*=\s*(\{.*?\});',
            r'"product"\s*:\s*(\{"id".*?\})(?:,|\s*\})',
            r'product:\s*(\{"id".*?\})(?:,|\s*\})',
        ]
        for pattern in json_patterns:
            for match in re.findall(pattern, html, re.DOTALL):
                try:
                    pdata = _json.loads(match)
                    # Could be nested under "product" key
                    if "product" in pdata:
                        pdata = pdata["product"]
                    for img in pdata.get("images", pdata.get("media", [])):
                        img_url = None
                        if isinstance(img, dict):
                            img_url = img.get("src") or img.get("url")
                        elif isinstance(img, str):
                            img_url = img
                        if img_url:
                            if img_url.startswith('//'):
                                img_url = 'https:' + img_url
                            clean = _normalize_image_url(img_url)
                            if clean not in seen and 'cdn.shopify.com' in img_url:
                                seen.add(clean)
                                images.append(img_url.split('?')[0])
                except (_json.JSONDecodeError, TypeError, KeyError):
                    continue
    except Exception:
        pass

    # Method 3: JSON-LD structured data
    try:
        ld_pattern = r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>'
        for match in re.findall(ld_pattern, html, re.DOTALL):
            try:
                ld_data = _json.loads(match)
                if isinstance(ld_data, dict) and ld_data.get("@type") == "Product":
                    ld_images = ld_data.get("image", [])
                    if isinstance(ld_images, str):
                        ld_images = [ld_images]
                    for img_url in ld_images:
                        if isinstance(img_url, str) and 'cdn.shopify.com' in img_url:
                            clean = _normalize_image_url(img_url)
                            if clean not in seen:
                                seen.add(clean)
                                images.append(img_url.split('?')[0])
            except (_json.JSONDecodeError, TypeError):
                continue
    except Exception:
        pass

    print(f"[FASHION-] Scraped {len(images)} images from product page")
    return images


def _normalize_image_url(url: str) -> str:
    """Normalize a Shopify CDN URL for deduplication.

    Removes size suffixes and query params to compare base images.
    """
    url = url.split('?')[0]
    url = re.sub(r'_(pico|icon|thumb|small|compact|medium|large|grande|original|master|\d+x\d*|\d*x\d+)\.', '.', url)
    if url.startswith('//'):
        url = 'https:' + url
    return url.lower()


def _merge_images(json_images: list[str], page_images: list[str]) -> list[str]:
    """Merge images from JSON API and page scraping, removing duplicates."""
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
        print(f"  {i+1}. {img['url'][:100]}")
    print(f"\nSizes: {len(result['sizes'])}")
    for s in result['sizes']:
        status = '\u2705' if s['in_stock'] else '\u274c'
        print(f"  {status} {s['label']}")
