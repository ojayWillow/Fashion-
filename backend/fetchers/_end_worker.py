"""END Clothing product fetcher — Playwright headless browser.

Loads the actual product page in a real Chromium browser,
waits for all content to render (images, sizes, prices),
then extracts everything from the DOM.

This is the only reliable approach because:
- END's Algolia proxy has Akamai bot protection
- curl_cffi gets 403 or returns partial data
- A real browser renders everything: sizes, gallery, prices

Usage:
    from fetchers._end_worker import fetch_end_page
    data = fetch_end_page("https://www.endclothing.com/eu/some-product-slug")

Setup:
    pip install playwright beautifulsoup4 lxml
    python -m playwright install chromium
"""
import re
import json
import logging
from typing import Optional
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

logger = logging.getLogger("end_worker")

_REGION_CURRENCY = {
    "eu": ("EUR", "\u20ac"),
    "gb": ("GBP", "\u00a3"),
    "us": ("USD", "$"),
    "de": ("EUR", "\u20ac"),
    "fr": ("EUR", "\u20ac"),
    "row": ("EUR", "\u20ac"),
    "ca": ("CAD", "$"),
}


def _extract_region(url: str) -> str:
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    if parts:
        region = parts[0].lower()
        if region in _REGION_CURRENCY:
            return region
    return "eu"


def _build_image_url(src: str) -> str:
    if not src:
        return ""
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return "https://www.endclothing.com" + src
    return src


def _load_page(url: str) -> str:
    """Load END product page with Playwright and return fully rendered HTML."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        page = context.new_page()

        logger.info(f"Loading {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait for the product content to render
        # Try multiple selectors — END changes their markup
        try:
            page.wait_for_selector(
                "h1, [data-testid*='product'], [class*='ProductName'], [class*='product-name']",
                timeout=15000,
            )
        except Exception:
            logger.warning("Could not find product heading, page may not have loaded fully")

        # Give extra time for images/sizes to hydrate
        page.wait_for_timeout(3000)

        # Try to close cookie/popup banners that might block content
        for selector in [
            "button[data-testid*='cookie']",
            "button[class*='cookie']",
            "button[id*='cookie']",
            "[class*='CookieBanner'] button",
            "button:has-text('Accept')",
        ]:
            try:
                btn = page.query_selector(selector)
                if btn:
                    btn.click()
                    page.wait_for_timeout(500)
                    break
            except Exception:
                continue

        # Scroll down to trigger lazy-loaded content
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        page.wait_for_timeout(1000)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)

        html = page.content()
        final_url = page.url
        logger.info(f"Page loaded: {len(html)} bytes, URL: {final_url}")

        browser.close()

    return html


def _extract_next_data(soup: BeautifulSoup) -> Optional[dict]:
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag and tag.string:
        try:
            return json.loads(tag.string)
        except json.JSONDecodeError:
            pass
    return None


def _extract_ld_json(soup: BeautifulSoup) -> Optional[dict]:
    for tag in soup.find_all("script", type="application/ld+json"):
        if tag.string:
            try:
                data = json.loads(tag.string)
                if isinstance(data, list):
                    for item in data:
                        if item.get("@type") == "Product":
                            return item
                elif data.get("@type") == "Product":
                    return data
                graph = data.get("@graph", [])
                for node in graph:
                    if node.get("@type") == "Product":
                        return node
            except json.JSONDecodeError:
                continue
    return None


def _extract_images(soup: BeautifulSoup) -> list[str]:
    """Extract all product images from the rendered page."""
    images = []
    seen = set()

    # Strategy 1: Gallery/carousel images (most common pattern)
    for img in soup.select(
        "[class*='gallery'] img, "
        "[class*='Gallery'] img, "
        "[class*='carousel'] img, "
        "[class*='Carousel'] img, "
        "[class*='pdp'] img, "
        "[class*='ProductImage'] img, "
        "[class*='product-image'] img, "
        "[data-testid*='image'] img, "
        "[data-testid*='gallery'] img"
    ):
        src = img.get("src") or img.get("data-src") or ""
        src = _build_image_url(src)
        if src and "media.endclothing" in src and src not in seen:
            seen.add(src)
            images.append(src)

    # Strategy 2: Any image from END's CDN
    if len(images) < 2:
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            src = _build_image_url(src)
            if src and "media.endclothing" in src and "/catalog/product" in src and src not in seen:
                seen.add(src)
                images.append(src)

    # Strategy 3: srcset
    if len(images) < 2:
        for img in soup.find_all("img", srcset=True):
            srcset = img.get("srcset", "")
            for part in srcset.split(","):
                url = part.strip().split(" ")[0]
                url = _build_image_url(url)
                if url and "media.endclothing" in url and url not in seen:
                    seen.add(url)
                    images.append(url)

    # Strategy 4: Background images in style attributes
    for el in soup.select("[style*='media.endclothing']"):
        style = el.get("style", "")
        urls = re.findall(r'url\(["\']?(https?://media\.endclothing[^"\')]+)["\']?\)', style)
        for url in urls:
            if url not in seen:
                seen.add(url)
                images.append(url)

    # Deduplicate: remove thumbnail variants (keep largest)
    # END often has same image in different sizes like /w_200/ vs /w_600/
    cleaned = []
    base_urls = set()
    for img_url in images:
        base = re.sub(r'/[whc]_\d+/', '/', img_url)
        base = re.sub(r'\?.*$', '', base)
        if base not in base_urls:
            base_urls.add(base)
            cleaned.append(img_url)

    return cleaned


def _extract_sizes(soup: BeautifulSoup) -> list[dict]:
    """Extract sizes from the rendered page."""
    sizes = []
    seen = set()

    ignore = {'size guide', 'size chart', 'find your size', 'select size',
              'choose size', 'add to bag', 'add to cart', 'notify me',
              'sold out', 'one size', ''}

    # Strategy 1: Size buttons (most common END pattern)
    for btn in soup.select(
        "button[data-testid*='size'], "
        "button[class*='size' i], "
        "button[class*='Size'], "
        "[data-testid*='size'] button, "
        "[class*='SizeSelector'] button, "
        "[class*='size-selector'] button, "
        "[class*='SizePicker'] button"
    ):
        label = btn.get_text(strip=True)
        if label.lower() in ignore or label in seen:
            continue
        # Check if it looks like a size (number, or common size format)
        if not re.search(r'\d|\b[XSML]{1,3}\b|one.size', label, re.I):
            continue
        seen.add(label)
        # Disabled means out of stock
        is_disabled = btn.get("disabled") is not None
        classes = " ".join(btn.get("class", []))
        is_oos = is_disabled or "disabled" in classes or "unavailable" in classes or "out-of-stock" in classes or "sold-out" in classes
        sizes.append({
            "label": label,
            "raw_label": label,
            "in_stock": not is_oos,
            "stock_count": 0,
            "variant_id": btn.get("data-sku") or btn.get("value"),
        })

    # Strategy 2: Select dropdown options
    if not sizes:
        for opt in soup.select(
            "select[name*='size' i] option, "
            "select[data-testid*='size'] option, "
            "select[class*='size' i] option"
        ):
            label = opt.get_text(strip=True)
            if label.lower() in ignore or label in seen:
                continue
            if not re.search(r'\d|\b[XSML]{1,3}\b', label, re.I):
                continue
            seen.add(label)
            is_disabled = opt.get("disabled") is not None
            sizes.append({
                "label": label,
                "raw_label": label,
                "in_stock": not is_disabled,
                "stock_count": 0,
                "variant_id": opt.get("value"),
            })

    # Strategy 3: List items with size data
    if not sizes:
        for li in soup.select(
            "[class*='SizeSelector'] li, "
            "[class*='size-selector'] li, "
            "[class*='size-list'] li"
        ):
            label = li.get_text(strip=True)
            if label.lower() in ignore or label in seen:
                continue
            if not re.search(r'\d|\b[XSML]{1,3}\b', label, re.I):
                continue
            seen.add(label)
            classes = " ".join(li.get("class", []))
            is_oos = "disabled" in classes or "unavailable" in classes or "sold-out" in classes
            sizes.append({
                "label": label,
                "raw_label": label,
                "in_stock": not is_oos,
                "stock_count": 0,
                "variant_id": None,
            })

    return sizes


def _extract_prices(soup: BeautifulSoup, currency_symbol: str) -> list[dict]:
    """Extract prices from the rendered page."""
    prices = []

    # Try meta tags first (most reliable)
    price_meta = soup.find("meta", property="product:price:amount")
    if price_meta and price_meta.get("content"):
        try:
            val = float(price_meta["content"])
            prices.append({"text": f"{currency_symbol}{val:.2f}", "value": val, "hasStrike": False})
        except ValueError:
            pass

    # Look for price elements in the page
    price_pattern = re.compile(r'[\u20ac\u00a3$]\s*([\d,.]+)')

    # Sale price vs original price
    for el in soup.select(
        "[class*='price' i], "
        "[data-testid*='price' i], "
        "[class*='Price']"
    ):
        text = el.get_text(strip=True)
        match = price_pattern.search(text)
        if match:
            val_str = match.group(1).replace(",", "")
            try:
                val = float(val_str)
                # Check if this is a struck-through / original price
                is_strike = False
                if el.find("s") or el.find("del") or el.find("strike"):
                    is_strike = True
                classes = " ".join(el.get("class", []))
                if any(w in classes.lower() for w in ["original", "was", "old", "strike", "crossed", "line-through"]):
                    is_strike = True
                style = el.get("style", "")
                if "line-through" in style:
                    is_strike = True

                entry = {"text": f"{currency_symbol}{val:.2f}", "value": val, "hasStrike": is_strike}
                # Don't duplicate
                if not any(p["value"] == val and p["hasStrike"] == is_strike for p in prices):
                    prices.append(entry)
            except ValueError:
                pass

    return prices


def _extract_breadcrumbs(soup: BeautifulSoup) -> list[str]:
    crumbs = []
    for nav in soup.select("nav[aria-label*='breadcrumb' i], [class*='breadcrumb' i], [class*='Breadcrumb']"):
        for a in nav.find_all("a"):
            text = a.get_text(strip=True)
            if text and text.lower() not in ("home", "end.", "end"):
                crumbs.append(text)
        if crumbs:
            return crumbs
    return crumbs


def _extract_description(soup: BeautifulSoup) -> str:
    """Extract product description."""
    # Try structured description sections
    for sel in [
        "[class*='description' i] p",
        "[class*='Description'] p",
        "[data-testid*='description'] p",
        "[class*='ProductDetail'] p",
        "[class*='product-detail'] p",
    ]:
        paras = soup.select(sel)
        if paras:
            text = " ".join(p.get_text(strip=True) for p in paras if p.get_text(strip=True))
            if len(text) > 20:
                return text

    # Try meta description as fallback
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        return meta["content"]

    og = soup.find("meta", property="og:description")
    if og and og.get("content"):
        return og["content"]

    return ""


def _extract_colorway(soup: BeautifulSoup, name: str) -> str:
    """Extract colorway from the page."""
    # Try color-specific elements
    for sel in [
        "[class*='color' i]:not(style)",
        "[class*='Colour']",
        "[data-testid*='color' i]",
        "[data-testid*='colour' i]",
    ]:
        for el in soup.select(sel):
            text = el.get_text(strip=True)
            # Must look like a color, not a random div
            if text and len(text) < 60 and not text.startswith("http"):
                # Filter out non-color text
                if any(c in text.lower() for c in ['black', 'white', 'red', 'blue', 'green',
                    'grey', 'gray', 'olive', 'navy', 'brown', 'beige', 'cream', 'tan',
                    'pink', 'orange', 'yellow', 'purple', 'burgundy', 'gold', 'silver',
                    'multi', 'sail', 'bone', 'sand', 'khaki', 'sequoia']):
                    return text

    # Try extracting from product name (e.g. "Air Jordan 3 - Olive, Sequoia & Sail")
    color_match = re.search(r'[-–—]\s*([^|]+?)\s*$', name)
    if color_match:
        return color_match.group(1).strip()

    # Try og:title which sometimes has color info
    og_title = soup.find("meta", property="og:title")
    if og_title:
        title = og_title.get("content", "")
        color_match = re.search(r'[-–—]\s*([^|]+?)\s*[|]', title)
        if color_match:
            return color_match.group(1).strip()

    return ""


def fetch_end_page(product_url: str) -> dict:
    """Fetch product data from END Clothing using Playwright.

    Opens the page in headless Chromium, waits for full render,
    then extracts all product data from the DOM.
    """
    region = _extract_region(product_url)
    currency_code, currency_symbol = _REGION_CURRENCY.get(region, ("EUR", "\u20ac"))

    # Load page in real browser
    html = _load_page(product_url)
    soup = BeautifulSoup(html, "lxml")

    # --- Name ---
    name = ""
    h1 = soup.find("h1")
    if h1:
        name = h1.get_text(strip=True)
    if not name:
        og = soup.find("meta", property="og:title")
        if og:
            name = og.get("content", "")
    if not name:
        name = soup.title.string if soup.title else "Unknown Product"

    # --- Brand ---
    brand = ""
    # Try specific brand elements
    for sel in ["[class*='brand' i] a", "[class*='Brand'] a", "[data-testid*='brand']", "[class*='brand' i]", "[class*='Brand']"]:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            if text and len(text) < 50:
                brand = text
                break
    if not brand:
        meta = soup.find("meta", property="og:brand") or soup.find("meta", attrs={"name": "brand"})
        if meta:
            brand = meta.get("content", "")

    # --- LD+JSON (supplement) ---
    ld = _extract_ld_json(soup)
    if ld:
        if not name:
            name = ld.get("name", name)
        if not brand:
            b = ld.get("brand", {})
            brand = b.get("name", "") if isinstance(b, dict) else str(b)

    # --- Colorway ---
    colorway = _extract_colorway(soup, name)

    # --- Images ---
    images = _extract_images(soup)
    # Add LD image if we didn't find any
    if not images and ld:
        ld_img = ld.get("image", [])
        if isinstance(ld_img, str):
            ld_img = [ld_img]
        images = [_build_image_url(u) for u in ld_img if u]

    # --- Sizes ---
    sizes = _extract_sizes(soup)

    # --- Prices ---
    prices = _extract_prices(soup, currency_symbol)
    # Supplement from LD+JSON
    if not prices and ld:
        offers = ld.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price_val = offers.get("price") or offers.get("lowPrice")
        if price_val:
            prices.append({"text": f"{currency_symbol}{float(price_val):.2f}", "value": float(price_val), "hasStrike": False})

    # --- Description ---
    description = _extract_description(soup)

    # --- Breadcrumbs ---
    breadcrumbs = _extract_breadcrumbs(soup)

    # --- SKU ---
    sku = None
    if ld:
        sku = ld.get("sku")
    if not sku:
        sku_el = soup.select_one("[class*='sku' i], [data-testid*='sku' i]")
        if sku_el:
            sku = sku_el.get_text(strip=True)

    # Build the ld block for compatibility
    sale_price = None
    if prices:
        non_strike = [p["value"] for p in prices if not p["hasStrike"]]
        sale_price = min(non_strike) if non_strike else prices[0]["value"]

    result = {
        "name": name,
        "brand": brand,
        "colour": colorway,
        "description": description,
        "images": images,
        "prices": prices,
        "sizes": sizes,
        "breadcrumbs": breadcrumbs,
        "ld": {
            "name": name,
            "brand": brand,
            "sku": sku,
            "description": description,
            "image": images[0] if images else None,
            "color": colorway,
            "offers": {
                "price": sale_price,
                "priceCurrency": currency_code,
            } if sale_price else None,
        },
    }

    logger.info(
        f"Fetched: name='{name}', brand='{brand}', color='{colorway}', "
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
    print(json.dumps(data, indent=2, ensure_ascii=False))
