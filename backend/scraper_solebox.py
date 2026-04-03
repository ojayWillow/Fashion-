"""Solebox scraper - extracts product variants, stock, sizes from ngsw HTML cache.

Price note:
  All prices in the ngsw cache are in CENTS (Scayle/Shopify convention).
  e.g. withTax=12074 means €120.74

  Per-variant price (v['price']['withTax']) is the individual shelf price and
  does NOT reflect product-level sales or promotions.

  The correct sale price is at the product level:
    body['priceRange']['min']['withTax']        -> lowest sale price in cents
    body['priceRange']['min']['wasPriceNumeric'] -> original/RRP in cents
    body['price']['withTax']                    -> fallback if no priceRange

  Always divide by 100 before storing or returning.
"""
import re, json
from urllib.parse import unquote
from curl_cffi import requests as cffi_requests


def _cents_to_eur(val) -> float | None:
    """Convert Scayle ngsw cents value to euros. Returns None if val is None."""
    if val is None:
        return None
    return round(int(val) / 100, 2)


class SoleboxScraper:
    BASE = "https://www.solebox.com/en-eu"

    def __init__(self):
        self.session = cffi_requests.Session()
        # warm session for Cloudflare
        self.session.get(f"{self.BASE}/", impersonate="chrome", timeout=15)

    def get_product(self, slug: str) -> dict:
        """Fetch product page and extract full product data from ngsw cache.
        slug: e.g. 'nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471'
        """
        url = f"{self.BASE}/p/{slug}"
        resp = self.session.get(url, impersonate="chrome", timeout=20)
        resp.raise_for_status()
        return self._parse_html(resp.text)

    def _parse_html(self, html: str) -> dict:
        """Extract all ngsw-cached API blobs and return the products one."""
        for m in re.finditer(r'api\.solebox\.com[^"\s]{20,}', html):
            decoded = unquote(m.group())
            # only process the products/{id} blob (has variants)
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
            body = json.loads(body_str[:end])
            return self._normalize(body)
        raise ValueError("Product data not found in HTML ngsw cache")

    def _normalize(self, body: dict) -> dict:
        """Return clean product dict with sizes and stock.

        Price extraction order (product-level, NOT per-variant):
          1. body['priceRange']['min'] -- reflects actual sale/promotion price
          2. body['price']             -- fallback if no priceRange

        Per-variant price (v['price']['withTax']) is included in each size entry
        for reference but should NOT be used as the product price -- it does not
        reflect product-level promotions.
        """
        # ── Product-level sale price (correct) ──────────────────────────────
        sale_price_eur     = None
        original_price_eur = None

        price_range = body.get('priceRange', {})
        range_min   = price_range.get('min', {})
        if range_min.get('withTax') is not None:
            sale_price_eur     = _cents_to_eur(range_min['withTax'])
            original_price_eur = _cents_to_eur(range_min.get('wasPriceNumeric')) or sale_price_eur
        else:
            product_price = body.get('price', {})
            if product_price.get('withTax') is not None:
                sale_price_eur     = _cents_to_eur(product_price['withTax'])
                original_price_eur = _cents_to_eur(product_price.get('wasPriceNumeric')) or sale_price_eur

        # ── Per-variant sizes ────────────────────────────────────────────────
        sizes = []
        for v in body.get('variants', []):
            sm    = v.get('sizeMap', {})
            stock = v.get('stock', {})
            price = v.get('price', {})
            sizes.append({
                'referenceKey': v.get('referenceKey'),
                'eu':           sm.get('sizeEu', {}).get('value'),
                'uk':           sm.get('sizeUk', {}).get('value'),
                'us':           sm.get('sizeUs', {}).get('value'),
                'cm':           sm.get('sizeCm', {}).get('value'),
                'quantity':     stock.get('quantity', 0),
                'inStock':      stock.get('quantity', 0) > 0,
                # price_eur is per-variant shelf price in euros (cents / 100)
                # Use only for display, not as the product sale price
                'price_eur':    _cents_to_eur(price.get('withTax')),
                'price_fmt':    price.get('formatted'),
            })

        return {
            'id':                 body.get('id'),
            'referenceKey':      body.get('referenceKey'),
            'name':               body.get('displayName'),
            'isSoldOut':          body.get('isSoldOut'),
            'totalStock':         body.get('stock'),
            'url':                body.get('url'),
            'sale_price_eur':     sale_price_eur,      # product-level sale price in euros
            'original_price_eur': original_price_eur,  # original/RRP in euros
            'sizes':              sizes,
        }


if __name__ == '__main__':
    scraper = SoleboxScraper()
    product = scraper.get_product(
        'nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471'
    )
    print(f"Product: {product['name']} | id: {product['id']} | ref: {product['referenceKey']}")
    print(f"Sold out: {product['isSoldOut']} | Total stock: {product['totalStock']}")
    print(f"Sale price: \u20ac{product['sale_price_eur']}  |  Original: \u20ac{product['original_price_eur']}")
    print(f"\nSizes ({len(product['sizes'])} variants):")
    print(f"{'EU':<6} {'UK':<6} {'US':<6} {'CM':<6} {'Qty':<5} {'In Stock':<10} Price")
    print("-" * 55)
    for s in product['sizes']:
        print(f"{str(s['eu']):<6} {str(s['uk']):<6} {str(s['us']):<6} {str(s['cm']):<6} {s['quantity']:<5} {str(s['inStock']):<10} €{s['price_eur']}")
