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

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
})


def _request_with_retry(url: str, max_retries: int = 3) -> requests.Response:
    """Make a GET request with retry on 429 rate limit."""
    for attempt in range(max_retries):
        resp = SESSION.get(url, timeout=15)
        if resp.status_code == 429:
            wait = (attempt + 1) * 3  # 3s, 6s, 9s
            print(f"[FASHION-] Rate limited, waiting {wait}s... (attempt {attempt + 1}/{max_retries})")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()  # raise the last 429
    return resp


def fetch_shopify_product(product_url: str) -> dict:
    """Fetch all product data from a Shopify product URL.

    Returns a dict with: name, brand, slug, sku, colorway, prices,
    discount_pct, description, images, sizes (with availability), in_stock.
    """
    parsed = urlparse(product_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    handle = parsed.path.rstrip("/").split("/")[-1]
    if not handle:
        raise ValueError(f"Could not extract product handle from URL: {product_url}")

    # === Fetch .json (main data source) ===
    json_url = f"{base_url}/products/{handle}.json"
    resp = _request_with_retry(json_url)
    json_data = resp.json()["product"]

    # === Fetch .js (availability source) ===
    js_data = None
    try:
        time.sleep(0.5)  # small delay to avoid rate limit
        js_url = f"{base_url}/products/{handle}.js"
        js_resp = _request_with_retry(js_url)
        js_data = js_resp.json()
    except Exception as e:
        print(f"[FASHION-] Could not fetch .js endpoint: {e}")
        print(f"[FASHION-] Falling back to .json availability (may show null)")

    # === Extract basic info ===
    colorway = _extract_tag(json_data.get("tags", []), "color")
    json_variants = json_data.get("variants", [])
    if not json_variants:
        raise ValueError(f"Product has no variants: {product_url}")

    # === Pricing ===
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

    # === Images ===
    # Combine from .json images + .js media (if available)
    all_image_urls = []
    seen = set()

    for img in json_data.get("images", []):
        url = img.get("src", "")
        if url:
            norm = _normalize_image_url(url)
            if norm not in seen:
                seen.add(norm)
                all_image_urls.append(url)

    # .js media often has more images
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

    # === Sizes & availability ===
    # Build availability map from .js (has true/false vs .json's null)
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

        sizes.append({
            "label": v.get("option1", v.get("title", "?")),
            "in_stock": in_stock,
            "variant_id": vid,
        })

    in_stock_count = sum(1 for s in sizes if s["in_stock"])
    any_in_stock = in_stock_count > 0
    print(f"[FASHION-] Sizes: {in_stock_count}/{len(sizes)} in stock")

    return {
        "name": json_data["title"],
        "brand": json_data.get("vendor", "Unknown"),
        "slug": handle,
        "sku": json_variants[0].get("sku"),
        "colorway": colorway,
        "original_price": original_price,
        "sale_price": sale_price,
        "discount_pct": discount_pct,
        "description": json_data.get("body_html", ""),
        "product_url": product_url,
        "images": images,
        "sizes": sizes,
        "in_stock": any_in_stock,
        "_raw_tags": json_data.get("tags", []),
        "_base_url": base_url,
    }


def check_product_still_online(product_url: str) -> dict:
    """Quick check if a product is still live and has stock.

    Returns: {"online": bool, "in_stock": bool, "sizes_available": int, "sizes_total": int}
    Used by the stock checker to update the database periodically.
    """
    parsed = urlparse(product_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    handle = parsed.path.rstrip("/").split("/")[-1]

    try:
        resp = SESSION.get(f"{base_url}/products/{handle}.js", timeout=10)
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


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "https://en.afew-store.com/products/asics-gel-kayano-14-white-pure-silver-1201b076-100"

    print(f"Fetching: {url}\n")
    result = fetch_shopify_product(url)
    print(f"\nName: {result['name']}")
    print(f"Brand: {result['brand']}")
    print(f"Price: \u20ac{result['sale_price']} (was \u20ac{result['original_price']}, -{result['discount_pct']}%)")
    print(f"In stock: {result['in_stock']}")
    print(f"Images: {len(result['images'])}")
    for i, img in enumerate(result['images']):
        print(f"  {i+1}. {img['url'][:120]}")
    print(f"\nSizes ({sum(1 for s in result['sizes'] if s['in_stock'])}/{len(result['sizes'])} available):")
    for s in result['sizes']:
        status = '\u2705' if s['in_stock'] else '\u274c'
        print(f"  {status} {s['label']}")

    print(f"\n--- Online check ---")
    status = check_product_still_online(url)
    print(f"Online: {status['online']}, In stock: {status['in_stock']}, Sizes: {status['sizes_available']}/{status['sizes_total']}")
