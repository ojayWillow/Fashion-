"""END Clothing product fetcher — via Algolia search API.

END Clothing uses Algolia for their product catalog. The search API
is public and returns full product data as JSON:
- name, brand, SKU, description
- prices (full + sale) per region
- sizes with stock counts
- all product images
- categories, colours, season

No browser needed. No anti-bot protection. Just HTTP POST.

Usage:
    from fetchers._end_worker import fetch_end_page
    data = fetch_end_page("https://www.endclothing.com/eu/some-product-slug")

Setup:
    pip install requests
"""
import re
import json
import logging
from typing import Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger("end_worker")

# END Clothing's Algolia credentials (public, embedded in their frontend JS)
ALGOLIA_URL = "https://search1web.endclothing.com/1/indexes/*/queries"
ALGOLIA_APP_ID = "2ESMGW31QF"
ALGOLIA_API_KEY = "MzhhMGNlNGEtODJlNC00NmMyLWFhMWUtMzRkOGJhODYxZDIz"

# END uses numbered price fields per region/currency:
# full_price_1 / final_price_1 = GBP
# full_price_2 / final_price_2 = EUR (EU store)
# full_price_3 / final_price_3 = USD
# full_price_4 / final_price_4 = SEK/DKK etc.
# We want EUR for /eu/ URLs, GBP for /gb/ URLs
_REGION_PRICE_MAP = {
    "eu": ("full_price_2", "final_price_2", "\u20ac"),
    "gb": ("full_price_1", "final_price_1", "\u00a3"),
    "us": ("full_price_3", "final_price_3", "$"),
    "row": ("full_price_2", "final_price_2", "\u20ac"),  # fallback to EUR
    "ca": ("full_price_3", "final_price_3", "$"),
    "de": ("full_price_2", "final_price_2", "\u20ac"),
    "fr": ("full_price_2", "final_price_2", "\u20ac"),
}


def _extract_slug_and_sku(product_url: str) -> tuple[str, str]:
    """Extract the URL slug and SKU from an END Clothing product URL.

    URL format: https://www.endclothing.com/{region}/{name}-{sku}.html
    or:         https://www.endclothing.com/{region}/{name}-{sku}
    Example:    .../eu/mm6-maison-margiela-fleece-trackpant-sh0ka0050
    """
    path = urlparse(product_url).path.rstrip("/")
    # Remove .html extension if present
    if path.endswith(".html"):
        path = path[:-5]
    # Last segment is the slug
    slug = path.split("/")[-1]
    # SKU is typically the last hyphen-separated segment
    parts = slug.rsplit("-", 1)
    sku = parts[-1] if len(parts) > 1 else slug
    return slug, sku


def _extract_region(product_url: str) -> str:
    """Extract the region code from the URL path."""
    path = urlparse(product_url).path.strip("/")
    parts = path.split("/")
    if parts:
        region = parts[0].lower()
        if region in _REGION_PRICE_MAP:
            return region
    return "eu"  # default


def _search_algolia(query: str, sku: str = "") -> Optional[dict]:
    """Search END's Algolia index for a product.

    Tries SKU first (exact match), falls back to slug-based search.
    """
    headers = {
        "Content-Type": "application/json",
        "x-algolia-application-id": ALGOLIA_APP_ID,
        "x-algolia-api-key": ALGOLIA_API_KEY,
    }

    # Try SKU search first (most precise)
    searches = []
    if sku:
        searches.append({
            "indexName": "production_products_en",
            "params": f"query={sku}&hitsPerPage=5",
        })
    # Also search by full slug (as fallback)
    slug_query = query.replace("-", " ")
    searches.append({
        "indexName": "production_products_en",
        "params": f"query={slug_query}&hitsPerPage=10",
    })

    payload = {"requests": searches}

    logger.info(f"Searching Algolia: sku='{sku}', slug='{slug_query}'")

    resp = requests.post(
        ALGOLIA_URL,
        headers=headers,
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    # Check SKU results first
    for result_set in data.get("results", []):
        hits = result_set.get("hits", [])
        for hit in hits:
            # Match by SKU
            if sku and hit.get("sku", "").lower() == sku.lower():
                logger.info(f"Found exact SKU match: {hit.get('name')}")
                return hit
            # Match by url_key
            if hit.get("url_key", "") == query:
                logger.info(f"Found url_key match: {hit.get('name')}")
                return hit

    # If no exact match, return best hit from slug search
    for result_set in data.get("results", []):
        hits = result_set.get("hits", [])
        if hits:
            logger.info(f"Using best Algolia hit: {hits[0].get('name')}")
            return hits[0]

    return None


def _build_image_url(path: str) -> str:
    """Convert Algolia media path to full END CDN URL."""
    if path.startswith("http"):
        return path
    return f"https://media.endclothing.com/media/catalog/product{path}"


def _parse_sizes_and_stock(hit: dict) -> list[dict]:
    """Extract sizes and stock from Algolia hit.

    Algolia returns:
    - size_label: ["Small", "Medium", ...] or ["EU 40", "EU 41", ...]
    - size: same as size_label usually
    - sku_stock: {"variant_sku": count, ...}
    """
    size_labels = hit.get("size_label") or hit.get("size") or []
    sku_stock = hit.get("sku_stock", {})

    if not size_labels:
        return []

    # sku_stock keys are variant SKUs, values are stock counts
    # The order usually matches size_labels
    stock_values = list(sku_stock.values()) if sku_stock else []

    sizes = []
    for i, label in enumerate(size_labels):
        stock = stock_values[i] if i < len(stock_values) else 0
        sizes.append({
            "label": str(label),
            "raw_label": str(label),
            "in_stock": stock > 0,
            "stock_count": stock,
            "variant_id": list(sku_stock.keys())[i] if i < len(sku_stock) else None,
        })

    return sizes


def fetch_end_page(product_url: str) -> dict:
    """Fetch product data from END Clothing via their Algolia API.

    Returns a dict compatible with the existing END product pipeline.
    """
    slug, sku = _extract_slug_and_sku(product_url)
    region = _extract_region(product_url)
    full_key, final_key, currency = _REGION_PRICE_MAP.get(region, _REGION_PRICE_MAP["eu"])

    hit = _search_algolia(slug, sku)

    if not hit:
        raise RuntimeError(
            f"Product not found on END Clothing. "
            f"Searched for SKU '{sku}' and slug '{slug}'."
        )

    # --- Prices ---
    original_price = hit.get(full_key)
    sale_price = hit.get(final_key)
    # If no region-specific price, try GBP as fallback
    if not sale_price:
        original_price = hit.get("full_price_1")
        sale_price = hit.get("final_price_1")
        currency = "\u00a3"

    prices = []
    if original_price and sale_price and original_price != sale_price:
        prices.append({"text": f"{currency}{original_price}", "value": float(original_price), "hasStrike": True})
        prices.append({"text": f"{currency}{sale_price}", "value": float(sale_price), "hasStrike": False})
    elif sale_price:
        prices.append({"text": f"{currency}{sale_price}", "value": float(sale_price), "hasStrike": False})

    # --- Images ---
    media = hit.get("media_gallery", [])
    images = [_build_image_url(path) for path in media if path]
    # Add small_image and model images as fallback
    for key in ("small_image", "model_full_image", "model_crop_image"):
        val = hit.get(key)
        if val and val != "no_selection":
            url = _build_image_url(val)
            if url not in images:
                images.append(url)

    # --- Sizes ---
    sizes = _parse_sizes_and_stock(hit)

    # --- Category detection ---
    categories = hit.get("categories", [])
    dept = (hit.get("departmentv1") or hit.get("department") or "").lower()
    cat_v1 = (hit.get("categoryv1") or "").lower()

    # --- Build result ---
    on_sale = original_price and sale_price and float(sale_price) < float(original_price)

    result = {
        "name": hit.get("name", ""),
        "brand": hit.get("brand", ""),
        "colour": hit.get("actual_colour") or ", ".join(hit.get("colour", [])),
        "description": hit.get("description", ""),
        "images": images,
        "prices": prices,
        "sizes": sizes,
        "breadcrumbs": [c for c in categories if "/" not in c],
        "ld": {
            "name": hit.get("name"),
            "brand": hit.get("brand"),
            "sku": hit.get("sku"),
            "description": hit.get("description"),
            "image": images[0] if images else None,
            "color": hit.get("actual_colour"),
            "offers": {
                "price": sale_price,
                "priceCurrency": currency,
            } if sale_price else None,
        },
        # Extra Algolia fields
        "_algolia": {
            "objectID": hit.get("objectID"),
            "sku": hit.get("sku"),
            "url_key": hit.get("url_key"),
            "season": hit.get("season"),
            "gender": hit.get("gender"),
            "department": hit.get("departmentv1") or hit.get("department"),
            "category": hit.get("categoryv1"),
            "sale_type": hit.get("sale_type"),
            "on_sale": on_sale,
            "total_stock": hit.get("stock", 0),
            "original_price": original_price,
            "sale_price": sale_price,
            "currency": currency,
        },
    }

    logger.info(
        f"Fetched via Algolia: name='{result['name']}', brand='{result['brand']}', "
        f"images={len(images)}, sizes={len(sizes)}, "
        f"price={currency}{sale_price}, stock={hit.get('stock', 0)}"
    )
    return result


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("Usage: python _end_worker.py <product_url>")
        sys.exit(1)
    data = fetch_end_page(sys.argv[1])
    print(json.dumps(data, indent=2, ensure_ascii=False))
