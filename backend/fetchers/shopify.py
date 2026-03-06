"""Fetch product data from Shopify stores (e.g., AFEW Store).

Uses two Shopify public endpoints:
- /products/{handle}.json  — rich product data (images, tags, description, pricing)
- /products/{handle}.js   — storefront data (real variant availability)

These are public APIs intended for headless storefronts, not scraping.
"""
import re
import time
import requests
from urllib.parse import urlparse
from utils.size_converter import convert_to_eu
from utils.category_detector import detect_category
from utils.http_retry import request_with_retry

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
})


def fetch_shopify_product(product_url: str) -> dict:
    parsed = urlparse(product_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    handle = parsed.path.rstrip("/").split("/")[-1]
    if not handle:
        raise ValueError(f"Could not extract product handle from URL: {product_url}")

    # Fetch .json (main data)
    json_url = f"{base_url}/products/{handle}.json"
    resp = request_with_retry(json_url, session=SESSION)
    resp.raise_for_status()
    json_data = resp.json()["product"]

    # Fetch .js (availability)
    js_data = None
    try:
        time.sleep(0.5)
        js_url = f"{base_url}/products/{handle}.js"
        js_resp = request_with_retry(js_url, session=SESSION)
        js_resp.raise_for_status()
        js_data = js_resp.json()
    except Exception as e:
        print(f"[FASHION-] Could not fetch .js endpoint: {e}")
        print(f"[FASHION-] Falling back to .json availability (may show null)")

    # Basic info
    colorway = _extract_tag(json_data.get("tags", []), "color")
    json_variants = json_data.get("variants", [])
    if not json_variants:
        raise ValueError(f"Product has no variants: {product_url}")

    # Auto-detect category
    raw_tags = json_data.get("tags", [])
    if isinstance(raw_tags, str):
        raw_tags = [t.strip() for t in raw_tags.split(",")]
    product_type = json_data.get("product_type", "")
    category = detect_category(json_data["title"], product_type=product_type, tags=raw_tags)
    print(f"[FASHION-] Category: {category} (type='{product_type}')")

    # Pricing
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
        sale_price = float(json_variants[0]["price"])
        original_price = sale_price

    discount_pct = round((1 - sale_price / original_price) * 100) if original_price > sale_price else 0

    # Images
    all_image_urls = []
    seen = set()

    for img in json_data.get("images", []):
        url = img.get("src", "")
        if url:
            norm = _normalize_image_url(url)
            if norm not in seen:
                seen.add(norm)
                all_image_urls.append(url)

    if js_data:
        for img in js_data.get("images", []):
            url = img if isinstance(img, str) else img.get("src", "")
            if url:
                if url.startswith("//"):
                    url = "https:" + url
                norm = _normalize_image_url(url)
                if norm not in seen:
                    seen.add(norm)
                    all_image_urls.append(url)

        for m in js_data.get("media", []):
            if m.get("media_type") == "image":
                url = m.get("src") or (m.get("preview_image", {}) or {}).get("src", "")
                if url:
                    if url.startswith("//"):
                        url = "https:" + url
                    norm = _normalize_image_url(url)
                    if norm not in seen:
                        seen.add(norm)
                        all_image_urls.append(url)

    images = [{"url": url, "alt": f"{json_data['title']} - image {i+1}"}
              for i, url in enumerate(all_image_urls)]

    print(f"[FASHION-] Images: {len(all_image_urls)} found")

    # Sizes & availability (convert to EU)
    js_avail = {}
    if js_data:
        for v in js_data.get("variants", []):
            js_avail[str(v["id"])] = v.get("available", False)

    sizes = []
    for v in json_variants:
        vid = str(v["id"])
        if js_avail:
            in_stock = js_avail.get(vid, False)
        elif v.get("available") is not None:
            in_stock = bool(v["available"])
        else:
            in_stock = False

        raw_label = v.get("option1", v.get("title", "?"))
        eu_label = convert_to_eu(raw_label, category)

        sizes.append({
            "label": eu_label,
            "original_label": raw_label,
            "in_stock": in_stock,
            "variant_id": vid,
        })

    in_stock_count = sum(1 for s in sizes if s["in_stock"])
    any_in_stock = in_stock_count > 0
    print(f"[FASHION-] Sizes: {in_stock_count}/{len(sizes)} in stock (converted to EU)")

    return {
        "name": json_data["title"],
        "brand": json_data.get("vendor", "Unknown"),
        "slug": handle,
        "sku": json_variants[0].get("sku"),
        "colorway": colorway,
        "category": category,
        "original_price": original_price,
        "sale_price": sale_price,
        "discount_pct": discount_pct,
        "description": json_data.get("body_html", ""),
        "product_url": product_url,
        "images": images,
        "sizes": sizes,
        "in_stock": any_in_stock,
        "_raw_tags": raw_tags,
        "_base_url": base_url,
    }


def check_product_still_online(product_url: str) -> dict:
    parsed = urlparse(product_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    handle = parsed.path.rstrip("/").split("/")[-1]

    try:
        resp = request_with_retry(f"{base_url}/products/{handle}.js", session=SESSION, timeout=10)
        if resp.status_code == 404:
            return {"online": False, "in_stock": False, "sizes_available": 0, "sizes_total": 0}
        resp.raise_for_status()
        data = resp.json()

        variants = data.get("variants", [])
        available = [v for v in variants if v.get("available")]

        return {
            "online": True,
            "in_stock": len(available) > 0,
            "sizes_available": len(available),
            "sizes_total": len(variants),
        }
    except requests.exceptions.HTTPError as e:
        if e.response and e.response.status_code == 404:
            return {"online": False, "in_stock": False, "sizes_available": 0, "sizes_total": 0}
        raise


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
