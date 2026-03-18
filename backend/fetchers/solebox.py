"""Fetch product data from Solebox (solebox.com).

Solebox runs on Scayle (headless commerce) and is protected by Cloudflare.
The public Scayle API is locked — instead we:
  1. Fetch the product page HTML using curl_cffi (bypasses Cloudflare TLS)
  2. Extract image public_id from JSON-LD (e.g. "02549461")
  3. Use referenceKey (Scayle variant key = image_id + size_index) as a
     unique anchor to locate the exact variants array for THIS product
  4. Parse variants, prices, stock, and images from that array

Price structure (Scayle):
  - price.withTax       = current sale price in cents (e.g. 11699 = €116.99)
  - wasPriceNumeric     = original price in cents (e.g. 12999 = €129.99)
  - stock.quantity > 0  = in stock
  - sizeMap.sizeEu      = EU size label (already converted, no mapping needed)

Note: curl_cffi must be installed (used for END Clothing too).
"""
import re
import json
import logging
from urllib.parse import urlparse
from curl_cffi import requests as cffi_requests
from utils.category_detector import detect_category
from utils.size_converter import detect_gender_from_tags

logger = logging.getLogger("solebox")

SESSION = cffi_requests.Session()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.solebox.com/",
}

_SESSION_WARMED = False


def _warm_session():
    """Hit the Solebox homepage once to acquire Cloudflare cookies."""
    global _SESSION_WARMED
    if _SESSION_WARMED:
        return
    try:
        SESSION.get("https://www.solebox.com/en-eu/", headers=HEADERS, impersonate="chrome", timeout=15)
        _SESSION_WARMED = True
        logger.debug("Solebox session warmed")
    except Exception as e:
        logger.warning(f"Session warm failed (continuing anyway): {e}")


def _cents_to_eur(cents: int | None) -> float | None:
    if cents is None:
        return None
    return round(cents / 100, 2)


def _extract_image_id(json_ld: dict) -> str | None:
    """Extract Cloudinary public_id prefix (8 digits) from JSON-LD image URL.

    Example URL: https://asset.solebox.com/images/.../02549461_1/nike-...
    Returns: "02549461"
    """
    image = json_ld.get("image", "")
    urls = []
    if isinstance(image, str):
        urls = [image]
    elif isinstance(image, list):
        urls = [i if isinstance(i, str) else i.get("url", "") for i in image]

    for url in urls:
        m = re.search(r'/(\d{8})_\d+/', url)
        if m:
            return m.group(1)
    return None


def _extract_variants_by_reference_key(html: str, image_id: str) -> list | None:
    """Find the variants array that belongs to this product.

    Strategy:
      - Scayle referenceKey = image_id + size_index, e.g. "0254946100000001"
      - Search for '"referenceKey":"<image_id>' — unique to this product
      - Walk back to find the opening '[' of the variants array
      - Walk forward to find the matching closing ']'
      - Parse and return the array
    """
    anchor = f'"referenceKey":"{image_id}'
    idx = html.find(anchor)
    if idx == -1:
        logger.debug(f"referenceKey anchor '{image_id}' not found in HTML")
        return None

    # Walk back to find '[' that opens the variants array
    # The structure is: "variants":[{..."referenceKey":"..."...},{...},...]
    search_back = html[max(0, idx - 20000):idx]
    bracket_pos = search_back.rfind('[{')
    if bracket_pos == -1:
        logger.debug("Could not find opening '[{' before referenceKey anchor")
        return None

    start = max(0, idx - 20000) + bracket_pos

    # Walk forward counting brackets to find the closing ']'
    depth = 0
    end = start
    for i, ch in enumerate(html[start:], start=start):
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    try:
        variants = json.loads(html[start:end])
        if isinstance(variants, list) and len(variants) > 0:
            logger.debug(f"Extracted {len(variants)} variants via referenceKey anchor")
            return variants
    except json.JSONDecodeError as e:
        logger.debug(f"Variants JSON parse error: {e}")

    return None


def _extract_variants_fallback(html: str) -> list | None:
    """Fallback: find variants by walking back from first 'variants' key to 'product'."""
    # Try all occurrences of '"variants":[{' (not just the first)
    for m in re.finditer(r'"variants":\[\{"id":', html):
        idx = m.start()
        start = idx + len('"variants":')
        depth = 0
        end = start
        for i, ch in enumerate(html[start:], start=start):
            if ch == '[':
                depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        try:
            variants = json.loads(html[start:end])
            if isinstance(variants, list) and len(variants) > 0:
                # Validate: a real variant has sizeMap or stock
                if any('sizeMap' in str(v) or 'stock' in v for v in variants[:3]):
                    logger.debug(f"Fallback: extracted {len(variants)} variants")
                    return variants
        except json.JSONDecodeError:
            continue
    return None


def fetch_solebox_product(product_url: str) -> dict:
    """Fetch and parse a Solebox product page."""
    parsed = urlparse(product_url)
    handle = parsed.path.rstrip("/").split("/")[-1]

    if not handle:
        raise ValueError(f"Could not extract product handle from URL: {product_url}")

    logger.info(f"Fetching Solebox product: {handle}")

    _warm_session()

    resp = SESSION.get(
        product_url,
        headers=HEADERS,
        impersonate="chrome",
        timeout=20,
    )

    if resp.status_code == 404:
        raise ValueError(f"Product not found (404): {product_url}")
    resp.raise_for_status()

    html = resp.text

    # ── Extract JSON-LD for name, brand, color, overall availability ──────────
    json_ld = None
    for match in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL):
        try:
            data = json.loads(match.group(1).strip())
            if data.get("@type") == "Product":
                json_ld = data
                break
        except (json.JSONDecodeError, AttributeError):
            continue

    if not json_ld:
        raise ValueError("Could not find Product JSON-LD on page")

    name = json_ld.get("name", "Unknown Product")
    brand_raw = json_ld.get("brand", {}).get("name", "Unknown Brand")
    brand = brand_raw.strip()
    color = json_ld.get("color", "")
    product_id = json_ld.get("productId")

    offers = json_ld.get("offers", {})
    ld_price = offers.get("price")
    ld_available = offers.get("availability", "") == "https://schema.org/InStock"

    # ── Extract images from JSON-LD or og:image ───────────────────────────────
    images = []
    ld_image = json_ld.get("image", "")
    if ld_image:
        if isinstance(ld_image, str):
            images.append({"url": ld_image, "alt": name})
        elif isinstance(ld_image, list):
            for img in ld_image:
                url = img if isinstance(img, str) else img.get("url", "")
                if url:
                    images.append({"url": url, "alt": name})

    og_images = re.findall(r'<meta property="og:image" content="([^"]+)"', html)
    seen = {i["url"] for i in images}
    for url in og_images:
        if url not in seen:
            images.append({"url": url, "alt": name})
            seen.add(url)

    logger.info(f"Images: {len(images)}")

    # ── Extract variants ──────────────────────────────────────────────────────
    # Primary: anchor on referenceKey (product-specific, unique)
    image_id = _extract_image_id(json_ld)
    variants = None

    if image_id:
        logger.debug(f"Image ID anchor: {image_id}")
        variants = _extract_variants_by_reference_key(html, image_id)

    # Fallback: scan all variants blocks and validate
    if not variants:
        logger.warning("Primary extraction failed, trying fallback")
        variants = _extract_variants_fallback(html)

    sizes = []
    sale_price = float(ld_price) if ld_price else None
    original_price = float(ld_price) if ld_price else None

    if variants:
        logger.info(f"Found {len(variants)} variants")

        for v in variants:
            stock = v.get("stock", {})
            in_stock = (stock.get("quantity", 0) > 0) or stock.get("isSellableWithoutStock", False)

            size_map = v.get("sizeMap", {})
            eu_size = size_map.get("sizeEu", {}).get("value", "")
            if not eu_size:
                eu_size = v.get("attributes", {}).get("sizeEu", {}).get("values", {}).get("label", "?")

            try:
                eu_val = float(eu_size)
                fraction = eu_val - int(eu_val)
                if fraction == 0:
                    label = f"EU {int(eu_val)}"
                elif abs(fraction - 0.333) < 0.01:
                    label = f"EU {int(eu_val)} 1/3"
                elif abs(fraction - 0.667) < 0.01 or abs(fraction - 0.666) < 0.01:
                    label = f"EU {int(eu_val)} 2/3"
                elif abs(fraction - 0.5) < 0.01:
                    label = f"EU {int(eu_val)}.5"
                else:
                    label = f"EU {eu_size}"
            except (ValueError, TypeError):
                label = f"EU {eu_size}" if eu_size else "?"

            variant_id = str(v.get("id", ""))
            ean = v.get("attributes", {}).get("ean", {}).get("values", {}).get("value", "")

            sizes.append({
                "label": label,
                "original_label": eu_size,
                "in_stock": in_stock,
                "variant_id": variant_id,
                "ean": ean,
            })

            if sale_price is None:
                price_data = v.get("price", {})
                sale_price = _cents_to_eur(price_data.get("withTax"))
                original_price = _cents_to_eur(price_data.get("wasPriceNumeric")) or sale_price

        # Use first variant for accurate pricing
        if variants:
            first_price = variants[0].get("price", {})
            sale_price = _cents_to_eur(first_price.get("withTax")) or sale_price
            original_price = _cents_to_eur(first_price.get("wasPriceNumeric")) or original_price or sale_price

    else:
        logger.warning("Could not extract variants — using JSON-LD price only, no per-size data")
        if ld_price:
            sale_price = float(ld_price)
            original_price = float(ld_price)

    if sale_price is None:
        raise ValueError("Could not determine product price")
    if original_price is None:
        original_price = sale_price

    discount_pct = round((1 - sale_price / original_price) * 100) if original_price > sale_price else 0

    any_in_stock = any(s["in_stock"] for s in sizes) if sizes else ld_available
    in_stock_count = sum(1 for s in sizes if s["in_stock"])
    logger.info(f"Sizes: {in_stock_count}/{len(sizes)} in stock")

    tags = [color] if color else []
    category = detect_category(name, tags=tags)
    gender = detect_gender_from_tags(tags=tags, name=name)
    logger.info(f"Category: {category}, Gender: {gender}")

    return {
        "name": name,
        "brand": brand,
        "slug": handle,
        "sku": str(product_id) if product_id else None,
        "colorway": color or None,
        "category": category,
        "gender": gender,
        "original_price": original_price,
        "sale_price": sale_price,
        "discount_pct": discount_pct,
        "description": "",
        "product_url": product_url,
        "images": images,
        "sizes": sizes,
        "in_stock": any_in_stock,
        "_raw_tags": tags,
    }


def check_product_still_online(product_url: str) -> dict:
    """Check if a Solebox product is still available."""
    try:
        _warm_session()
        resp = SESSION.get(
            product_url,
            headers=HEADERS,
            impersonate="chrome",
            timeout=15,
        )
        if resp.status_code == 404:
            return {"online": False, "in_stock": False, "sizes_available": 0, "sizes_total": 0}

        resp.raise_for_status()
        html = resp.text

        avail_match = re.search(r'"availability":\s*"https://schema\.org/(InStock|OutOfStock)"', html)
        if avail_match:
            in_stock = avail_match.group(1) == "InStock"
        else:
            in_stock = True

        stock_matches = re.findall(r'"quantity":(\d+)', html)
        quantities = [int(q) for q in stock_matches]
        available = sum(1 for q in quantities if q > 0)
        total = len(quantities)

        return {
            "online": True,
            "in_stock": in_stock,
            "sizes_available": available,
            "sizes_total": total,
        }

    except Exception as e:
        if "404" in str(e):
            return {"online": False, "in_stock": False, "sizes_available": 0, "sizes_total": 0}
        raise
