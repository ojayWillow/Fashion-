"""END Clothing scraper — Playwright with stealth.

Uses a real Chromium browser via Playwright to fetch product data.
playwright-stealth patches the browser to avoid automation detection
by Akamai Bot Manager.

No manual cookie management needed — the browser handles everything.

Usage:
    from fetchers._end_worker import fetch_end_page
    data = fetch_end_page("https://www.endclothing.com/gb/product/...")

First-time setup:
    pip install playwright playwright-stealth
    python -m playwright install chromium
"""
import re
import json
import logging
from typing import Optional

from bs4 import BeautifulSoup

logger = logging.getLogger("end_worker")

# Labels to ignore from size selectors
_SIZE_IGNORE = {
    'size guide', 'size chart', 'find your size', 'select size',
    'choose size', 'add to bag', 'add to cart', 'notify me', 'sold out',
}


def _fetch_html(url: str) -> str:
    """Launch a stealth Chromium browser and fetch the page HTML."""
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    stealth = Stealth()

    with stealth.use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="en-GB",
            timezone_id="Europe/London",
        )
        page = context.new_page()

        logger.info(f"Navigating to: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait for product content to render
        try:
            page.wait_for_selector('h1, [data-testid="product-title"], script[type="application/ld+json"]', timeout=15000)
        except Exception:
            logger.warning("Timeout waiting for product content, proceeding with current HTML")

        # Small delay for any remaining JS rendering
        page.wait_for_timeout(2000)

        html = page.content()
        browser.close()

    return html


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

    Uses Playwright stealth to render the page in a real browser.
    Returns structured product data.

    Raises:
        RuntimeError: If blocked by Akamai or page can't be fetched.
        ValueError: If no product data could be extracted.
    """
    html = _fetch_html(product_url)
    soup = BeautifulSoup(html, "lxml")

    # Check for block page
    title = soup.title.string if soup.title else ""
    body_text = soup.get_text(" ", strip=True).lower()
    if "blocked" in title.lower() or "you have been blocked" in body_text or "pardon our interruption" in body_text:
        raise RuntimeError(
            "Blocked by END's Akamai protection. "
            "Try again in a few minutes."
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
