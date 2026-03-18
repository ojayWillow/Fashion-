"""Fetch product data from Solebox (solebox.com).

Solebox runs on Scayle (headless commerce), protected by Cloudflare.
Data strategy:
  1. Fetch product page HTML with curl_cffi (bypasses Cloudflare TLS)
  2. Decode the ngsw Angular service-worker cache embedded in the HTML
     - The cache stores full API responses URL-encoded inside the HTML
     - The products/{id} blob contains variants, stock, sizes, prices
  3. Parse and normalise into the standard product dict

Price structure (Scayle):
  - price.withTax        = current price in cents (e.g. 12999 = €129.99)
  - price.wasPriceNumeric = original price in cents when on sale
  - stock.quantity > 0   = in stock
  - sizeMap.sizeEu       = EU size label
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
    if cents is None:
        return None
    return round(int(cents) / 100, 2)


def _extract_ngsw_product(html: str) -> dict | None:
    """Extract the products/{id} blob from the ngsw service-worker cache in HTML.

    The Angular app embeds serialised HTTP responses URL-encoded into the HTML.
    We find the blob matching '/v1/products/' and decode its 'body' field.
    """
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

    # ── JSON-LD for name, brand, color, images ────────────────────────────────
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

    name  = json_ld.get("name", "Unknown Product")
    brand = json_ld.get("brand", {}).get("name", "Unknown Brand").strip()
    color = json_ld.get("color", "")
    product_id = json_ld.get("productId")

    offers = json_ld.get("offers", {})
    ld_price     = offers.get("price")
    ld_available = offers.get("availability", "") == "https://schema.org/InStock"

    # ── Images ────────────────────────────────────────────────────────────────
    images = []
    ld_image = json_ld.get("image", "")
    if isinstance(ld_image, str) and ld_image:
        images.append({"url": ld_image, "alt": name})
    elif isinstance(ld_image, list):
        for img in ld_image:
            url = img if isinstance(img, str) else img.get("url", "")
            if url:
                images.append({"url": url, "alt": name})
    seen = {i["url"] for i in images}
    for url in re.findall(r'<meta property="og:image" content="([^"]+)"', html):
        if url not in seen:
            images.append({"url": url, "alt": name})
            seen.add(url)

    # ── Variants via ngsw cache ───────────────────────────────────────────────
    body = _extract_ngsw_product(html)

    sizes = []
    sale_price     = float(ld_price) if ld_price else None
    original_price = float(ld_price) if ld_price else None

    if body:
        raw_variants = body.get('variants', [])
        logger.info(f"Found {len(raw_variants)} variants via ngsw cache")

        for v in raw_variants:
            stock    = v.get('stock', {})
            in_stock = (stock.get('quantity', 0) > 0) or stock.get('isSellableWithoutStock', False)

            size_map = v.get('sizeMap', {})
            eu_raw   = size_map.get('sizeEu', {}).get('value', '')

            # Format EU size label
            try:
                eu_val   = float(eu_raw)
                frac     = eu_val - int(eu_val)
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
                label = f"EU {eu_raw}" if eu_raw else "?"

            ean = v.get('attributes', {}).get('ean', {}).get('values', {}).get('value', '')

            sizes.append({
                'label':          label,
                'original_label': eu_raw,
                'in_stock':       in_stock,
                'variant_id':     str(v.get('id', '')),
                'ean':            ean,
            })

        # Pricing from first variant
        if raw_variants:
            fp = raw_variants[0].get('price', {})
            sale_price     = _cents_to_eur(fp.get('withTax'))     or sale_price
            original_price = _cents_to_eur(fp.get('wasPriceNumeric')) or sale_price

    else:
        logger.warning("ngsw cache empty — falling back to JSON-LD price only, no per-size data")
        if ld_price:
            sale_price = original_price = float(ld_price)

    if sale_price is None:
        raise ValueError("Could not determine product price")
    if original_price is None:
        original_price = sale_price

    discount_pct  = round((1 - sale_price / original_price) * 100) if original_price > sale_price else 0
    any_in_stock  = any(s['in_stock'] for s in sizes) if sizes else ld_available
    in_stock_count = sum(1 for s in sizes if s['in_stock'])
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
        'description':    '',
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

        # fallback: JSON-LD availability
        avail = re.search(r'"availability":\s*"https://schema\.org/(InStock|OutOfStock)"', html)
        in_stock = avail.group(1) == 'InStock' if avail else True
        return {'online': True, 'in_stock': in_stock, 'sizes_available': 0, 'sizes_total': 0}

    except Exception as e:
        if '404' in str(e):
            return {'online': False, 'in_stock': False, 'sizes_available': 0, 'sizes_total': 0}
        raise
