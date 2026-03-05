"""END Clothing scraper — plain HTTP with browser cookies.

Uses requests + BeautifulSoup to fetch product data from END Clothing.
Avoids Playwright/CDP entirely — no automation fingerprints for Akamai.

Cookies are sourced from the user's real Chrome browser via browser_cookie3.
If cookies are expired or missing, the user just needs to visit
endclothing.com once in Chrome to refresh them.

Usage:
    from fetchers._end_worker import fetch_end_page
    data = fetch_end_page("https://www.endclothing.com/gb/product/...")
"""
import re
import json
import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("end_worker")

# Realistic Chrome headers
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# Labels to ignore from size selectors
_SIZE_IGNORE = {
    'size guide', 'size chart', 'find your size', 'select size',
    'choose size', 'add to bag', 'add to cart', 'notify me', 'sold out',
}


def _load_cookies() -> dict:
    """Load END Clothing cookies from Chrome's cookie store.

    Returns a dict of cookies for endclothing.com.
    Falls back to empty dict if browser_cookie3 is not installed
    or cookies can't be read.
    """
    try:
        import browser_cookie3
        cj = browser_cookie3.chrome(domain_name=".endclothing.com")
        cookies = {c.name: c.value for c in cj}
        if cookies:
            logger.info(f"Loaded {len(cookies)} cookies from Chrome")
        else:
            logger.warning("No END cookies found in Chrome — visit endclothing.com first")
        return cookies
    except Exception as e:
        logger.warning(f"Could not load Chrome cookies: {e}")
        return {}


def _extract_json_ld(soup: BeautifulSoup) -> Optional[dict]:
    """Extract Product JSON-LD structured data from the page."""
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
                        "brand": item.get("brand", {}).get("name") if isinstance(item.get("brand"), dict) else item.get("brand"),
                        "sku": item.get("sku") or item.get("productID") or item.get("mpn"),
                        "description": item.get("description"),
                        "image": item.get("image"),
                        "color": item.get("color"),
                        "offers": item.get("offers"),
                    }
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _extract_images(soup: BeautifulSoup) -> list[str]:
    """Extract product image URLs from the page."""
    images = []
    seen = set()

    # Priority: Cloudinary/media.endclothing.com images
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

    # Fallback: any media.endclothing.com img
    if not images:
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if "media.endclothing.com" in src and src not in seen and "logo" not in src and "icon" not in src:
                seen.add(src)
                images.append(src)

    return images


def _extract_prices(soup: BeautifulSoup) -> list[dict]:
    """Extract price elements from the page."""
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
    """Extract size options from the page."""
    sizes = []

    # Primary: size buttons
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

    # Fallback: select/option
    if not sizes:
        for opt in soup.select('select option, [role="listbox"] [role="option"]'):
            label = opt.get_text(strip=True)
            if not label or len(label) > 30 or label.lower() in _SIZE_IGNORE or "select" in label.lower():
                continue
            disabled = opt.get("disabled") is not None or opt.get("aria-disabled") == "true"
            sizes.append({
                "label": label,
                "raw_label": label,
                "in_stock": not disabled,
            })

    return sizes


def _extract_breadcrumbs(soup: BeautifulSoup) -> list[str]:
    """Extract breadcrumb navigation links."""
    crumbs = []
    selectors = '[class*="breadcrumb"] a, nav[aria-label*="breadcrumb"] a, [data-testid*="breadcrumb"] a'
    for a in soup.select(selectors):
        text = a.get_text(strip=True)
        if text and text != "Home":
            crumbs.append(text)
    return crumbs


def fetch_end_page(product_url: str) -> dict:
    """Fetch and parse an END Clothing product page.

    Uses plain HTTP requests with Chrome cookies.
    Returns the same data structure as the old Playwright worker.

    Raises:
        RuntimeError: If blocked by Akamai or page can't be fetched.
        ValueError: If no product data could be extracted.
    """
    cookies = _load_cookies()

    session = requests.Session()
    session.headers.update(_HEADERS)
    if cookies:
        session.cookies.update(cookies)

    logger.info(f"Fetching: {product_url}")
    resp = session.get(product_url, timeout=20)

    # Check for Akamai block
    if resp.status_code == 403 or "you have been blocked" in resp.text.lower():
        raise RuntimeError(
            "Blocked by END's Akamai protection. "
            "Please visit endclothing.com in Chrome to refresh cookies, "
            "then try again. If still blocked, wait 15-30 minutes."
        )

    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    # Check if we got a real product page
    title = soup.title.string if soup.title else ""
    if "blocked" in title.lower() or "sorry" in title.lower():
        raise RuntimeError(
            "END returned a block page. Visit endclothing.com in Chrome first."
        )

    # Extract all data
    ld = _extract_json_ld(soup)
    images = _extract_images(soup)
    prices = _extract_prices(soup)
    sizes = _extract_sizes(soup)
    breadcrumbs = _extract_breadcrumbs(soup)

    # Name from DOM
    name_el = soup.select_one('[data-testid="product-title"], h1.product-title, h1')
    name = name_el.get_text(strip=True) if name_el else ""

    # Brand from DOM
    brand_el = soup.select_one('[data-testid="product-brand"], .product-brand, a[href*="/brand/"]')
    brand = brand_el.get_text(strip=True) if brand_el else ""

    # Colour from DOM
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

    # Description
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
