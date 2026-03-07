"""Fetch product data from Shopify stores (e.g., AFEW Store).

Uses two Shopify public endpoints:
- /products/{handle}.json  — rich product data (images, tags, description, pricing)
- /products/{handle}.js   — storefront data (real variant availability)

For AFEW specifically, also scrapes the product page HTML to extract
high-res packshot images from cdn.afew-store.com (the Shopify API
only returns 1 low-quality thumbnail).

These are public APIs intended for headless storefronts, not scraping.
"""
import re
import time
import logging
import requests
from urllib.parse import urlparse, unquote
from utils.size_converter import convert_to_eu, detect_gender_from_tags
from utils.category_detector import detect_category
from utils.http_retry import request_with_retry

logger = logging.getLogger("shopify")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
})

# AFEW CDN image settings
AFEW_CDN_PATTERN = re.compile(
    r'https://cdn\.afew-store\.com/assets/[^"\'\'\s>]+\.(?:jpg|webp|png)'
)
AFEW_CDN_PREFERRED_RES = "1200"  # Good balance of quality vs file size


def _normalize_price(price_str: str) -> float:
    """Convert Shopify price to float, auto-detecting cents vs currency units.
    
    Some Shopify stores return prices in cents (11995 for €119.95),
    others return them in currency units (119.95 for €119.95).
    
    Detection logic: if price > 1000, assume it's in cents and divide by 100.
    This handles the 99.9% case correctly (most sneakers are under €1000).
    """
    price = float(price_str)
    
    # If price is unreasonably high (>1000), it's likely in cents
    if price > 1000:
        logger.debug(f"Price {price} looks like cents, converting to currency units")
        return price / 100
    
    return price


def _scrape_afew_cdn_images(product_url: str) -> list[str]:
    """Scrape AFEW's custom CDN packshot images from the product HTML.

    AFEW stores their real product images on cdn.afew-store.com, not
    on Shopify's CDN. The Shopify API only returns 1 thumbnail.

    Each product has 5-6 rotation angles (packshots-0 through packshots-150)
    at multiple resolutions (300, 600, 900, 1200, 1800, 2400).

    We grab the 1200px versions — sorted by angle for consistent ordering.
    """
    try:
        resp = request_with_retry(product_url, session=SESSION, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"HTML scrape returned {resp.status_code}")
            return []

        html = resp.text
        all_urls = set(AFEW_CDN_PATTERN.findall(html))

        if not all_urls:
            logger.info("No AFEW CDN images found in HTML")
            return []

        # Filter to preferred resolution only
        preferred = [u for u in all_urls if f"/{AFEW_CDN_PREFERRED_RES}/" in u]

        # If no images at preferred res, try 2400 then take whatever we find
        if not preferred:
            preferred = [u for u in all_urls if "/2400/" in u]
        if not preferred:
            by_angle = {}
            for u in all_urls:
                m = re.search(r'packshots-(\d+)\.', u)
                angle = m.group(1) if m else "unknown"
                by_angle[angle] = u
            preferred = list(by_angle.values())

        # Sort by angle number for consistent gallery ordering
        def _angle_sort_key(url: str) -> int:
            m = re.search(r'packshots-(\d+)\.', url)
            return int(m.group(1)) if m else 999

        preferred.sort(key=_angle_sort_key)

        logger.info(f"AFEW CDN: found {len(preferred)} packshot images")
        return preferred

    except Exception as e:
        logger.warning(f"AFEW CDN image scrape failed: {e}")
        return []


def fetch_shopify_product(product_url: str) -> dict:
    parsed = urlparse(product_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    handle = parsed.path.rstrip("/").split("/")[-1]
    if not handle:
        raise ValueError(f"Could not extract product handle from URL: {product_url}")

    is_afew = "afew-store.com" in parsed.netloc

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
        logger.warning(f"Could not fetch .js endpoint: {e}")
        logger.warning(f"Falling back to .json availability (may show null)")

    # Basic info
    colorway = _extract_tag(json_data.get("tags", []), "color")
    json_variants = json_data.get("variants", [])
    if not json_variants:
        raise ValueError(f"Product has no variants: {product_url}")

    # Parse tags
    raw_tags = json_data.get("tags", [])
    if isinstance(raw_tags, str):
        raw_tags = [t.strip() for t in raw_tags.split(",")]

    # Auto-detect category
    product_type = json_data.get("product_type", "")
    category = detect_category(json_data["title"], product_type=product_type, tags=raw_tags)
    logger.info(f"Category: {category} (type='{product_type}')")

    # Detect gender for correct size conversion
    gender = detect_gender_from_tags(tags=raw_tags, name=json_data["title"])
    logger.info(f"Gender: {gender}")

    # Pricing (with auto-detection of cents vs currency units)
    original_price = None
    sale_price = None
    for v in json_variants:
        cap = v.get("compare_at_price")
        price = v.get("price")
        if cap and price:
            cap_normalized = _normalize_price(cap)
            price_normalized = _normalize_price(price)
            if cap_normalized > price_normalized:
                original_price = cap_normalized
                sale_price = price_normalized
                break

    if original_price is None:
        sale_price = _normalize_price(json_variants[0]["price"])
        original_price = sale_price

    discount_pct = round((1 - sale_price / original_price) * 100) if original_price > sale_price else 0

    # ── Images ────────────────────────────────────────────────────
    all_image_urls = []

    if is_afew:
        time.sleep(0.3)
        cdn_images = _scrape_afew_cdn_images(product_url)
        if cdn_images:
            all_image_urls = cdn_images
            logger.info(f"Using {len(cdn_images)} AFEW CDN packshot images")

    # Fallback (or non-AFEW Shopify stores): use API images
    if not all_image_urls:
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

        logger.info(f"Using {len(all_image_urls)} Shopify API images (fallback)")

    images = [{"url": url, "alt": f"{json_data['title']} - image {i+1}"}
              for i, url in enumerate(all_image_urls)]

    logger.info(f"Images: {len(all_image_urls)} total")

    # Sizes & availability (convert to EU using correct gender table)
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
        eu_label = convert_to_eu(raw_label, category, gender=gender)

        sizes.append({
            "label": eu_label,
            "original_label": raw_label,
            "in_stock": in_stock,
            "variant_id": vid,
        })

    in_stock_count = sum(1 for s in sizes if s["in_stock"])
    any_in_stock = in_stock_count > 0
    logger.info(f"Sizes: {in_stock_count}/{len(sizes)} in stock (converted to EU, gender={gender})")

    return {
        "name": json_data["title"],
        "brand": json_data.get("vendor", "Unknown"),
        "slug": handle,
        "sku": json_variants[0].get("sku"),
        "colorway": colorway,
        "category": category,
        "gender": gender,
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
