"""END Clothing data fetcher — Algolia search proxy.

Instead of using Playwright (blocked by Akamai), we query END's own
Algolia search proxy at search1web.endclothing.com which returns
complete product data: name, sizes, stock per size, prices, images.

Key insight: END's Algolia `footwear_size_label` array ONLY contains
sizes that are currently available/in-stock. Sold-out sizes are removed
from this array by END's system. So all labels = all available sizes.

The `sku_stock` dict maps internal child SKUs (e.g. IH0296-40015) to
stock quantities. The keys are NOT size-based — the trailing digits are
sequential IDs, not sizes. We use stock counts from the non-zero entries
matched to labels in order.

Fallback: LD+JSON from curl_cffi HTML scrape (no sizes).

Requires: pip install curl_cffi
NO Playwright, NO browser_cookie3, NO BeautifulSoup needed.
"""
import re
import json
import logging
from typing import Optional
from urllib.parse import urlparse

from curl_cffi import requests as cffi_requests

logger = logging.getLogger("end_worker")

# --- Algolia search proxy (public, from END's frontend config) ---
ALGOLIA_URL = (
    "https://search1web.endclothing.com"
    "/1/indexes/Catalog_products_v3_gb_products/query"
)
ALGOLIA_HEADERS = {
    "X-Algolia-Application-Id": "KO4W2GBINK",
    "X-Algolia-API-Key": "f0cc49399fc8922337e40fb5fc3ab2a4",
    "Content-Type": "application/json",
    "Origin": "https://www.endclothing.com",
    "Referer": "https://www.endclothing.com/",
}

MEDIA_BASE = "https://media.endclothing.com/media/catalog/product"

# Website index -> region.  1=GB(GBP), 2=US(USD), 3=EU(EUR)
REGION_PRICE_INDEX = {
    "eu": 3, "de": 3, "fr": 3, "row": 3,
    "gb": 1,
    "us": 2,
}
REGION_CURRENCY = {
    "eu": "EUR", "de": "EUR", "fr": "EUR", "row": "EUR",
    "gb": "GBP",
    "us": "USD",
}


# -- helpers -----------------------------------------------------------

def _extract_region(url: str) -> str:
    parts = urlparse(url).path.strip("/").split("/")
    if parts and parts[0].lower() in REGION_PRICE_INDEX:
        return parts[0].lower()
    return "eu"


def _extract_sku_from_url(url: str) -> Optional[str]:
    """Pull a product SKU from the END URL slug.

    Typical pattern: /eu/product-name-DN3707-202.html
    """
    slug = urlparse(url).path.rstrip("/").split("/")[-1].replace(".html", "")
    m = re.search(r"([a-zA-Z]{1,5}\d{3,5}-\d{2,4})$", slug)
    if m:
        return m.group(1).upper()
    m = re.search(r"([a-zA-Z]{1,5}\d{3,5}[-_]\d{2,4})", slug)
    if m:
        return m.group(1).upper().replace("_", "-")
    return None


def _extract_product_name_from_url(url: str) -> Optional[str]:
    """Extract a human-readable product name from the URL slug.

    Used as a fallback search query when the SKU doesn't match in Algolia
    (e.g. END changed the SKU but kept the same product page URL).
    """
    slug = urlparse(url).path.rstrip("/").split("/")[-1].replace(".html", "")
    # Remove SKU suffix
    slug = re.sub(r"-[a-zA-Z]{1,5}\d{3,5}-\d{2,4}$", "", slug)
    if not slug:
        return None
    return slug.replace("-", " ")


def _extract_sku_from_html(html: str) -> Optional[str]:
    """Extract SKU from LD+JSON in the raw HTML."""
    for m in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S
    ):
        try:
            data = json.loads(m.group(1))
            if isinstance(data, list):
                data = data[0]
            if data.get("@type") == "Product" and data.get("sku"):
                return data["sku"]
        except Exception:
            pass
    return None


# -- Algolia -----------------------------------------------------------

def _query_algolia(query: str, expect_sku: Optional[str] = None) -> Optional[dict]:
    """Query END's Algolia proxy.

    Args:
        query: Search string (SKU, product name, etc.)
        expect_sku: If provided, prefer an exact SKU match from results.

    Returns the best matching hit dict, or None.
    """
    try:
        resp = cffi_requests.post(
            ALGOLIA_URL,
            headers=ALGOLIA_HEADERS,
            json={"query": query, "hitsPerPage": 5},
            impersonate="chrome",
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning("Algolia HTTP %s", resp.status_code)
            return None

        hits = resp.json().get("hits", [])
        if not hits:
            return None

        # Prefer exact SKU match
        if expect_sku:
            for h in hits:
                if h.get("sku", "").upper() == expect_sku.upper():
                    return h

        return hits[0]

    except Exception as e:
        logger.error("Algolia query failed: %s", e)
        return None


def _find_product_in_algolia(product_url: str) -> Optional[dict]:
    """Try multiple strategies to find a product in Algolia.

    Strategy order:
    1. SKU extracted from URL
    2. SKU extracted from HTML LD+JSON (handles URL SKU mismatches)
    3. Product name extracted from URL slug (broadest fallback)
    """
    url_sku = _extract_sku_from_url(product_url)

    # Strategy 1: SKU from URL
    if url_sku:
        logger.info("Trying Algolia with URL SKU: %s", url_sku)
        hit = _query_algolia(url_sku, expect_sku=url_sku)
        if hit:
            return hit
        logger.info("URL SKU '%s' not found in Algolia", url_sku)

    # Strategy 2: SKU from HTML LD+JSON
    try:
        logger.info("Fetching HTML to extract real SKU...")
        resp = cffi_requests.get(product_url, impersonate="chrome", timeout=20)
        if resp.status_code == 200:
            html_sku = _extract_sku_from_html(resp.text)
            if html_sku and html_sku.upper() != (url_sku or "").upper():
                logger.info("HTML SKU differs from URL: %s vs %s", html_sku, url_sku)
                hit = _query_algolia(html_sku, expect_sku=html_sku)
                if hit:
                    return hit
    except Exception as e:
        logger.warning("HTML fetch for SKU failed: %s", e)

    # Strategy 3: Product name from URL slug
    product_name = _extract_product_name_from_url(product_url)
    if product_name:
        logger.info("Trying Algolia with product name: '%s'", product_name)
        hit = _query_algolia(product_name)
        if hit:
            logger.info("Found via name search: %s (SKU: %s)", hit.get("name"), hit.get("sku"))
            return hit

    return None


def _build_image_urls(hit: dict) -> list[str]:
    gallery = hit.get("media_gallery", [])
    urls = []
    for path in gallery:
        if path.startswith("http"):
            urls.append(path)
        else:
            urls.append(f"{MEDIA_BASE}{path}")
    return urls


def _parse_sizes(hit: dict) -> list[dict]:
    """Extract available sizes from Algolia hit.

    END's Algolia `footwear_size_label` (and `size`) arrays ONLY contain
    sizes that are currently available on the website. Sold-out sizes are
    removed from these arrays. Therefore all labels = all in-stock sizes.

    The `sku_stock` dict maps internal child SKU codes to stock quantities.
    Keys like 'IH0296-40015' use sequential IDs, NOT the size number.
    We extract non-zero stock counts (sorted by key) and match them to
    labels in order to get approximate per-size quantities.
    """
    labels = hit.get("footwear_size_label") or hit.get("size") or []

    if not labels:
        return []

    # Extract non-zero stock counts from sku_stock, sorted by key
    sku_stock = hit.get("sku_stock", {})
    nonzero_stocks = [
        v for _, v in sorted(sku_stock.items())
        if v > 0
    ]

    sizes: list[dict] = []
    for i, label in enumerate(labels):
        # Match stock counts to labels in order (both are ordered by size)
        stock_count = nonzero_stocks[i] if i < len(nonzero_stocks) else 0

        sizes.append({
            "label": label,
            "raw_label": label,
            "in_stock": True,  # All labels in the array are available
            "stock_count": stock_count,
            "variant_id": None,
        })

    return sizes


# -- HTML fallback -----------------------------------------------------

def _fallback_html(url: str) -> Optional[dict]:
    """Scrape LD+JSON + image URLs from the product page HTML.

    Returns basic product info (no sizes — those require Algolia).
    """
    try:
        resp = cffi_requests.get(url, impersonate="chrome", timeout=20)
        if resp.status_code != 200:
            return None
        html = resp.text

        ld: dict = {}
        for m in re.finditer(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
            html,
            re.S,
        ):
            try:
                data = json.loads(m.group(1))
                if isinstance(data, list):
                    data = data[0]
                if data.get("@type") == "Product":
                    ld = data
                    break
            except Exception:
                continue

        images = list(
            dict.fromkeys(
                re.findall(
                    r"(https://media\.endclothing\.com/media/catalog/product/[^\"'\\]+\.jpg)",
                    html,
                )
            )
        )

        offers = ld.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        price = None
        if offers.get("price"):
            try:
                price = float(offers["price"])
            except (ValueError, TypeError):
                pass

        return {
            "name": ld.get("name", "Unknown Product"),
            "brand": ld.get("brand", "Unknown"),
            "sku": ld.get("sku"),
            "colour": ld.get("color"),
            "description": ld.get("description", ""),
            "price": price,
            "images": images,
        }
    except Exception as e:
        logger.error("HTML fallback failed: %s", e)
        return None


# -- public entry point ------------------------------------------------

def fetch_end_page(product_url: str) -> dict:
    """Fetch END product data. Algolia first, HTML fallback.

    Returns a dict with keys that ``end_clothing.py`` expects:
        ld, images, sizes, prices, breadcrumbs,
        name, brand, colour, description
    """
    region = _extract_region(product_url)
    price_idx = REGION_PRICE_INDEX.get(region, 3)
    currency = REGION_CURRENCY.get(region, "EUR")

    # 1. Find product in Algolia (tries SKU from URL, HTML, then name)
    hit = _find_product_in_algolia(product_url)

    if hit:
        logger.info("Algolia OK: %s | %s", hit.get("name"), hit.get("sku"))

        images = _build_image_urls(hit)
        sizes = _parse_sizes(hit)

        full_price = hit.get(f"full_price_{price_idx}")
        final_price = hit.get(f"final_price_{price_idx}")

        prices: list[dict] = []
        if full_price and final_price and full_price > final_price:
            prices.append({"value": float(full_price), "hasStrike": True})
            prices.append({"value": float(final_price), "hasStrike": False})
        elif final_price:
            prices.append({"value": float(final_price), "hasStrike": False})
        elif full_price:
            prices.append({"value": float(full_price), "hasStrike": False})

        desc_clean = hit.get("description_markdown") or re.sub(
            r"<[^>]+>", "", hit.get("description", "")
        ).strip()

        return {
            "ld": {
                "name": hit.get("name"),
                "brand": hit.get("brand"),
                "sku": hit.get("sku"),
                "color": hit.get("actual_colour"),
                "description": desc_clean,
                "offers": {
                    "price": final_price or full_price,
                    "priceCurrency": currency,
                },
                "image": images[:1],
            },
            "images": images,
            "sizes": sizes,
            "prices": prices,
            "breadcrumbs": hit.get("department_hierarchy", []),
            "name": hit.get("name"),
            "brand": hit.get("brand"),
            "colour": hit.get("actual_colour"),
            "description": desc_clean,
            "gender": hit.get("gender"),
            "categories": hit.get("categories", []),
            "stock_total": hit.get("stock", 0),
            "sale_percentage": hit.get("sale_percentage"),
            "source": "algolia",
        }

    # 2. Fallback to HTML scrape (no sizes available)
    logger.warning("Algolia miss — falling back to HTML scrape")
    fb = _fallback_html(product_url)
    if not fb:
        raise RuntimeError(f"Could not fetch product data from {product_url}")

    prices = []
    if fb["price"]:
        prices.append({"value": fb["price"], "hasStrike": False})

    return {
        "ld": {
            "name": fb["name"],
            "brand": fb["brand"],
            "sku": fb["sku"],
            "color": fb["colour"],
            "description": fb["description"],
            "offers": (
                {"price": fb["price"], "priceCurrency": currency}
                if fb["price"]
                else {}
            ),
            "image": fb["images"][:1],
        },
        "images": fb["images"],
        "sizes": [],
        "prices": prices,
        "breadcrumbs": [],
        "name": fb["name"],
        "brand": fb["brand"],
        "colour": fb["colour"],
        "description": fb["description"],
        "source": "html_fallback",
    }


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    url = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "https://www.endclothing.com/eu/air-jordan-3-retro-og-rt-sneaker-dn3707-202.html"
    )
    data = fetch_end_page(url)
    print(
        json.dumps(
            {
                "source": data.get("source"),
                "name": data["name"],
                "brand": data["brand"],
                "sku": data["ld"]["sku"],
                "colour": data["colour"],
                "images": len(data["images"]),
                "sizes": len(data["sizes"]),
                "sizes_detail": [
                    {"label": s["label"], "in_stock": s["in_stock"], "qty": s["stock_count"]}
                    for s in data["sizes"]
                ],
                "prices": data["prices"],
            },
            indent=2,
        )
    )
