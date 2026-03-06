"""Shared category detection from product metadata.

Used by both Shopify and END fetchers to auto-categorize products.
"""

_TODDLER_WORDS = ['toddler', 'infant', 'baby', ' td ', ' td', 'td ', 'crib']
_KIDS_WORDS = ['kids', 'junior', 'youth', 'gs ', ' gs', 'grade school', 'big kid', 'little kid']
_CLOTHING_WORDS = [
    'hoodie', 'jacket', 'shirt', 't-shirt', 'tee', 'pants', 'jogger',
    'shorts', 'sweater', 'crewneck', 'crew neck', 'pullover', 'vest',
    'coat', 'parka', 'windbreaker', 'tracksuit', 'sweatshirt', 'sweatpant',
    'jersey', 'polo', 'cardigan', 'fleece', 'puffer', 'anorak', 'dress',
    'skirt', 'legging', 'trouser', 'cargo', 'denim', 'jeans', 'tank top',
    'longsleeve', 'apparel', 'clothing',
]
_ACCESSORY_WORDS = [
    'cap', 'hat', 'beanie', 'bag', 'backpack', 'wallet', 'belt', 'sock',
    'scarf', 'glove', 'sunglasses', 'watch', 'keychain', 'headband',
    'wristband', 'accessory', 'accessories', 'case', 'pouch', 'tote', 'duffle',
]
_SNEAKER_WORDS = [
    'sneaker', 'shoe', 'footwear', 'runner', 'trainer', 'boot', 'slide',
    'sandal', 'clog', 'mule', 'slipper', 'foam', 'dunk', 'jordan',
    'air max', 'gel-', 'chuck', '550', '530', '2002r', '990', '1906',
    'ultraboost', 'ozweego', 'forum', 'samba', 'gazelle', 'campus',
    'old skool', 'sk8', 'classic leather',
]


def detect_category(
    name: str,
    product_type: str = "",
    tags: list[str] | None = None,
    breadcrumbs: list[str] | None = None,
) -> str:
    """Auto-detect product category from metadata.

    Works for any store — pass whatever metadata you have.
    """
    parts = [name, product_type] + (tags or []) + (breadcrumbs or [])
    text = f" {' '.join(parts)} ".lower()

    if any(w in text for w in _TODDLER_WORDS):
        return 'toddler'
    if any(w in text for w in _KIDS_WORDS):
        return 'kids'

    # Check Shopify product_type if available
    if product_type:
        ptype = product_type.lower().strip()
        if ptype in ['footwear', 'shoes', 'sneakers']:
            return 'sneakers'
        if ptype in ['apparel', 'clothing', 'tops', 'bottoms', 'outerwear']:
            return 'clothing'
        if ptype in ['accessories', 'bags', 'hats', 'socks']:
            return 'accessories'

    # Check Shopify tags with type: prefix
    for tag in (tags or []):
        tl = tag.lower()
        if tl.startswith('type:'):
            val = tl.split(':', 1)[1].strip()
            if val in ['footwear', 'shoes', 'sneakers', 'sneaker']:
                return 'sneakers'
            if val in ['apparel', 'clothing', 'tops', 'bottoms']:
                return 'clothing'
            if val in ['accessories', 'accessory']:
                return 'accessories'

    # Check breadcrumbs (END Clothing style)
    bc_text = ' '.join(breadcrumbs or []).lower()
    if any(w in bc_text for w in ['sneakers', 'footwear', 'shoes', 'boots']):
        return 'sneakers'
    if any(w in bc_text for w in ['clothing', 'tops', 'bottoms', 'outerwear', 'knitwear']):
        return 'clothing'
    if any(w in bc_text for w in ['accessories', 'bags', 'hats', 'socks', 'jewellery']):
        return 'accessories'

    # Keyword fallback
    if any(w in text for w in _ACCESSORY_WORDS):
        return 'accessories'
    if any(w in text for w in _CLOTHING_WORDS):
        return 'clothing'
    if any(w in text for w in _SNEAKER_WORDS):
        return 'sneakers'

    return 'sneakers'
