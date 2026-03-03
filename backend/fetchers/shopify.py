"""Fetch product data from Shopify stores (e.g., AFEW Store).

Usage:
    from fetchers.shopify import fetch_shopify_product
    product_data = fetch_shopify_product("https://en.afew-store.com/products/nike-air-max-1-sc")
"""
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

    # Extract handle from URL path
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

    # Use the first variant with a compare_at_price for pricing
    original_price = None
    sale_price = None
    for v in variants:
        cap = v.get("compare_at_price")
        price = v.get("price")
        if cap and price and float(cap) > float(price):
            original_price = float(cap)
            sale_price = float(price)
            break

    # Fallback: no sale detected, use regular price
    if original_price is None:
        sale_price = float(variants[0]["price"])
        original_price = sale_price

    discount_pct = round((1 - sale_price / original_price) * 100) if original_price > sale_price else 0

    # Build images list
    images = []
    for img in data.get("images", []):
        images.append({
            "url": img["src"],
            "alt": f"{data['title']} - image {img.get('position', 0)}",
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
    import json
    test_url = "https://en.afew-store.com/products/hoka-one-one-mafate-speed-4-lite-stucco-alabaster"
    result = fetch_shopify_product(test_url)
    print(json.dumps({
        "name": result["name"],
        "brand": result["brand"],
        "colorway": result["colorway"],
        "original_price": result["original_price"],
        "sale_price": result["sale_price"],
        "discount_pct": result["discount_pct"],
        "images": len(result["images"]),
        "sizes": len(result["sizes"]),
        "sizes_in_stock": sum(1 for s in result["sizes"] if s["in_stock"]),
    }, indent=2))
