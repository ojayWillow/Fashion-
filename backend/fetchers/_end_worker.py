"""END Clothing product fetcher via Algolia search API.

END Clothing uses Algolia for their product catalog. The search API
is public and returns full product data as JSON.

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

# Extracted from endclothing.com network requests 2026-03-05
ALGOLIA_APP_ID = "KO4W2GBINK"
ALGOLIA_API_KEY = "dfa5df098f8d677dd2105ece472a44f8"
ALGOLIA_AGENT = "Algolia for JavaScript (5.23.4); Browser; Lite"

_REGION_PRICE_MAP = {
    "eu": ("full_price_2", "final_price_2", "\u20ac"),
    "gb": ("full_price_1", "final_price_1", "\u00a3"),
    "us": ("full_price_3", "final_price_3", "$"),
    "row": ("full_price_2", "final_price_2", "\u20ac"),
    "ca": ("full_price_3", "final_price_3", "$"),
    "de": ("full_price_2", "final_price_2", "\u20ac"),
    "fr": ("full_price_2", "final_price_2", "\u20ac"),
}


def _extract_slug_and_sku(product_url):
    path = urlparse(product_url).path.rstrip("/")
    if path.endswith(".html"):
        path = path[:-5]
    slug = path.split("/")[-1]
    sku_match = re.search(r'([a-z]{1,3}\d{3,}[-_]?\d{0,3})$', slug, re.IGNORECASE)
    if sku_match:
        sku = sku_match.group(1)
    else:
        parts = slug.rsplit("-", 1)
        sku = parts[-1] if len(parts) > 1 else slug
    return slug, sku


def _extract_region(product_url):
    path = urlparse(product_url).path.strip("/")
    parts = path.split("/")
    if parts:
        region = parts[0].lower()
        if region in _REGION_PRICE_MAP:
            return region
    return "eu"


def _algolia_search(query, index="production_products_en", hits_per_page=5):
    """Make a search request to END's Algolia endpoint.
    Passes credentials as URL query params (matching END's frontend JS)."""
    url = (
        f"https://search1web.endclothing.com/1/indexes/*/queries"
        f"?x-algolia-agent={ALGOLIA_AGENT}"
        f"&x-algolia-api-key={ALGOLIA_API_KEY}"
        f"&x-algolia-application-id={ALGOLIA_APP_ID}"
    )

    payload = {
        "requests": [
            {
                "indexName": index,
                "params": f"query={query}&hitsPerPage={hits_per_page}",
            }
        ]
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://www.endclothing.com",
        "Referer": "https://www.endclothing.com/",
    }

    logger.info(f"Algolia search: query='{query}', index='{index}'")

    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _find_product(slug, sku):
    # Strategy 1: Search by SKU
    if sku:
        data = _algolia_search(sku)
        for rs in data.get("results", []):
            for hit in rs.get("hits", []):
                if hit.get("sku", "").lower() == sku.lower():
                    logger.info(f"Exact SKU match: {hit.get('name')}")
                    return hit
                if hit.get("url_key", "") == slug:
                    logger.info(f"url_key match: {hit.get('name')}")
                    return hit

    # Strategy 2: Search by slug words
    slug_query = slug.replace("-", " ")
    data = _algolia_search(slug_query, hits_per_page=10)
    for rs in data.get("results", []):
        for hit in rs.get("hits", []):
            if hit.get("url_key", "") == slug:
                logger.info(f"url_key match via slug: {hit.get('name')}")
                return hit

    # Strategy 3: Best hit
    for rs in data.get("results", []):
        hits = rs.get("hits", [])
        if hits:
            logger.info(f"Best Algolia hit: {hits[0].get('name')}")
            return hits[0]

    return None


def _build_image_url(path):
    if path.startswith("http"):
        return path
    return f"https://media.endclothing.com/media/catalog/product{path}"


def _parse_sizes_and_stock(hit):
    size_labels = hit.get("size_label") or hit.get("size") or []
    sku_stock = hit.get("sku_stock", {})
    if not size_labels:
        return []
    stock_values = list(sku_stock.values()) if sku_stock else []
    stock_keys = list(sku_stock.keys()) if sku_stock else []
    sizes = []
    for i, label in enumerate(size_labels):
        stock = stock_values[i] if i < len(stock_values) else 0
        sizes.append({
            "label": str(label),
            "raw_label": str(label),
            "in_stock": stock > 0,
            "stock_count": stock,
            "variant_id": stock_keys[i] if i < len(stock_keys) else None,
        })
    return sizes


def fetch_end_page(product_url):
    """Fetch product data from END Clothing via their Algolia API."""
    slug, sku = _extract_slug_and_sku(product_url)
    region = _extract_region(product_url)
    full_key, final_key, currency = _REGION_PRICE_MAP.get(region, _REGION_PRICE_MAP["eu"])

    hit = _find_product(slug, sku)

    if not hit:
        raise RuntimeError(
            f"Product not found on END Clothing. "
            f"Searched for SKU '{sku}' and slug '{slug}'."
        )

    original_price = hit.get(full_key)
    sale_price = hit.get(final_key)
    if not sale_price:
        original_price = hit.get("full_price_1")
        sale_price = hit.get("final_price_1")
        currency = "\u00a3"

    prices = []
    if original_price and sale_price and float(original_price) != float(sale_price):
        prices.append({"text": f"{currency}{original_price}", "value": float(original_price), "hasStrike": True})
        prices.append({"text": f"{currency}{sale_price}", "value": float(sale_price), "hasStrike": False})
    elif sale_price:
        prices.append({"text": f"{currency}{sale_price}", "value": float(sale_price), "hasStrike": False})

    media = hit.get("media_gallery", [])
    images = [_build_image_url(path) for path in media if path]
    for key in ("small_image", "model_full_image", "model_crop_image"):
        val = hit.get(key)
        if val and val != "no_selection":
            url = _build_image_url(val)
            if url not in images:
                images.append(url)

    sizes = _parse_sizes_and_stock(hit)
    categories = hit.get("categories", [])
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
