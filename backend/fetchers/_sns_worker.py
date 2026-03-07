"""Low-level SNS (Sneakersnstuff) data fetcher.

SNS runs on Shopify (sns-prod.myshopify.com) but uses locale-prefixed
URLs: /en-eu/products/{handle}.json and .js

SNS has anti-bot protection that blocks plain requests — we use
curl_cffi with browser impersonation (same approach as _end_worker.py).

Data sources on SNS product pages:
1. /en-eu/products/{handle}.json — standard Shopify product data
2. /en-eu/products/{handle}.js  — real-time variant availability
3. application/ld+json — Schema.org ProductGroup with GTINs/EANs

Sizes are in US format — caller must convert to EU using convert_to_eu().

Requires: pip install curl_cffi
"""
import re
import json
import time
import logging
from urllib.parse import urlparse

from curl_cffi import requests as cffi_requests

logger = logging.getLogger("sns_worker")

SNS_BASE = "https://www.sneakersnstuff.com"
SNS_LOCALE = "/en-eu"


def _extract_handle_from_url(product_url: str) -> str:
    """Extract the product handle from an SNS URL.

    Handles URLs like:
      https://www.sneakersnstuff.com/en-eu/products/some-product-handle
      https://www.sneakersnstuff.com/products/some-product-handle
    """
    parsed = urlparse(product_url)
    path = parsed.path.rstrip("/")
    path = re.sub(r'^/en-[a-z]{2}', '', path)
    parts = path.split("/")
    for i, part in enumerate(parts):
        if part == "products" and i + 1 < len(parts):
            return parts[i + 1]
    raise ValueError(f"Could not extract product handle from SNS URL: {product_url}")


def _cffi_get(url: str, timeout: int = 15):
    """GET with curl_cffi browser impersonation to bypass anti-bot."""
    return cffi_requests.get(
        url,
        impersonate="chrome",
        timeout=timeout,
        headers={
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "en-EU,en;q=0.9",
        },
    )


def _fetch_json_endpoint(handle: str) -> dict:
    """Fetch /en-eu/products/{handle}.json — main product data."""
    url = f"{SNS_BASE}{SNS_LOCALE}/products/{handle}.json"
    logger.info(f"Fetching SNS .json: {url}")
    resp = _cffi_get(url)
    resp.raise_for_status()
    return resp.json()["product"]


def _fetch_js_endpoint(handle: str) -> dict | None:
    """Fetch /en-eu/products/{handle}.js — real-time availability."""
    url = f"{SNS_BASE}{SNS_LOCALE}/products/{handle}.js"
    logger.info(f"Fetching SNS .js: {url}")
    try:
        time.sleep(0.5)
        resp = _cffi_get(url)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"Could not fetch SNS .js endpoint: {e}")
        return None


def _fetch_ld_json(handle: str) -> dict | None:
    """Fetch the product HTML page and extract ld+json for EAN/GTIN data."""
    url = f"{SNS_BASE}{SNS_LOCALE}/products/{handle}"
    logger.info(f"Fetching SNS HTML for ld+json: {url}")
    try:
        time.sleep(0.5)
        resp = _cffi_get(url)
        if resp.status_code != 200:
            logger.warning(f"SNS HTML returned {resp.status_code}")
            return None

        ld_blocks = re.findall(
            r'<script\s+type=["\']application/ld\+json["\']\s*>(.*?)</script>',
            resp.text, re.DOTALL
        )

        for block in ld_blocks:
            try:
                data = json.loads(block.strip())
                if isinstance(data, dict):
                    schema_type = data.get("@type", "")
                    if schema_type in ("ProductGroup", "Product"):
                        return data
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") in ("ProductGroup", "Product"):
                            return item
            except json.JSONDecodeError:
                continue

        return None
    except Exception as e:
        logger.warning(f"Failed to fetch SNS ld+json: {e}")
        return None


def fetch_sns_page(product_url: str) -> dict:
    """Fetch all SNS product data and return a raw bundle."""
    handle = _extract_handle_from_url(product_url)
    logger.info(f"SNS handle: {handle}")

    json_data = _fetch_json_endpoint(handle)
    js_data = _fetch_js_endpoint(handle)
    ld_data = _fetch_ld_json(handle)

    return {
        "json_data": json_data,
        "js_data": js_data,
        "ld_data": ld_data,
        "handle": handle,
    }


def check_sns_still_online(product_url: str) -> dict:
    """Check if an SNS product is still available."""
    handle = _extract_handle_from_url(product_url)
    url = f"{SNS_BASE}{SNS_LOCALE}/products/{handle}.js"

    try:
        resp = _cffi_get(url, timeout=10)
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
    except Exception as e:
        if hasattr(e, 'response') and getattr(e.response, 'status_code', None) == 404:
            return {"online": False, "in_stock": False, "sizes_available": 0, "sizes_total": 0}
        raise
