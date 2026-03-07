"""Fetch product data from Naked Copenhagen (nakedcph.com).

Naked Copenhagen runs on Shopify but blocks the public .json and .js endpoints.
Instead, we parse the HTML page to extract:
- JSON-LD structured data (schema.org Product)
- Shopify product/variant data embedded in JavaScript (prices in DKK)
- Images and product metadata

Note: Prices are in Danish Krone (DKK), not EUR.
"""
import re
import json
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from utils.size_converter import convert_to_eu, detect_gender_from_tags
from utils.category_detector import detect_category
from utils.http_retry import request_with_retry

logger = logging.getLogger("naked")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
})

# DKK to EUR conversion
DKK_TO_EUR = 0.134


def fetch_naked_product(product_url: str) -> dict:
    """Fetch and parse a Naked Copenhagen product page."""
    parsed = urlparse(product_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    handle = parsed.path.rstrip("/").split("/")[-1]

    if not handle:
        raise ValueError(f"Could not extract product handle from URL: {product_url}")

    logger.info(f"Fetching Naked Copenhagen product: {handle}")

    # Fetch the HTML page
    resp = request_with_retry(product_url, session=SESSION, timeout=15)
    resp.raise_for_status()
    html = resp.text

    soup = BeautifulSoup(html, 'lxml')

    # Extract JSON-LD structured data
    json_ld = None
    for script in soup.find_all('script', {'type': 'application/ld+json'}):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and data.get('@type') == 'Product':
                json_ld = data
                logger.info("Found JSON-LD Product schema")
                break
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get('@type') == 'Product':
                        json_ld = item
                        logger.info("Found JSON-LD Product schema in array")
                        break
        except (json.JSONDecodeError, AttributeError):
            continue

    if not json_ld:
        raise ValueError("Could not find product data in JSON-LD")

    # Extract basic info from JSON-LD
    name = json_ld.get('name', 'Unknown Product')
    brand = json_ld.get('brand', {}).get('name', 'Unknown Brand') if isinstance(json_ld.get('brand'), dict) else json_ld.get('brand', 'Unknown Brand')
    description = json_ld.get('description', '')

    # Images from JSON-LD
    images = []
    json_ld_images = json_ld.get('image', [])
    
    if isinstance(json_ld_images, str):
        json_ld_images = [json_ld_images]
    elif isinstance(json_ld_images, dict):
        json_ld_images = [json_ld_images]
    
    for i, img_item in enumerate(json_ld_images):
        if isinstance(img_item, str):
            img_url = img_item
        elif isinstance(img_item, dict):
            img_url = img_item.get('url') or img_item.get('@url') or img_item.get('contentUrl', '')
        else:
            continue
        
        if not img_url:
            continue
            
        if img_url.startswith('//'):
            img_url = 'https:' + img_url
        
        images.append({"url": img_url, "alt": f"{name} - image {i+1}"})

    logger.info(f"Images from JSON-LD: {len(images)}")

    # Get currency
    currency = 'DKK'
    meta_currency = soup.find('meta', {'property': 'og:price:currency'})
    if meta_currency:
        currency = meta_currency.get('content', 'DKK')
    logger.info(f"Currency: {currency}")

    # Extract FULL variant data with availability field
    # This is the complete structure with all fields including "available"
    variant_data = None
    for script in soup.find_all('script'):
        if not script.string or '"variants"' not in script.string:
            continue
        
        # Look for the full variant array that includes "available" field
        match = re.search(
            r'"variants"\s*:\s*(\[\{"id":\d+,"title":"[^"]*".*?"available":(true|false).*?\}\])',
            script.string,
            re.DOTALL
        )
        if match:
            try:
                variant_data = json.loads(match.group(1))
                logger.info(f"Found {len(variant_data)} variants with availability data")
                break
            except json.JSONDecodeError as e:
                logger.debug(f"Failed to parse full variants: {e}")
                continue

    if not variant_data or len(variant_data) == 0:
        raise ValueError("Could not find variant data with availability")

    # Get price from first variant (in cents)
    first_variant = variant_data[0]
    sale_price_cents = first_variant.get('price', 0)
    
    # Get compare_at_price from variant or search HTML
    original_price_cents = first_variant.get('compare_at_price') or sale_price_cents
    if not first_variant.get('compare_at_price'):
        # Fallback: search in HTML
        compare_match = re.search(r'"compare_at_price"\s*:\s*(\d+)', html)
        if compare_match:
            original_price_cents = int(compare_match.group(1))
            logger.info(f"Found compare_at_price in HTML: {original_price_cents}")

    # Convert from cents to currency
    sale_price = sale_price_cents / 100.0
    original_price = original_price_cents / 100.0

    logger.info(f"Raw prices: sale={sale_price} {currency}, original={original_price} {currency}")

    # Convert DKK to EUR
    if currency == 'DKK':
        sale_price_eur = round(sale_price * DKK_TO_EUR, 2)
        original_price_eur = round(original_price * DKK_TO_EUR, 2)
        logger.info(f"Converted to EUR: sale={sale_price_eur}, original={original_price_eur}")
        sale_price = sale_price_eur
        original_price = original_price_eur

    discount_pct = round((1 - sale_price / original_price) * 100) if original_price > sale_price else 0

    # Extract sizes from variants with actual availability
    sizes = []
    for variant in variant_data:
        size_label = variant.get('title') or variant.get('public_title') or variant.get('option1', '?')
        available = variant.get('available', False)
        variant_id = str(variant.get('id', ''))
        
        sizes.append({
            "label": size_label,
            "original_label": size_label,
            "in_stock": available,
            "variant_id": variant_id,
        })

    in_stock_count = sum(1 for s in sizes if s["in_stock"])
    any_in_stock = in_stock_count > 0
    logger.info(f"Sizes: {in_stock_count}/{len(sizes)} in stock")

    # Get product type and tags
    product_type_str = ''
    type_match = re.search(r'"type"\s*:\s*"([^"]+)"', html)
    if type_match:
        product_type_str = type_match.group(1)
    
    tags = []
    tags_match = re.search(r'"tags"\s*:\s*\[([^\]]+)\]', html)
    if tags_match:
        tags_str = tags_match.group(1)
        tags = [t.strip('" ') for t in tags_str.split(',')]

    category = detect_category(name, product_type=product_type_str, tags=tags)
    logger.info(f"Category: {category}")

    gender = detect_gender_from_tags(tags=tags, name=name)
    logger.info(f"Gender: {gender}")

    # Convert sizes to EU (only for sneakers)
    for size in sizes:
        eu_label = convert_to_eu(size["original_label"], category, gender=gender)
        size["label"] = eu_label

    # Extract colorway
    colorway = None
    if ' - ' in name:
        parts = name.split(' - ')
        if len(parts) > 1:
            colorway = parts[-1].strip()

    # Get SKU
    sku = first_variant.get('sku')

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
        "product_url": product_url,
        "images": images,
        "sizes": sizes,
        "in_stock": any_in_stock,
        "_raw_tags": tags,
        "_base_url": base_url,
    }


def check_product_still_online(product_url: str) -> dict:
    """Check if a Naked Copenhagen product is still available."""
    try:
        resp = request_with_retry(product_url, session=SESSION, timeout=10)
        if resp.status_code == 404:
            return {"online": False, "in_stock": False, "sizes_available": 0, "sizes_total": 0}
        
        resp.raise_for_status()
        html = resp.text
        soup = BeautifulSoup(html, 'lxml')

        has_product = False
        for script in soup.find_all('script', {'type': 'application/ld+json'}):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Product':
                    has_product = True
                    break
            except:
                continue

        if not has_product:
            return {"online": False, "in_stock": False, "sizes_available": 0, "sizes_total": 0}

        # Try to get full variant data
        variant_data = None
        for script in soup.find_all('script'):
            if script.string and 'variants' in script.string:
                match = re.search(
                    r'"variants"\s*:\s*(\[\{"id":\d+.*?"available":(true|false).*?\}\])',
                    script.string,
                    re.DOTALL
                )
                if match:
                    try:
                        variant_data = json.loads(match.group(1))
                        break
                    except:
                        continue

        if variant_data:
            available = sum(1 for v in variant_data if v.get('available', False))
            total = len(variant_data)
            return {
                "online": True,
                "in_stock": available > 0,
                "sizes_available": available,
                "sizes_total": total,
            }
        
        return {"online": True, "in_stock": True, "sizes_available": 0, "sizes_total": 0}

    except requests.exceptions.HTTPError as e:
        if e.response and e.response.status_code == 404:
            return {"online": False, "in_stock": False, "sizes_available": 0, "sizes_total": 0}
        raise
