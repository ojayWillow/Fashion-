"""Solebox scraper - extracts product variants, stock, sizes from ngsw HTML cache."""
import re, json
from urllib.parse import unquote
from curl_cffi import requests as cffi_requests


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
        """Return clean product dict with sizes and stock."""
        sizes = []
        for v in body.get('variants', []):
            sm = v.get('sizeMap', {})
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
                'price_eur':    price.get('withTax'),
                'price_fmt':    price.get('formatted'),
            })
        return {
            'id':           body.get('id'),
            'referenceKey': body.get('referenceKey'),
            'name':         body.get('displayName'),
            'isSoldOut':    body.get('isSoldOut'),
            'totalStock':   body.get('stock'),
            'url':          body.get('url'),
            'sizes':        sizes,
        }


if __name__ == '__main__':
    scraper = SoleboxScraper()
    product = scraper.get_product(
        'nike-wmns-air-force-107-low-se-valentines-day-2026-light-pink-94471'
    )
    print(f"Product: {product['name']} | id: {product['id']} | ref: {product['referenceKey']}")
    print(f"Sold out: {product['isSoldOut']} | Total stock: {product['totalStock']}")
    print(f"\nSizes ({len(product['sizes'])} variants):")
    print(f"{'EU':<6} {'UK':<6} {'US':<6} {'CM':<6} {'Qty':<5} {'In Stock':<10} Price")
    print("-" * 55)
    for s in product['sizes']:
        print(f"{s['eu']:<6} {s['uk']:<6} {s['us']:<6} {s['cm']:<6} {s['quantity']:<5} {str(s['inStock']):<10} {s['price_fmt']}")
