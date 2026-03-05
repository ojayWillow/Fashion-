"""END Clothing product fetcher — direct page scraping.

END Clothing's Algolia proxy and product pages are protected by Akamai.
Plain requests/httpx get 403/416 blocked.

Solution: curl_cffi impersonates real Chrome TLS fingerprints, bypassing
Akamai without needing a headless browser. We load the actual product
page and extract data from:
  1. __NEXT_DATA__ JSON (Next.js hydration data — has everything)
  2. application/ld+json script tags (structured product schema)
  3. HTML parsing with BeautifulSoup (fallback)

Usage:
    from fetchers._end_worker import fetch_end_page
    data = fetch_end_page("https://www.endclothing.com/eu/some-product-slug")

Requires:
    pip install curl_cffi beautifulsoup4 lxml
"""
import re
import json
import logging
from typing import Optional
from urllib.parse import urlparse

from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

logger = logging.getLogger("end_worker")

# Price fields per region
_REGION_PRICE_MAP = {
    "eu": ("EUR", "\u20ac"),
    "gb": ("GBP", "\u00a3"),
    "us": ("USD", "$"),
    "de": ("EUR", "\u20ac"),
    "fr": ("EUR", "\u20ac"),
    "row": ("EUR", "\u20ac"),
}


def _fetch_page_html(url: str) -> str:
    """Fetch END product page HTML using curl_cffi to bypass Akamai."""
    resp = cffi_requests.get(
        url,
        impersonate="chrome",
        timeout=20,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    if resp.status_code == 403:
        raise RuntimeError(
            f"END returned 403 Blocked. Akamai is blocking curl_cffi. "
            f"Try again or check if endclothing.com is reachable."
        )
    resp.raise_for_status()
    return resp.text


def _extract_next_data(html: str) -> Optional[dict]:
    """Extract __NEXT_DATA__ JSON from the HTML page."""
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag and tag.string:
        try:
            return json.loads(tag.string)
        except json.JSONDecodeError:
            logger.warning("Failed to parse __NEXT_DATA__ JSON")
    return None


def _extract_ld_json(html: str) -> list[dict]:
    """Extract all application/ld+json script contents."""
    soup = BeautifulSoup(html, "lxml")
    results = []
    for tag in soup.find_all("script", type="application/ld+json"):
        if tag.string:
            try:
                data = json.loads(tag.string)
                if isinstance(data, list):
                    results.extend(data)
                else:
                    results.append(data)
            except json.JSONDecodeError:
                continue
    return results


def _find_product_in_ld(ld_items: list[dict]) -> Optional[dict]:
    """Find the Product schema from LD+JSON items."""
    for item in ld_items:
        if item.get("@type") == "Product":
            return item
        # Sometimes nested in @graph
        graph = item.get("@graph", [])
        for node in graph:
            if node.get("@type") == "Product":
                return node
    return None


def _extract_region(url: str) -> str:
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    if parts:
        region = parts[0].lower()
        if region in _REGION_PRICE_MAP:
            return region
    return "eu"


def _parse_from_next_data(next_data: dict, url: str) -> Optional[dict]:
    """Try to extract product info from __NEXT_DATA__."""
    try:
        page_props = next_data.get("props", {}).get("pageProps", {})
        
        # The product data could be under various keys
        product = None
        for key in ("product", "productData", "initialProduct", "data"):
            if key in page_props and isinstance(page_props[key], dict):
                product = page_props[key]
                break
        
        if not product:
            # Try deeper nesting
            for key, val in page_props.items():
                if isinstance(val, dict) and ("name" in val or "sku" in val):
                    product = val
                    break
        
        if not product:
            logger.info("No product found in __NEXT_DATA__ pageProps")
            return None
        
        region = _extract_region(url)
        currency_code, currency_symbol = _REGION_PRICE_MAP.get(region, ("EUR", "\u20ac"))
        
        # Extract prices
        price_data = product.get("price", product.get("prices", {}))
        original_price = None
        sale_price = None
        
        if isinstance(price_data, dict):
            original_price = price_data.get("was") or price_data.get("full") or price_data.get("original")
            sale_price = price_data.get("now") or price_data.get("sale") or price_data.get("current") or price_data.get("final")
            if not sale_price:
                sale_price = price_data.get("amount") or price_data.get("value")
        elif isinstance(price_data, (int, float)):
            sale_price = float(price_data)

        # Extract sizes
        sizes = []
        size_data = product.get("sizes", product.get("variants", product.get("options", [])))
        if isinstance(size_data, list):
            for s in size_data:
                if isinstance(s, dict):
                    label = s.get("label") or s.get("size") or s.get("name") or str(s.get("value", ""))
                    in_stock = s.get("inStock", s.get("in_stock", s.get("available", True)))
                    stock_count = s.get("stock", s.get("quantity", 0))
                    sizes.append({
                        "label": str(label),
                        "raw_label": str(label),
                        "in_stock": bool(in_stock),
                        "stock_count": int(stock_count) if stock_count else 0,
                        "variant_id": s.get("sku") or s.get("id"),
                    })
                elif isinstance(s, str):
                    sizes.append({
                        "label": s, "raw_label": s,
                        "in_stock": True, "stock_count": 0, "variant_id": None,
                    })

        # Extract images
        images = []
        media = product.get("images", product.get("media", product.get("gallery", [])))
        if isinstance(media, list):
            for item in media:
                if isinstance(item, str):
                    images.append(_build_image_url(item))
                elif isinstance(item, dict):
                    img_url = item.get("url") or item.get("src") or item.get("path") or ""
                    if img_url:
                        images.append(_build_image_url(img_url))

        # Extract categories/breadcrumbs
        categories = product.get("categories", product.get("breadcrumbs", []))
        if isinstance(categories, list):
            categories = [c if isinstance(c, str) else c.get("name", "") for c in categories]

        prices = []
        if original_price and sale_price and float(original_price) != float(sale_price):
            prices.append({"text": f"{currency_symbol}{original_price}", "value": float(original_price), "hasStrike": True})
            prices.append({"text": f"{currency_symbol}{sale_price}", "value": float(sale_price), "hasStrike": False})
        elif sale_price:
            prices.append({"text": f"{currency_symbol}{sale_price}", "value": float(sale_price), "hasStrike": False})

        return {
            "name": product.get("name", ""),
            "brand": product.get("brand", {}).get("name", "") if isinstance(product.get("brand"), dict) else product.get("brand", ""),
            "colour": product.get("colour") or product.get("color") or "",
            "description": product.get("description", ""),
            "images": images,
            "prices": prices,
            "sizes": sizes,
            "breadcrumbs": categories,
            "ld": {
                "name": product.get("name"),
                "brand": product.get("brand", {}).get("name", "") if isinstance(product.get("brand"), dict) else product.get("brand", ""),
                "sku": product.get("sku"),
                "description": product.get("description"),
                "image": images[0] if images else None,
                "color": product.get("colour") or product.get("color"),
                "offers": {"price": sale_price, "priceCurrency": currency_code} if sale_price else None,
            },
            "_source": "next_data",
        }
    except Exception as e:
        logger.warning(f"Error parsing __NEXT_DATA__: {e}")
        return None


def _parse_from_ld_json(ld_product: dict, html: str, url: str) -> dict:
    """Extract product info from LD+JSON Product schema + HTML."""
    region = _extract_region(url)
    currency_code, currency_symbol = _REGION_PRICE_MAP.get(region, ("EUR", "\u20ac"))
    
    name = ld_product.get("name", "")
    brand = ld_product.get("brand", {})
    if isinstance(brand, dict):
        brand = brand.get("name", "")
    
    description = ld_product.get("description", "")
    sku = ld_product.get("sku", "")
    color = ld_product.get("color", "")
    
    # Images
    ld_images = ld_product.get("image", [])
    if isinstance(ld_images, str):
        ld_images = [ld_images]
    images = [_build_image_url(u) for u in ld_images if u]
    
    # Prices from offers
    offers = ld_product.get("offers", {})
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    
    sale_price = None
    original_price = None
    if offers:
        sale_price = offers.get("price") or offers.get("lowPrice")
        if sale_price:
            sale_price = float(sale_price)
    
    prices = []
    if sale_price:
        prices.append({"text": f"{currency_symbol}{sale_price}", "value": sale_price, "hasStrike": False})
    
    # Parse sizes from HTML
    sizes = _parse_sizes_from_html(html)
    
    # Parse more images from HTML if LD only gave us one
    if len(images) <= 1:
        html_images = _parse_images_from_html(html)
        for img in html_images:
            if img not in images:
                images.append(img)
    
    # Breadcrumbs from HTML
    breadcrumbs = _parse_breadcrumbs_from_html(html)
    
    return {
        "name": name,
        "brand": brand,
        "colour": color,
        "description": description,
        "images": images,
        "prices": prices,
        "sizes": sizes,
        "breadcrumbs": breadcrumbs,
        "ld": {
            "name": name,
            "brand": brand,
            "sku": sku,
            "description": description,
            "image": images[0] if images else None,
            "color": color,
            "offers": {"price": sale_price, "priceCurrency": currency_code} if sale_price else None,
        },
        "_source": "ld_json",
    }


def _parse_from_html_only(html: str, url: str) -> dict:
    """Last resort: parse product data from raw HTML."""
    soup = BeautifulSoup(html, "lxml")
    region = _extract_region(url)
    currency_code, currency_symbol = _REGION_PRICE_MAP.get(region, ("EUR", "\u20ac"))
    
    # Title
    name = ""
    title_tag = soup.find("h1")
    if title_tag:
        name = title_tag.get_text(strip=True)
    if not name:
        og_title = soup.find("meta", property="og:title")
        if og_title:
            name = og_title.get("content", "")
    
    # Brand — often in a specific element or part of the title
    brand = ""
    brand_tag = soup.find("meta", property="og:brand") or soup.find("meta", attrs={"name": "brand"})
    if brand_tag:
        brand = brand_tag.get("content", "")
    
    # Description
    description = ""
    desc_tag = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
    if desc_tag:
        description = desc_tag.get("content", "")
    
    # OG image
    images = []
    og_img = soup.find("meta", property="og:image")
    if og_img and og_img.get("content"):
        images.append(og_img["content"])
    
    # More images from HTML
    images.extend([i for i in _parse_images_from_html(html) if i not in images])
    
    # Price from meta or HTML
    sale_price = None
    price_tag = soup.find("meta", property="product:price:amount")
    if price_tag:
        try:
            sale_price = float(price_tag["content"])
        except (ValueError, KeyError):
            pass
    
    prices = []
    if sale_price:
        prices.append({"text": f"{currency_symbol}{sale_price}", "value": sale_price, "hasStrike": False})
    
    sizes = _parse_sizes_from_html(html)
    breadcrumbs = _parse_breadcrumbs_from_html(html)
    
    return {
        "name": name,
        "brand": brand,
        "colour": "",
        "description": description,
        "images": images,
        "prices": prices,
        "sizes": sizes,
        "breadcrumbs": breadcrumbs,
        "ld": {
            "name": name,
            "brand": brand,
            "sku": None,
            "description": description,
            "image": images[0] if images else None,
            "color": None,
            "offers": {"price": sale_price, "priceCurrency": currency_code} if sale_price else None,
        },
        "_source": "html_only",
    }


def _build_image_url(path: str) -> str:
    if not path:
        return ""
    if path.startswith("http"):
        return path
    if path.startswith("//"):
        return "https:" + path
    return f"https://media.endclothing.com/media/catalog/product{path}"


def _parse_sizes_from_html(html: str) -> list[dict]:
    """Extract sizes from HTML (button elements, select options, etc.)."""
    soup = BeautifulSoup(html, "lxml")
    sizes = []
    
    # Look for size buttons/options
    ignore_labels = {'size guide', 'size chart', 'find your size', 'select size',
                     'choose size', 'add to bag', 'add to cart', 'notify me', 'one size'}
    
    # Try size selector buttons
    for btn in soup.select("button[data-test-id*='size'], button[class*='size'], [data-size]"):
        label = btn.get_text(strip=True)
        if label.lower() in ignore_labels or not label:
            continue
        disabled = btn.get("disabled") is not None or "disabled" in btn.get("class", [])
        sizes.append({
            "label": label, "raw_label": label,
            "in_stock": not disabled, "stock_count": 0, "variant_id": None,
        })
    
    # Try select option elements
    if not sizes:
        for opt in soup.select("select[name*='size'] option, select[id*='size'] option"):
            label = opt.get_text(strip=True)
            if not label or label.lower() in ignore_labels:
                continue
            disabled = opt.get("disabled") is not None
            sizes.append({
                "label": label, "raw_label": label,
                "in_stock": not disabled, "stock_count": 0, "variant_id": opt.get("value"),
            })
    
    return sizes


def _parse_images_from_html(html: str) -> list[str]:
    """Extract product images from HTML."""
    soup = BeautifulSoup(html, "lxml")
    images = []
    
    # Look for product gallery images
    for img in soup.select("img[src*='media.endclothing'], img[src*='catalog/product']"):
        src = img.get("src") or img.get("data-src") or ""
        if src and src not in images:
            images.append(_build_image_url(src))
    
    # Also try srcset
    for img in soup.select("img[srcset*='media.endclothing']"):
        srcset = img.get("srcset", "")
        for part in srcset.split(","):
            url = part.strip().split(" ")[0]
            if url and "media.endclothing" in url and url not in images:
                images.append(url)
    
    return images


def _parse_breadcrumbs_from_html(html: str) -> list[str]:
    """Extract breadcrumb navigation from HTML."""
    soup = BeautifulSoup(html, "lxml")
    crumbs = []
    
    # Try structured breadcrumbs
    for nav in soup.select("nav[aria-label*='breadcrumb'], [class*='breadcrumb']"):
        for a in nav.find_all("a"):
            text = a.get_text(strip=True)
            if text and text.lower() != "home":
                crumbs.append(text)
        if crumbs:
            return crumbs
    
    return crumbs


def fetch_end_page(product_url: str) -> dict:
    """Fetch product data from END Clothing.
    
    Uses curl_cffi to impersonate Chrome (bypasses Akamai TLS fingerprinting).
    Extracts data from __NEXT_DATA__, LD+JSON, or raw HTML parsing.
    """
    logger.info(f"Fetching END page: {product_url}")
    
    html = _fetch_page_html(product_url)
    logger.info(f"Got HTML ({len(html)} bytes)")
    
    # Strategy 1: __NEXT_DATA__ (richest data source)
    next_data = _extract_next_data(html)
    if next_data:
        logger.info("Found __NEXT_DATA__, attempting parse...")
        result = _parse_from_next_data(next_data, product_url)
        if result and result.get("name"):
            logger.info(f"Parsed from __NEXT_DATA__: {result['name']}")
            return result
    
    # Strategy 2: LD+JSON Product schema
    ld_items = _extract_ld_json(html)
    ld_product = _find_product_in_ld(ld_items)
    if ld_product:
        logger.info("Found LD+JSON Product, attempting parse...")
        result = _parse_from_ld_json(ld_product, html, product_url)
        if result and result.get("name"):
            logger.info(f"Parsed from LD+JSON: {result['name']}")
            return result
    
    # Strategy 3: Raw HTML parsing
    logger.info("Falling back to HTML-only parsing...")
    result = _parse_from_html_only(html, product_url)
    if result and result.get("name"):
        logger.info(f"Parsed from HTML: {result['name']}")
        return result
    
    raise RuntimeError(
        f"Could not extract product data from {product_url}. "
        f"Page may have changed structure or Akamai blocked the request. "
        f"HTML length: {len(html)}"
    )


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("Usage: python _end_worker.py <product_url>")
        sys.exit(1)
    data = fetch_end_page(sys.argv[1])
    print(json.dumps(data, indent=2, ensure_ascii=False))
