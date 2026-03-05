"""END Clothing scraper — curl_cffi with Chrome TLS impersonation.

Akamai blocks at the TLS fingerprint level. No browser can fix this
if the TLS handshake doesn't match a real browser. curl_cffi solves
this by using BoringSSL (Chrome's TLS library) to produce an
identical JA3 fingerprint to real Chrome.

This is faster, lighter, and more reliable than any browser approach.

Usage:
    from fetchers._end_worker import fetch_end_page
    data = fetch_end_page("https://www.endclothing.com/eu/product/...")

Setup:
    pip install curl_cffi beautifulsoup4 lxml
"""
import re
import json
import time
import random
import logging
from typing import Optional

from bs4 import BeautifulSoup

logger = logging.getLogger("end_worker")

_SIZE_IGNORE = {
    'size guide', 'size chart', 'find your size', 'select size',
    'choose size', 'add to bag', 'add to cart', 'notify me', 'sold out',
}

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

_IMPERSONATE_VERSIONS = [
    "chrome131",
    "chrome130",
    "chrome124",
]


def _fetch_html(url: str, max_retries: int = 3) -> str:
    """Fetch page HTML using curl_cffi with Chrome TLS impersonation.

    curl_cffi uses BoringSSL to produce Chrome's exact TLS fingerprint,
    making it indistinguishable from a real Chrome browser at the
    network level. Akamai's TLS fingerprinting cannot detect this.
    """
    from curl_cffi import requests as cffi_requests

    session = cffi_requests.Session(
        impersonate=random.choice(_IMPERSONATE_VERSIONS),
    )

    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "en-GB,en;q=0.9,en-US;q=0.8",
        "accept-encoding": "gzip, deflate, br",
        "cache-control": "max-age=0",
        "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
    }

    last_error = None
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                delay = random.uniform(2, 5) * attempt
                logger.info(f"Retry {attempt}/{max_retries} after {delay:.1f}s")
                time.sleep(delay)
                # Switch impersonation on retry
                session = cffi_requests.Session(
                    impersonate=random.choice(_IMPERSONATE_VERSIONS),
                )

            # First visit homepage to get cookies (like a real user)
            logger.info("Warming up: visiting endclothing.com")
            session.get(
                "https://www.endclothing.com",
                headers=headers,
                timeout=20,
            )
            time.sleep(random.uniform(1.0, 2.5))

            # Now fetch the actual product page
            logger.info(f"Fetching: {url}")
            headers["referer"] = "https://www.endclothing.com/"
            resp = session.get(url, headers=headers, timeout=30)

            if resp.status_code == 403:
                logger.warning(f"Got 403 on attempt {attempt + 1}")
                last_error = RuntimeError(f"HTTP 403 Forbidden")
                continue

            resp.raise_for_status()
            return resp.text

        except Exception as e:
            last_error = e
            logger.warning(f"Attempt {attempt + 1} failed: {e}")

    raise RuntimeError(
        f"Failed after {max_retries} attempts. Last error: {last_error}"
    )


def _try_next_data(html: str) -> Optional[dict]:
    """Extract product data from Next.js __NEXT_DATA__ if present."""
    soup = BeautifulSoup(html, "lxml")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return None
    try:
        data = json.loads(script.string)
        page_props = data.get("props", {}).get("pageProps", {})
        if page_props:
            logger.info("Found __NEXT_DATA__ with pageProps")
            return page_props
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _extract_json_ld(soup: BeautifulSoup) -> Optional[dict]:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict) and data.get("@graph"):
                data = data["@graph"]
            candidates = data if isinstance(data, list) else [data]
            for item in candidates:
                if isinstance(item, dict) and item.get("@type") == "Product":
                    return {
                        "name": item.get("name"),
                        "brand": (
                            item.get("brand", {}).get("name")
                            if isinstance(item.get("brand"), dict)
                            else item.get("brand")
                        ),
                        "sku": (
                            item.get("sku")
                            or item.get("productID")
                            or item.get("mpn")
                        ),
                        "description": item.get("description"),
                        "image": item.get("image"),
                        "color": item.get("color"),
                        "offers": item.get("offers"),
                    }
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _extract_images(soup: BeautifulSoup) -> list[str]:
    images = []
    seen = set()
    selectors = [
        '[data-testid*="image"] img',
        '.product-image img',
        'picture img',
        '[class*="gallery"] img',
        '[class*="Gallery"] img',
        '[class*="carousel"] img',
    ]
    for selector in selectors:
        for img in soup.select(selector):
            src = img.get("src") or img.get("data-src") or ""
            srcset = img.get("srcset", "")
            if srcset and not src:
                src = srcset.split(" ")[0]
            if src and src not in seen and "media.endclothing.com" in src:
                seen.add(src)
                images.append(src)
    if not images:
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if "media.endclothing.com" in src and src not in seen and "logo" not in src and "icon" not in src:
                seen.add(src)
                images.append(src)
    return images


def _extract_prices(soup: BeautifulSoup) -> list[dict]:
    prices = []
    price_pattern = re.compile(r"[\u20ac\u00a3$]\s*([\d,.]+)")
    selectors = '[data-testid*="price"], .price, .product-price, [class*="Price"]'
    for el in soup.select(selectors):
        text = el.get_text(strip=True)
        match = price_pattern.search(text)
        if match:
            has_strike = bool(
                el.find_parent("s") or el.find_parent("del")
                or el.find("s") or el.find("del")
            )
            prices.append({
                "text": text,
                "value": float(match.group(1).replace(",", "")),
                "hasStrike": has_strike,
            })
    return prices


def _extract_sizes(soup: BeautifulSoup) -> list[dict]:
    sizes = []
    selectors = [
        '[data-test-id="Size__Button"]',
        '[data-testid*="size"] button',
        '[class*="size"] button',
        '[class*="Size"] button',
        'button[data-size]',
        '[role="option"]',
    ]
    for selector in selectors:
        for btn in soup.select(selector):
            label = btn.get_text(strip=True)
            if not label or len(label) > 30 or label.lower() in _SIZE_IGNORE:
                continue
            disabled = (
                btn.get("disabled") is not None
                or "disabled" in btn.get("class", [])
                or btn.get("aria-disabled") == "true"
                or "out-of-stock" in btn.get("class", [])
                or "unavailable" in btn.get("class", [])
            )
            sold_out = "sold out" in label.lower()
            sizes.append({
                "label": label,
                "raw_label": label,
                "in_stock": not disabled and not sold_out,
            })
    if not sizes:
        for opt in soup.select('select option, [role="listbox"] [role="option"]'):
            label = opt.get_text(strip=True)
            if not label or len(label) > 30 or label.lower() in _SIZE_IGNORE or "select" in label.lower():
                continue
            disabled = opt.get("disabled") is not None or opt.get("aria-disabled") == "true"
            sizes.append({"label": label, "raw_label": label, "in_stock": not disabled})
    return sizes


def _extract_breadcrumbs(soup: BeautifulSoup) -> list[str]:
    crumbs = []
    selectors = '[class*="breadcrumb"] a, nav[aria-label*="breadcrumb"] a, [data-testid*="breadcrumb"] a'
    for a in soup.select(selectors):
        text = a.get_text(strip=True)
        if text and text != "Home":
            crumbs.append(text)
    return crumbs


def fetch_end_page(product_url: str) -> dict:
    """Fetch and parse an END Clothing product page.

    Uses curl_cffi to impersonate Chrome's TLS fingerprint.
    No browser needed — just HTTP requests that look exactly like Chrome.
    """
    html = _fetch_html(product_url)
    soup = BeautifulSoup(html, "lxml")

    # Check for block page
    title = soup.title.string if soup.title else ""
    body_text = soup.get_text(" ", strip=True).lower()
    if (
        "blocked" in title.lower()
        or "you have been blocked" in body_text
        or "pardon our interruption" in body_text
    ):
        raise RuntimeError(
            "Blocked by END's Akamai protection. "
            "Try again in a few minutes."
        )

    # Try __NEXT_DATA__ first
    next_data = _try_next_data(html)

    ld = _extract_json_ld(soup)
    images = _extract_images(soup)
    prices = _extract_prices(soup)
    sizes = _extract_sizes(soup)
    breadcrumbs = _extract_breadcrumbs(soup)

    name_el = soup.select_one('[data-testid="product-title"], h1.product-title, h1')
    name = name_el.get_text(strip=True) if name_el else ""

    brand_el = soup.select_one('[data-testid="product-brand"], .product-brand, a[href*="/brand/"]')
    brand = brand_el.get_text(strip=True) if brand_el else ""

    colour = ""
    colour_el = soup.select_one('[data-testid="product-colour"], .product-colour')
    if colour_el:
        colour = colour_el.get_text(strip=True)
    if not colour:
        for el in soup.find_all(["span", "p", "div"]):
            txt = el.get_text(strip=True)
            if txt.lower().startswith("colour:"):
                colour = re.sub(r"^colour:\s*", "", txt, flags=re.IGNORECASE).strip()
                break

    desc_el = soup.select_one('[data-testid="product-description"], .product-description, [class*="description"] p')
    description = str(desc_el) if desc_el else ""

    result = {
        "ld": ld or {},
        "name": name,
        "brand": brand,
        "colour": colour,
        "description": description,
        "images": images,
        "prices": prices,
        "sizes": sizes,
        "breadcrumbs": breadcrumbs,
    }

    if next_data:
        result["_next_data"] = next_data

    logger.info(
        f"Extracted: name='{name}', brand='{brand}', "
        f"images={len(images)}, sizes={len(sizes)}, prices={len(prices)}"
    )
    return result


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("Usage: python _end_worker.py <product_url>")
        sys.exit(1)
    data = fetch_end_page(sys.argv[1])
    print(json.dumps(data, indent=2))
