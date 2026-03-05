"""END Clothing scraper — Scrapling StealthyFetcher.

Uses Scrapling's StealthyFetcher (Camoufox-based stealth browser) to fetch
END Clothing product pages. This bypasses Akamai Bot Manager by using a
real modified Firefox browser with fingerprint spoofing — no cookies needed,
no manual steps, no detection.

Setup (one-time):
    pip install "scrapling[fetchers]"
    scrapling install          # downloads stealth browser + dependencies

Usage:
    from fetchers._end_worker import fetch_end_page
    data = fetch_end_page("https://www.endclothing.com/eu/product/...")

Returns a dict with: name, brand, colour, description, images, prices, sizes, breadcrumbs, ld (JSON-LD).
"""
import re
import json
import logging
from typing import Optional

logger = logging.getLogger("end_worker")

# Labels to ignore from size selectors
_SIZE_IGNORE = {
    'size guide', 'size chart', 'find your size', 'select size',
    'choose size', 'add to bag', 'add to cart', 'notify me', 'sold out',
    'one size',
}


def _extract_json_ld(page) -> Optional[dict]:
    """Extract Product JSON-LD structured data from the page."""
    for script in page.css('script[type="application/ld+json"]'):
        try:
            text = script.text or ""
            data = json.loads(text)
            if isinstance(data, dict) and data.get("@graph"):
                data = data["@graph"]
            candidates = data if isinstance(data, list) else [data]
            for item in candidates:
                if isinstance(item, dict) and item.get("@type") == "Product":
                    brand_raw = item.get("brand")
                    brand = brand_raw.get("name") if isinstance(brand_raw, dict) else brand_raw
                    return {
                        "name": item.get("name"),
                        "brand": brand,
                        "sku": item.get("sku") or item.get("productID") or item.get("mpn"),
                        "description": item.get("description"),
                        "image": item.get("image"),
                        "color": item.get("color"),
                        "offers": item.get("offers"),
                    }
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _extract_images(page) -> list[str]:
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
        '[class*="slider"] img',
    ]
    for selector in selectors:
        for img in page.css(selector):
            src = img.attrib.get("src") or img.attrib.get("data-src") or ""
            srcset = img.attrib.get("srcset", "")
            if srcset and not src:
                src = srcset.split(" ")[0]
            if src and src not in seen and "media.endclothing.com" in src:
                seen.add(src)
                images.append(src)

    if not images:
        for img in page.css("img"):
            src = img.attrib.get("src", "")
            if "media.endclothing.com" in src and src not in seen and "logo" not in src and "icon" not in src:
                seen.add(src)
                images.append(src)

    return images


def _extract_prices(page) -> list[dict]:
    """Extract price elements from the page."""
    prices = []
    price_pattern = re.compile(r"[\u20ac\u00a3$\u20ac\u00a3]\s*([\d,.]+)")

    selectors = '[data-testid*="price"], .price, .product-price, [class*="Price"], [class*="price"]'
    for el in page.css(selectors):
        text = el.text.strip() if el.text else ""
        if not text:
            continue
        match = price_pattern.search(text)
        if match:
            el_html = str(el.html or "")
            has_strike = "<s" in el_html or "<del" in el_html or "line-through" in el_html
            parent = el.parent
            if parent:
                parent_html = str(parent.html or "")
                if "<s" in parent_html or "<del" in parent_html:
                    has_strike = True

            prices.append({
                "text": text,
                "value": float(match.group(1).replace(",", "")),
                "hasStrike": has_strike,
            })
    return prices


def _extract_sizes(page) -> list[dict]:
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
        for btn in page.css(selector):
            label = btn.text.strip() if btn.text else ""
            if not label or len(label) > 30 or label.lower().strip() in _SIZE_IGNORE:
                continue

            classes = btn.attrib.get("class", "")
            disabled = (
                btn.attrib.get("disabled") is not None
                or "disabled" in classes
                or btn.attrib.get("aria-disabled") == "true"
                or "out-of-stock" in classes
                or "unavailable" in classes
                or "sold-out" in classes
            )
            sold_out = "sold out" in label.lower()

            sizes.append({
                "label": label,
                "raw_label": label,
                "in_stock": not disabled and not sold_out,
            })

    if not sizes:
        for opt in page.css('select option, [role="listbox"] [role="option"]'):
            label = opt.text.strip() if opt.text else ""
            if not label or len(label) > 30 or label.lower().strip() in _SIZE_IGNORE or "select" in label.lower():
                continue
            disabled = opt.attrib.get("disabled") is not None or opt.attrib.get("aria-disabled") == "true"
            sizes.append({
                "label": label,
                "raw_label": label,
                "in_stock": not disabled,
            })

    return sizes


def _extract_breadcrumbs(page) -> list[str]:
    """Extract breadcrumb navigation links."""
    crumbs = []
    selectors = '[class*="breadcrumb"] a, nav[aria-label*="breadcrumb"] a, [data-testid*="breadcrumb"] a'
    for a in page.css(selectors):
        text = a.text.strip() if a.text else ""
        if text and text.lower() != "home":
            crumbs.append(text)
    return crumbs


def fetch_end_page(product_url: str) -> dict:
    """Fetch and parse an END Clothing product page.

    Uses Scrapling's StealthyFetcher — a Camoufox-based stealth browser
    that bypasses Akamai Bot Manager without any manual cookie steps.

    Raises:
        RuntimeError: If blocked by Akamai or page can't be fetched.
        ValueError: If no product data could be extracted.
    """
    from scrapling.fetchers import StealthyFetcher

    logger.info(f"Fetching END page with StealthyFetcher: {product_url}")

    try:
        page = StealthyFetcher.fetch(
            product_url,
            headless=True,
            network_idle=True,
            block_images=False,
        )
    except Exception as e:
        raise RuntimeError(
            f"StealthyFetcher failed to load page: {e}. "
            "Make sure you ran: pip install \"scrapling[fetchers]\" && scrapling install"
        )

    if page.status and page.status == 403:
        raise RuntimeError(
            "Blocked by END's Akamai protection (403). "
            "Try again in a few minutes — your IP may be temporarily flagged."
        )

    page_text = page.text.lower() if page.text else ""
    title_el = page.css_first("title")
    title_text = title_el.text.lower() if title_el and title_el.text else ""

    if "you have been blocked" in page_text or "access denied" in page_text:
        raise RuntimeError(
            "END returned a block page. Your IP may be temporarily flagged. "
            "Try again in 15-30 minutes."
        )

    if "blocked" in title_text or "sorry" in title_text:
        raise RuntimeError("END returned a block/error page.")

    ld = _extract_json_ld(page)
    images = _extract_images(page)
    prices = _extract_prices(page)
    sizes = _extract_sizes(page)
    breadcrumbs = _extract_breadcrumbs(page)

    name_el = page.css_first('[data-testid="product-title"], h1.product-title, h1')
    name = name_el.text.strip() if name_el and name_el.text else ""

    brand_el = page.css_first('[data-testid="product-brand"], .product-brand, a[href*="/brand/"]')
    brand = brand_el.text.strip() if brand_el and brand_el.text else ""

    colour = ""
    colour_el = page.css_first('[data-testid="product-colour"], .product-colour')
    if colour_el and colour_el.text:
        colour = colour_el.text.strip()
    if not colour:
        for el in page.css("span, p, div"):
            txt = el.text.strip() if el.text else ""
            if txt.lower().startswith("colour:"):
                colour = re.sub(r"^colour:\s*", "", txt, flags=re.IGNORECASE).strip()
                break

    desc_el = page.css_first('[data-testid="product-description"], .product-description, [class*="description"] p')
    description = str(desc_el.html) if desc_el and desc_el.html else ""

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
    print(json.dumps(data, indent=2, default=str))
