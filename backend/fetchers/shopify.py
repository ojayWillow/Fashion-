"""Fetch product data from Shopify stores (e.g., AFEW Store).

Usage:
    from fetchers.shopify import fetch_shopify_product
    product_data = fetch_shopify_product("https://en.afew-store.com/products/nike-air-max-1-sc")
"""
import re
import json as _json
import requests
from urllib.parse import urlparse


def fetch_shopify_product(product_url: str) -> dict:
    """Fetch all product data from a Shopify product URL.

    Takes a URL like:
        https://en.afew-store.com/products/hoka-one-one-mafate-speed-4-lite-stucco-alabaster

    Returns a dict ready for database insertion with all fields mapped.
    """
    parsed = urlparse(product_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    handle = parsed.path.rstrip("/").split("/")[-1]
    if not handle:
        raise ValueError(f"Could not extract product handle from URL: {product_url}")

    # Fetch product JSON
    json_url = f"{base_url}/products/{handle}.json"
    resp = requests.get(json_url, timeout=15)
    resp.raise_for_status()
    data = resp.json()["product"]

    # Extract colorway from tags
    colorway = _extract_tag(data.get("tags", []), "color")

    # Find the best price info from variants
    variants = data.get("variants", [])
    if not variants:
        raise ValueError(f"Product has no variants: {product_url}")

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

    # Build images list from JSON
    json_images = []
    for img in data.get("images", []):
        json_images.append(img["src"])

    # Also scrape the product page HTML for additional images
    page_images = _scrape_page_images(product_url, base_url)

    # Merge: use all unique images, page images often have more
    all_image_urls = _merge_images(json_images, page_images)

    images = []
    for i, url in enumerate(all_image_urls):
        images.append({
            "url": url,
            "alt": f"{data['title']} - image {i + 1}",
        })

    # Build sizes list
    sizes = []
    for v in variants:
        sizes.append({
            "label": v.get("option1", v.get("title", "?")),
            "in_stock": v.get("available", False),
            "variant_id": str(v["id"]),
        })

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


def _scrape_page_images(product_url: str, base_url: str) -> list[str]:
    """Scrape the actual product page HTML for additional CDN image URLs.

    Shopify stores often embed extra product images in their page HTML
    (inside JSON-LD, media galleries, or JavaScript data) that don't
    appear in the basic products.json endpoint.
    """
    try:
        resp = requests.get(product_url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp.raise_for_status()
        html = resp.text
    except Exception:
        return []

    images = set()

    # Method 1: Find all Shopify CDN image URLs in the page
    cdn_pattern = r'https?://cdn\.shopify\.com/s/files/[^"\s\)\}\>]+\.(?:jpg|jpeg|png|webp)'
    for match in re.findall(cdn_pattern, html, re.IGNORECASE):
        # Clean up URL — remove size suffixes to get the largest version
        clean = _get_largest_image(match)
        # Only include product images (not theme/logo images)
        if '/products/' in clean or '/product/' in clean:
            images.add(clean)

    # Method 2: Parse JSON-LD structured data
    try:
        ld_pattern = r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>'
        for match in re.findall(ld_pattern, html, re.DOTALL):
            try:
                ld_data = _json.loads(match)
                if isinstance(ld_data, dict) and ld_data.get("@type") == "Product":
                    for img_url in ld_data.get("image", []):
                        if isinstance(img_url, str) and 'cdn.shopify.com' in img_url:
                            images.add(_get_largest_image(img_url))
            except (_json.JSONDecodeError, TypeError):
                continue
    except Exception:
        pass

    return list(images)


def _get_largest_image(url: str) -> str:
    """Remove Shopify image size suffixes to get the original/largest version.

    Converts URLs like:
        ...product_800x.jpg -> ...product.jpg
        ...product_medium.jpg -> ...product.jpg
        ...product_1024x1024.jpg -> ...product.jpg
    """
    # Remove size parameters from URL query string
    url = url.split("?")[0]
    # Remove size suffixes like _800x, _medium, _1024x1024, etc.
    url = re.sub(r'_(pico|icon|thumb|small|compact|medium|large|grande|original|master|\d+x\d*|\d*x\d+)\.', '.', url)
    return url


def _merge_images(json_images: list[str], page_images: list[str]) -> list[str]:
    """Merge images from JSON API and page scraping, removing duplicates.

    Keeps JSON images first (they're usually the best ordered), then
    appends any additional images found on the page.
    """
    seen = set()
    result = []

    for url in json_images:
        clean = _get_largest_image(url)
        if clean not in seen:
            seen.add(clean)
            result.append(url)  # Keep original URL with size params

    for url in page_images:
        clean = _get_largest_image(url)
        if clean not in seen:
            seen.add(clean)
            result.append(url)

    return result


def _extract_tag(tags, prefix: str) -> str | None:
    """Extract value from Shopify tags like 'color:Beige'."""
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
    print(f"Name: {result['name']}")
    print(f"Images found: {len(result['images'])}")
    for i, img in enumerate(result['images']):
        print(f"  {i+1}. {img['url'][:80]}...")
    print(f"Sizes: {len(result['sizes'])}")
