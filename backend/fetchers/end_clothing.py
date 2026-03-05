"""Fetch product data from END Clothing.

Uses requests + BeautifulSoup via _end_worker.py to scrape product pages.
No Playwright, no browser automation, no Akamai detection.

Cookies are loaded from Chrome's cookie store via browser_cookie3.
User just needs to have visited endclothing.com in Chrome recently.

Output format matches fetch_shopify_product() so the same
insert_product / insert_images / insert_sizes logic works.

Requires:
    pip install beautifulsoup4 browser_cookie3 lxml
"""
import re
import logging
from urllib.parse import urlparse
from utils.size_converter import convert_to_eu
from fetchers._end_worker import fetch_end_page

logger = logging.getLogger("end_clothing")

# Category detection
_TODDLER_WORDS = ['toddler', 'infant', 'baby', ' td ', ' td', 'td ', 'crib']
_KIDS_WORDS = ['kids', 'junior', 'youth', 'gs ', ' gs', 'grade school', 'big kid', 'little kid']
_CLOTHING_WORDS = ['hoodie', 'jacket', 'shirt', 't-shirt', 'tee', 'pants', 'jogger', 'shorts', 'sweater', 'crewneck', 'crew neck', 'pullover', 'vest', 'coat', 'parka', 'windbreaker', 'tracksuit', 'sweatshirt', 'sweatpant', 'jersey', 'polo', 'cardigan', 'fleece', 'puffer', 'anorak', 'dress', 'skirt', 'legging', 'trouser', 'cargo', 'denim', 'jeans', 'tank top', 'longsleeve', 'apparel', 'clothing']
_ACCESSORY_WORDS = ['cap', 'hat', 'beanie', 'bag', 'backpack', 'wallet', 'belt', 'sock', 'scarf', 'glove', 'sunglasses', 'watch', 'keychain', 'headband', 'wristband', 'accessory', 'accessories', 'case', 'pouch', 'tote', 'duffle']
_SNEAKER_WORDS = ['sneaker', 'shoe', 'footwear', 'runner', 'trainer', 'boot', 'slide', 'sandal', 'clog', 'mule', 'slipper', 'foam', 'dunk', 'jordan', 'air max', 'gel-', 'chuck', '550', '530', '2002r', '990', '1906', 'ultraboost', 'ozweego', 'forum', 'samba', 'gazelle', 'campus', 'old skool', 'sk8', 'classic leather']

# Labels to ignore from size selectors
_SIZE_IGNORE = {'size guide', 'size chart', 'find your size', 'select size', 'choose size', 'add to bag', 'add to cart', 'notify me', 'sold out'}


def _detect_category(name: str, breadcrumbs: list[str] = None) -> str:
    text = f" {name} {' '.join(breadcrumbs or [])} ".lower()

    if any(w in text for w in _TODDLER_WORDS):
        return 'toddler'
    if any(w in text for w in _KIDS_WORDS):
        return 'kids'
    if any(w in text for w in _ACCESSORY_WORDS):
        return 'accessories'
    if any(w in text for w in _CLOTHING_WORDS):
        return 'clothing'
    if any(w in text for w in _SNEAKER_WORDS):
        return 'sneakers'

    bc_text = ' '.join(breadcrumbs or []).lower()
    if any(w in bc_text for w in ['sneakers', 'footwear', 'shoes', 'boots']):
        return 'sneakers'
    if any(w in bc_text for w in ['clothing', 'tops', 'bottoms', 'outerwear', 'knitwear']):
        return 'clothing'
    if any(w in bc_text for w in ['accessories', 'bags', 'hats', 'socks', 'jewellery']):
        return 'accessories'

    return 'sneakers'


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")


def fetch_end_product(product_url: str) -> dict:
    """Fetch product data from an END Clothing product page.

    Uses plain HTTP requests with browser cookies — no Playwright.
    Returns the same dict format as fetch_shopify_product().
    """
    parsed = urlparse(product_url)
    if 'endclothing.com' not in parsed.netloc:
        raise ValueError(f"Not an END Clothing URL: {product_url}")

    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    # Fetch page data via requests + BeautifulSoup
    logger.info(f"Fetching END product: {clean_url}")
    product = fetch_end_page(clean_url)

    # Process extracted data
    ld = product.get('ld', {})
    name = ld.get('name') or product.get('name', 'Unknown Product')
    brand = ld.get('brand') or product.get('brand', 'Unknown')
    colorway = ld.get('color') or product.get('colour') or None
    sku = ld.get('sku') or None
    description = ld.get('description') or product.get('description', '')

    if brand:
        brand = brand.strip()

    # Pricing
    original_price = None
    sale_price = None

    offers = ld.get('offers', {})
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if offers:
        price_val = offers.get('price') or offers.get('lowPrice')
        if price_val:
            sale_price = float(price_val)

    prices = product.get('prices', [])
    if prices:
        strike_prices = [p['value'] for p in prices if p.get('hasStrike')]
        normal_prices = [p['value'] for p in prices if not p.get('hasStrike')]

        if strike_prices and normal_prices:
            original_price = max(strike_prices)
            sale_price = min(normal_prices)
        elif normal_prices:
            sale_price = sale_price or min(normal_prices)
        elif strike_prices:
            original_price = max(strike_prices)

    if sale_price is None:
        all_prices = [p['value'] for p in prices]
        if all_prices:
            sale_price = min(all_prices)
        else:
            raise ValueError(f"Could not extract any price from {product_url}")

    if original_price is None or original_price <= sale_price:
        original_price = sale_price

    discount_pct = round((1 - sale_price / original_price) * 100) if original_price > sale_price else 0

    # Images — prefer scraped Cloudinary URLs
    image_urls = product.get('images', [])
    if not image_urls:
        ld_image = ld.get('image')
        if ld_image:
            if isinstance(ld_image, str):
                ld_image = [ld_image]
            image_urls = [u for u in ld_image if u]

    images = [{"url": url, "alt": f"{name} - image {i+1}"}
              for i, url in enumerate(image_urls)]

    # Sizes
    raw_sizes = product.get('sizes', [])
    raw_sizes = [s for s in raw_sizes if s.get('label', '').lower().strip() not in _SIZE_IGNORE]

    category = _detect_category(name, product.get('breadcrumbs', []))
    logger.info(f"Category: {category}")

    sizes = []
    for s in raw_sizes:
        raw_label = s.get('raw_label', s.get('label', ''))
        label = s.get('label', raw_label)
        eu_label = convert_to_eu(label, category)

        sizes.append({
            "label": eu_label,
            "original_label": raw_label,
            "in_stock": s.get('in_stock', True),
            "variant_id": None,
        })

    in_stock_count = sum(1 for s in sizes if s['in_stock'])
    any_in_stock = in_stock_count > 0 if sizes else True
    logger.info(f"Sizes: {in_stock_count}/{len(sizes)} in stock")

    path_slug = parsed.path.rstrip('/').split('/')[-1]
    slug = re.sub(r'\.html$', '', path_slug)
    if not slug:
        slug = _slugify(name)

    return {
        "name": name,
        "brand": brand,
        "slug": slug,
        "sku": sku,
        "colorway": colorway,
        "category": category,
        "original_price": original_price,
        "sale_price": sale_price,
        "discount_pct": discount_pct,
        "description": description,
        "product_url": clean_url,
        "images": images,
        "sizes": sizes,
        "in_stock": any_in_stock,
        "shipping_cost": 11.99,
        "_base_url": "https://www.endclothing.com",
    }
