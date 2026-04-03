"""Fetch product data from Solebox (solebox.com).

Solebox runs on Scayle (headless commerce), protected by Cloudflare.
Data strategy:
  1. Fetch product page HTML with curl_cffi (bypasses Cloudflare TLS)
  2. Decode the ngsw Angular service-worker cache embedded in the HTML
     - The cache stores full API responses URL-encoded inside the HTML
     - The products/{id} blob contains variants, stock, sizes, prices
  3. Parse and normalise into the standard product dict

Image strategy:
  Solebox CDN serves images from asset.solebox.com/images/ with Cloudinary transforms.
  Full-size product images use the w_680,h_680 transform.
  We extract the product's own image set by:
    1. Finding the product image ID from the first JSON-LD image URL (e.g. "02481113")
    2. Collecting all w_680 URLs in the HTML that contain that same image ID
  This reliably gets all angles (front, back, side etc.) without false positives.

Price sources (two separate flows — do NOT mix them up):
  SOURCE A — ngsw cache (preferred, has per-size data):
    - price.withTax         = current price in CENTS (e.g. 21399 = €213.99)
    - price.wasPriceNumeric = original price in CENTS when on sale
    - Always use _cents_to_eur() to convert.

  SOURCE B — JSON-LD <offers> block (fallback, no per-size data):
    - offers.price          = current price already in EUROS as a float (e.g. 213.99)
    - Do NOT divide by 100 — use as-is.
    - Only used when ngsw cache extraction fails.

  stock.quantity > 0    = in stock
  sizeMap.sizeEu        = EU size label
"""
import re
import json
import logging
from urllib.parse import urlparse, unquote
from curl_cffi import requests as cffi_requests
from utils.category_detector import detect_category
from utils.size_converter import detect_gender_from_tags

logger = logging.getLogger("solebox")

SESSION = cffi_requests.Session()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.solebox.com/",
}

_SESSION_WARMED = False


def _warm_session():
    global _SESSION_WARMED
    if _SESSION_WARMED:
        return
    try:
        SESSION.get("https://www.solebox.com/en-eu/", headers=HEADERS, impersonate="chrome", timeout=15)
        _SESSION_WARMED = True
        logger.debug("Solebox session warmed")
    except Exception as e:
        logger.warning(f"Session warm failed (continuing anyway): {e}")


def _cents_to_eur(cents) -> float | None:
    """Convert Scayle ngsw cache prices from cents to euros.
    ONLY use this for ngsw cache prices. JSON-LD prices are already in euros.
    """
    if cents is None:
        return None
    return round(int(cents) / 100, 2)


def _extract_ngsw_product(html: str) -> dict | None:
    """Extract the products/{id} blob from the ngsw service-worker cache in HTML."""
    for m in re.finditer(r'api\.solebox\.com[^"\s]{20,}', html):
        decoded = unquote(m.group())
        if '/v1/products/' not in decoded:
            continue
        body_idx = decoded.find('"body":')
        if body_idx < 0:
            continue
        body_str = decoded[body_idx + 7:]
        depth, end = 0, 0
        for i, ch in enumerate(body_str):
            if ch == '{': depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if not end:
            continue
        try:
            body = json.loads(body_str[:end])
            if body.get('variants'):
                logger.debug(f"ngsw cache: found product id={body.get('id')} with {len(body['variants'])} variants")
                return body
        except json.JSONDecodeError as e:
            logger.debug(f"ngsw body parse error: {e}")
    return None


def _extract_product_images(html: str, name: str, json_ld: dict) -> list:
    """Extract full-size product images from asset.solebox.com."""
    images = []
    seen = set()

    def add(url):
        if url and url not in seen:
            seen.add(url)
            images.append({"url": url, "alt": name})

    ld_image = json_ld.get("image", "")
    first_url = ld_image if isinstance(ld_image, str) else (ld_image[0] if isinstance(ld_image, list) and ld_image else "")

    image_id = None
    id_match = re.search(r'/images/[^/]+/([0-9]{8})_', first_url)
    if id_match:
        image_id = id_match.group(1)
        logger.info(f"Solebox product image ID: {image_id}")

    if image_id:
        pattern = re.compile(
            r'(https://asset\.solebox\.com/images/[^\s"]+w_680[^\s"]*/' + re.escape(image_id) + r'_[0-9]+/[^\s"]+)',
            re.IGNORECASE,
        )
        for url in pattern.findall(html):
            add(url)
        logger.info(f"Found {len(images)} full-size images for product ID {image_id}")

    if not images:
        logger.warning("Could not find w_680 images, falling back to JSON-LD image")
        if isinstance(ld_image, str) and ld_image:
            add(ld_image)
        elif isinstance(ld_image, list):
            for img in ld_image:
                url = img if isinstance(img, str) else img.get("url", "")
                add(url)

    return images


def fetch_solebox_product(product_url: str) -> dict:
    """Fetch and parse a Solebox product page."""
    parsed = urlparse(product_url)
    handle = parsed.path.rstrip("/").split("/")[-1]
    if not handle:
        raise ValueError(f"Could not extract product handle from URL: {product_url}")

    logger.info(f"Fetching Solebox product: {handle}")
    _warm_session()

    resp = SESSION.get(product_url, headers=HEADERS, impersonate="chrome", timeout=20)
    if resp.status_code == 404:
        raise ValueError(f"Product not found (404): {product_url}")
    resp.raise_for_status()
    html = resp.text

    # ── JSON-LD: name, brand, color, description, fallback price ─────────────
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

    name        = json_ld.get("name", "Unknown Product")
    brand       = json_ld.get("brand", {}).get("name", "Unknown Brand").strip()
    color       = json_ld.get("color", "")
    product_id  = json_ld.get("productId")
    description = json_ld.get("description", "").strip()

    offers       = json_ld.get("offers", {})
    ld_price_raw = offers.get("price")
    ld_available = offers.get("availability", "") == "https://schema.org/InStock"

    # JSON-LD price is already in euros (e.g. 213.99) — do NOT divide by 100
    ld_price = round(float(ld_price_raw), 2) if ld_price_raw is not None else None
    logger.info(f"JSON-LD price (euros, fallback only): {ld_price}")

    # ── Images ────────────────────────────────────────────────────────────
    images = _extract_product_images(html, name, json_ld)

    # ── Variants + prices via ngsw cache (prices in CENTS here) ──────────────
    body = _extract_ngsw_product(html)

    sizes = []
    # Default to JSON-LD euro price; will be overridden by ngsw cents if cache found
    sale_price     = ld_price
    original_price = ld_price

    if body:
        raw_variants = body.get('variants', [])
        logger.info(f"Found {len(raw_variants)} variants via ngsw cache")

        for v in raw_variants:
            stock    = v.get('stock', {})
            in_stock = (stock.get('quantity', 0) > 0) or stock.get('isSellableWithoutStock', False)

            size_map = v.get('sizeMap', {})
            eu_raw   = size_map.get('sizeEu', {}).get('value', '')

            if not eu_raw or str(eu_raw).strip() in ('', 'null', 'None'):
                label = "One Size"
            else:
                try:
                    eu_val = float(eu_raw)
                    frac   = eu_val - int(eu_val)
                    if frac == 0:
                        label = f"EU {int(eu_val)}"
                    elif abs(frac - 0.5) < 0.01:
                        label = f"EU {int(eu_val)}.5"
                    elif abs(frac - 0.333) < 0.01:
                        label = f"EU {int(eu_val)} 1/3"
                    elif abs(frac - 0.667) < 0.01:
                        label = f"EU {int(eu_val)} 2/3"
                    else:
                        label = f"EU {eu_raw}"
                except (ValueError, TypeError):
                    label = f"EU {eu_raw}"

            ean = v.get('attributes', {}).get('ean', {}).get('values', {}).get('value', '')

            sizes.append({
                'label':          label,
                'original_label': eu_raw,
                'in_stock':       in_stock,
                'variant_id':     str(v.get('id', '')),
                'ean':            ean,
            })

        if raw_variants:
            fp = raw_variants[0].get('price', {})
            # ngsw prices are in CENTS — convert with _cents_to_eur()
            cents_sale     = fp.get('withTax')
            cents_original = fp.get('wasPriceNumeric')

            logger.info(f"ngsw raw price cents: withTax={cents_sale}, wasPriceNumeric={cents_original}")

            if cents_sale is not None:
                sale_price = _cents_to_eur(cents_sale)
                logger.info(f"ngsw sale_price (converted from cents): €{sale_price}")
            if cents_original is not None:
                original_price = _cents_to_eur(cents_original)
            # Not on sale: original == sale
            if original_price is None:
                original_price = sale_price

    else:
        logger.warning("ngsw cache empty — using JSON-LD price as-is (already in euros), no per-size data")

    if sale_price is None:
        raise ValueError("Could not determine product price")
    if original_price is None:
        original_price = sale_price

    discount_pct   = round((1 - sale_price / original_price) * 100) if original_price > sale_price else 0
    any_in_stock   = any(s['in_stock'] for s in sizes) if sizes else ld_available
    in_stock_count = sum(1 for s in sizes if s['in_stock'])
    logger.info(f"Final price: sale=€{sale_price} original=€{original_price} discount={discount_pct}%")
    logger.info(f"Sizes: {in_stock_count}/{len(sizes)} in stock")

    tags     = [color] if color else []
    category = detect_category(name, tags=tags)
    gender   = detect_gender_from_tags(tags=tags, name=name)

    return {
        'name':           name,
        'brand':          brand,
        'slug':           handle,
        'sku':            str(product_id) if product_id else None,
        'colorway':       color or None,
        'category':       category,
        'gender':         gender,
        'original_price': original_price,
        'sale_price':     sale_price,
        'discount_pct':   discount_pct,
        'description':    description,
        'product_url':    product_url,
        'images':         images,
        'sizes':          sizes,
        'in_stock':       any_in_stock,
        '_raw_tags':      tags,
    }


def check_product_still_online(product_url: str) -> dict:
    """Check if a Solebox product is still available."""
    try:
        _warm_session()
        resp = SESSION.get(product_url, headers=HEADERS, impersonate="chrome", timeout=15)
        if resp.status_code == 404:
            return {'online': False, 'in_stock': False, 'sizes_available': 0, 'sizes_total': 0}
        resp.raise_for_status()
        html = resp.text

        body = _extract_ngsw_product(html)
        if body:
            variants  = body.get('variants', [])
            available = sum(1 for v in variants if v.get('stock', {}).get('quantity', 0) > 0)
            return {
                'online':          True,
                'in_stock':        available > 0,
                'sizes_available': available,
                'sizes_total':     len(variants),
            }

        avail = re.search(r'"availability":\s*"https://schema\.org/(InStock|OutOfStock)"', html)
        in_stock = avail.group(1) == 'InStock' if avail else True
        return {'online': True, 'in_stock': in_stock, 'sizes_available': 0, 'sizes_total': 0}

    except Exception as e:
        if '404' in str(e):
            return {'online': False, 'in_stock': False, 'sizes_available': 0, 'sizes_total': 0}
        raise
