"""END Clothing scraper — Camoufox anti-detect browser.

Uses Camoufox (Firefox-based) instead of Chromium + playwright-stealth.
Camoufox patches browser fingerprints at the C++ level, making it
undetectable to Akamai Bot Manager, Cloudflare, DataDome, etc.

No manual cookie management needed — the browser handles everything.

Usage:
    from fetchers._end_worker import fetch_end_page
    data = fetch_end_page("https://www.endclothing.com/gb/product/...")

First-time setup:
    pip install camoufox[geoip]
    camoufox fetch          # Windows
    python -m camoufox fetch  # macOS/Linux
"""
import re
import json
import time
import random
import logging
from typing import Optional

from bs4 import BeautifulSoup

logger = logging.getLogger("end_worker")

# Labels to ignore from size selectors
_SIZE_IGNORE = {
    'size guide', 'size chart', 'find your size', 'select size',
    'choose size', 'add to bag', 'add to cart', 'notify me', 'sold out',
}

# Random viewport sizes to look like different real devices
_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 720},
]


def _human_delay(min_s: float = 0.5, max_s: float = 2.0):
    """Sleep for a random human-like duration."""
    time.sleep(random.uniform(min_s, max_s))


def _fetch_html(url: str) -> str:
    """Launch a Camoufox anti-detect browser and fetch the page HTML.

    Camoufox is a modified Firefox that spoofs fingerprints at the C++ level.
    It rotates navigator, screen, WebGL, fonts, etc. automatically via
    BrowserForge, making each session look like a unique real device.
    """
    from camoufox.sync_api import Camoufox

    viewport = random.choice(_VIEWPORTS)

    with Camoufox(
        headless=True,
        humanize=True,          # built-in human-like mouse movement
        i_know_what_im_doing=True,  # suppress headless warning
    ) as browser:
        page = browser.new_page()

        # Set viewport to a random common resolution
        page.set_viewport_size(viewport)

        logger.info(f"Navigating to: {url}")

        # Small pre-navigation delay to mimic user opening a tab
        _human_delay(0.3, 1.0)

        page.goto(url, wait_until="domcontentloaded", timeout=45000)

        # Wait for product content to render
        try:
            page.wait_for_selector(
                'h1, [data-testid="product-title"], '
                'script[type="application/ld+json"]',
                timeout=20000
            )
        except Exception:
            logger.warning(
                "Timeout waiting for product content, "
                "proceeding with current HTML"
            )

        # Human-like delay after page load (reading the page)
        _human_delay(1.5, 3.5)

        # Optionally scroll down a bit like a real user
        try:
            page.mouse.wheel(0, random.randint(200, 500))
            _human_delay(0.5, 1.5)
        except Exception:
            pass

        html = page.content()

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
            if (
                src
                and src not in seen
                and "media.endclothing.com" in src
            ):
                seen.add(src)
                images.append(src)

    if not images:
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if (
                "media.endclothing.com" in src
                and src not in seen
                and "logo" not in src
                and "icon" not in src
            ):
                seen.add(src)
                images.append(src)

    return images


def _extract_prices(soup: BeautifulSoup) -> list[dict]:
    """Extract price elements from the page."""
    prices = []
    price_pattern = re.compile(r"[\u20ac\u00a3$]\s*([\d,.]+)")

    selectors = (
        '[data-testid*="price"], .price, '
        '.product-price, [class*="Price"]'
    )
    for el in soup.select(selectors):
        text = el.get_text(strip=True)
        match = price_pattern.search(text)
        if match:
            has_strike = bool(
                el.find_parent("s")
                or el.find_parent("del")
                or el.find("s")
                or el.find("del")
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
            if (
                not label
                or len(label) > 30
                or label.lower() in _SIZE_IGNORE
            ):
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
        for opt in soup.select(
            'select option, [role="listbox"] [role="option"]'
        ):
            label = opt.get_text(strip=True)
            if (
                not label
                or len(label) > 30
                or label.lower() in _SIZE_IGNORE
                or "select" in label.lower()
            ):
                continue
            disabled = (
                opt.get("disabled") is not None
                or opt.get("aria-disabled") == "true"
            )
            sizes.append({
                "label": label,
                "raw_label": label,
                "in_stock": not disabled,
            })

    return sizes


def _extract_breadcrumbs(soup: BeautifulSoup) -> list[str]:
    """Extract breadcrumb navigation links."""
    crumbs = []
    selectors = (
        '[class*="breadcrumb"] a, '
        'nav[aria-label*="breadcrumb"] a, '
        '[data-testid*="breadcrumb"] a'
    )
    for a in soup.select(selectors):
        text = a.get_text(strip=True)
        if text and text != "Home":
            crumbs.append(text)
    return crumbs


def fetch_end_page(product_url: str) -> dict:
    """Fetch and parse an END Clothing product page.

    Uses Camoufox anti-detect browser to render the page.
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
    if (
        "blocked" in title.lower()
        or "you have been blocked" in body_text
        or "pardon our interruption" in body_text
    ):
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
    name_el = soup.select_one(
        '[data-testid="product-title"], h1.product-title, h1'
    )
    name = name_el.get_text(strip=True) if name_el else ""

    # Brand from DOM
    brand_el = soup.select_one(
        '[data-testid="product-brand"], '
        '.product-brand, a[href*="/brand/"]'
    )
    brand = brand_el.get_text(strip=True) if brand_el else ""

    # Colour from DOM
    colour = ""
    colour_el = soup.select_one(
        '[data-testid="product-colour"], .product-colour'
    )
    if colour_el:
        colour = colour_el.get_text(strip=True)
    if not colour:
        for el in soup.find_all(["span", "p", "div"]):
            txt = el.get_text(strip=True)
            if txt.lower().startswith("colour:"):
                colour = re.sub(
                    r"^colour:\s*", "", txt, flags=re.IGNORECASE
                ).strip()
                break

    # Description
    desc_el = soup.select_one(
        '[data-testid="product-description"], '
        '.product-description, [class*="description"] p'
    )
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
