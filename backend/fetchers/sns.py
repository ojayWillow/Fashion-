"""Fetch product data from SNS (Sneakersnstuff).

SNS runs on Shopify but uses locale-prefixed URLs (/en-eu/).
_sns_worker.py handles the low-level fetching with correct URL paths.

Sizes are US format — we convert to EU using convert_to_eu().
Images use standard Shopify CDN (no custom CDN like AFEW).
EAN/GTIN data is extracted from ld+json for cross-store matching.

Output format matches fetch_shopify_product() / fetch_end_product()
so the same insert_product / insert_images / insert_sizes logic works.

Requires:
    pip install requests
"""
import re
import logging
from urllib.parse import urlparse
from utils.size_converter import convert_to_eu, detect_gender_from_tags
from utils.category_detector import detect_category
from fetchers._sns_worker import fetch_sns_page

logger = logging.getLogger("sns")


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")


def _extract_ean_map(ld_data: dict | None) -> dict:
    """Build a variant_id -> EAN/GTIN map from ld+json data.

    The ld+json ProductGroup contains hasVariant[] with gtin13/gtin
    and variant URL containing the variant ID.
    """
    ean_map = {}
    if not ld_data:
        return ean_map

    variants = ld_data.get("hasVariant", [])
    if not variants and ld_data.get("@type") == "Product":
        # Single product, not a group
        gtin = ld_data.get("gtin13") or ld_data.get("gtin") or ld_data.get("gtin12")
        sku = ld_data.get("sku")
        if gtin and sku:
            ean_map[sku] = gtin
        return ean_map

    for v in variants:
        gtin = v.get("gtin13") or v.get("gtin") or v.get("gtin12")
        if not gtin:
            continue
        # Try to extract variant ID from URL
        url = v.get("url", "")
        vid_match = re.search(r'variant=(\d+)', url)
        if vid_match:
            ean_map[vid_match.group(1)] = gtin
        # Also map by SKU
        sku = v.get("sku")
        if sku:
            ean_map[sku] = gtin

    return ean_map


def fetch_sns_product(product_url: str) -> dict:
    """Fetch product data from an SNS product page.

    Returns the same dict format as fetch_shopify_product() / fetch_end_product().
    """
    parsed = urlparse(product_url)
    if 'sneakersnstuff.com' not in parsed.netloc:
        raise ValueError(f"Not an SNS URL: {product_url}")

    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    logger.info(f"Fetching SNS product: {clean_url}")
    raw = fetch_sns_page(clean_url)

    json_data = raw["json_data"]
    js_data = raw["js_data"]
    ld_data = raw["ld_data"]
    handle = raw["handle"]

    # Basic info
    name = json_data["title"]
    brand = json_data.get("vendor", "Unknown")
    if brand:
        brand = brand.strip()

    # Tags
    raw_tags = json_data.get("tags", [])
    if isinstance(raw_tags, str):
        raw_tags = [t.strip() for t in raw_tags.split(",")]

    # Colorway from tags
    colorway = _extract_tag(raw_tags, "color")

    # SKU from first variant
    json_variants = json_data.get("variants", [])
    if not json_variants:
        raise ValueError(f"Product has no variants: {product_url}")
    sku = json_variants[0].get("sku")

    # Category detection
    product_type = json_data.get("product_type", "")
    category = detect_category(name, product_type=product_type, tags=raw_tags)
    logger.info(f"Category: {category} (type='{product_type}')")

    # Gender detection for size conversion
    gender = detect_gender_from_tags(tags=raw_tags, name=name)
    logger.info(f"Gender: {gender}")

    # Pricing — SNS has compare_at_price for sales
    original_price = None
    sale_price = None
    for v in json_variants:
        cap = v.get("compare_at_price")
        price = v.get("price")
        if cap and price:
            try:
                cap_f = float(cap)
                price_f = float(price)
                if cap_f > price_f:
                    original_price = cap_f
                    sale_price = price_f
                    break
            except (ValueError, TypeError):
                pass

    if original_price is None:
        sale_price = float(json_variants[0]["price"])
        original_price = sale_price

    discount_pct = round((1 - sale_price / original_price) * 100) if original_price > sale_price else 0

    # Images — standard Shopify CDN (no custom CDN like AFEW)
    all_image_urls = []
    seen = set()

    for img in json_data.get("images", []):
        url = img.get("src", "")
        if url:
            norm = url.split("?")[0].lower()
            if norm not in seen:
                seen.add(norm)
                all_image_urls.append(url)

    if js_data:
        for img in js_data.get("images", []):
            url = img if isinstance(img, str) else img.get("src", "")
            if url:
                if url.startswith("//"):
                    url = "https:" + url
                norm = url.split("?")[0].lower()
                if norm not in seen:
                    seen.add(norm)
                    all_image_urls.append(url)

    images = [{"url": url, "alt": f"{name} - image {i+1}"}
              for i, url in enumerate(all_image_urls)]
    logger.info(f"Images: {len(all_image_urls)} total")

    # EAN/GTIN map from ld+json
    ean_map = _extract_ean_map(ld_data)
    if ean_map:
        logger.info(f"EAN/GTIN data: {len(ean_map)} variants mapped")

    # Sizes & availability — SNS uses US sizes, must convert to EU
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

        # Attach EAN if available
        ean = ean_map.get(vid) or ean_map.get(v.get("sku", ""))

        sizes.append({
            "label": eu_label,
            "original_label": raw_label,
            "in_stock": in_stock,
            "variant_id": vid,
            "ean": ean,
        })

    in_stock_count = sum(1 for s in sizes if s["in_stock"])
    any_in_stock = in_stock_count > 0
    logger.info(f"Sizes: {in_stock_count}/{len(sizes)} in stock (US->EU, gender={gender})")

    # Description
    description = json_data.get("body_html", "")

    return {
        "name": name,
        "brand": brand,
        "slug": handle,
        "sku": sku,
        "colorway": colorway,
        "category": category,
        "gender": gender,
        "original_price": original_price,
        "sale_price": sale_price,
        "discount_pct": discount_pct,
        "description": description,
        "product_url": clean_url,
        "images": images,
        "sizes": sizes,
        "in_stock": any_in_stock,
        "_raw_tags": raw_tags,
        "_base_url": "https://www.sneakersnstuff.com",
    }


def _extract_tag(tags, prefix: str) -> str | None:
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    values = []
    for tag in tags:
        if tag.lower().startswith(f"{prefix}:"):
            values.append(tag.split(":", 1)[1].strip())
    return " / ".join(values) if values else None
