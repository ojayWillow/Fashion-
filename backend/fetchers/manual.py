"""Manual product entry for non-Shopify stores (e.g., END Clothing).

Usage:
    from fetchers.manual import build_manual_product
    product_data = build_manual_product({...})
"""


def build_manual_product(data: dict) -> dict:
    """Validate and normalize manually entered product data.

    Accepts a dict with product fields and returns a dict
    matching the same format as shopify.fetch_shopify_product()
    so the same insert logic works for both.

    Required fields: name, brand, sale_price, product_url
    Optional: original_price, colorway, sku, description, images, sizes
    """
    required = ["name", "brand", "sale_price", "product_url"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    sale_price = float(data["sale_price"])
    original_price = float(data.get("original_price", sale_price))

    if original_price < sale_price:
        original_price = sale_price

    discount_pct = (
        round((1 - sale_price / original_price) * 100)
        if original_price > sale_price
        else 0
    )

    # Generate slug from name + colorway
    slug = data.get("slug") or _slugify(data["name"], data.get("colorway"))

    # Normalize images
    images = []
    for i, img in enumerate(data.get("images", [])):
        if isinstance(img, str):
            images.append({"url": img, "alt": f"{data['name']} - image {i}"})
        elif isinstance(img, dict):
            images.append({"url": img["url"], "alt": img.get("alt", f"{data['name']} - image {i}")})

    # Normalize sizes
    sizes = []
    for size in data.get("sizes", []):
        if isinstance(size, str):
            sizes.append({"label": size, "in_stock": True, "variant_id": None})
        elif isinstance(size, dict):
            sizes.append({
                "label": size["label"],
                "in_stock": size.get("in_stock", True),
                "variant_id": size.get("variant_id"),
            })

    return {
        "name": data["name"].strip(),
        "brand": data["brand"].strip(),
        "slug": slug,
        "sku": data.get("sku"),
        "colorway": data.get("colorway"),
        "original_price": original_price,
        "sale_price": sale_price,
        "discount_pct": discount_pct,
        "description": data.get("description", ""),
        "product_url": data["product_url"],
        "images": images,
        "sizes": sizes,
        "_base_url": None,
    }


def _slugify(name: str, colorway: str = None) -> str:
    """Generate a URL-friendly slug from product name."""
    import re
    text = name
    if colorway:
        text += f" {colorway}"
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")
