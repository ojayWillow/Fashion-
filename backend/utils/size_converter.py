"""Convert US/UK shoe sizes to EU. Clothing sizes (S/M/L/XL) pass through unchanged."""
import re

# US Men's -> EU (covers most sneaker brands)
US_MENS_TO_EU = {
    "3.5": "36", "4": "36.5", "4.5": "37", "5": "37.5", "5.5": "38",
    "6": "38.5", "6.5": "39", "7": "40", "7.5": "40.5", "8": "41",
    "8.5": "42", "9": "42.5", "9.5": "43", "10": "44", "10.5": "44.5",
    "11": "45", "11.5": "45.5", "12": "46", "12.5": "47", "13": "47.5",
    "13.5": "48", "14": "48.5", "15": "49.5", "16": "50.5",
}

# US Women's -> EU
US_WOMENS_TO_EU = {
    "5": "35.5", "5.5": "36", "6": "36.5", "6.5": "37.5", "7": "38",
    "7.5": "38.5", "8": "39", "8.5": "40", "9": "40.5", "9.5": "41",
    "10": "42", "10.5": "42.5", "11": "43", "11.5": "44", "12": "44.5",
}

# UK -> EU (unisex)
UK_TO_EU = {
    "3": "36", "3.5": "36.5", "4": "37", "4.5": "37.5", "5": "38",
    "5.5": "38.5", "6": "39", "6.5": "40", "7": "40.5", "7.5": "41",
    "8": "42", "8.5": "42.5", "9": "43", "9.5": "44", "10": "44.5",
    "10.5": "45", "11": "45.5", "11.5": "46", "12": "47", "12.5": "47.5",
    "13": "48", "13.5": "48.5", "14": "49.5",
}

# Kids US -> EU
US_KIDS_TO_EU = {
    "1": "32", "1.5": "33", "2": "33.5", "2.5": "34", "3": "35",
    "3.5": "35.5", "4": "36", "4.5": "36.5", "5": "37", "5.5": "37.5",
    "6": "38.5", "6.5": "39", "7": "40",
}

# Toddler US -> EU
US_TODDLER_TO_EU = {
    "2": "18", "3": "19", "4": "20", "5": "21", "6": "22",
    "7": "23.5", "8": "25", "9": "26", "10": "27",
}

# Clothing sizes pass through
_CLOTHING_SIZES = {'xxs', 'xs', 's', 'm', 'l', 'xl', 'xxl', 'xxxl', '2xs', '2xl', '3xl', '4xl', 'one size', 'os'}


def _is_eu_size(num_str: str) -> bool:
    """EU sneaker sizes are typically 35-50."""
    try:
        val = float(num_str)
        return 18 <= val <= 55
    except ValueError:
        return False


def _is_us_size(num_str: str) -> bool:
    """US sneaker sizes are typically 3-16."""
    try:
        val = float(num_str)
        return 2 <= val <= 16
    except ValueError:
        return False


def detect_gender_from_tags(tags: list[str] | None = None, name: str = "") -> str:
    """Detect product gender from store tags or product name.

    Returns: 'women', 'men', 'kids', 'toddler', or 'men' (default)

    Most sneakers sold on AFEW/END/SNS are men's sizing. We default
    to 'men' instead of 'unisex' to use the correct US->EU table.
    """
    # Check tags first (most reliable)
    for tag in (tags or []):
        tl = tag.lower().strip()
        if tl in ("gender:women", "gender:woman", "gender:female"):
            return "women"
        if tl in ("gender:men", "gender:man", "gender:male"):
            return "men"
        if tl in ("gender:kids", "gender:youth", "gender:junior"):
            return "kids"
        if tl in ("gender:toddler", "gender:infant", "gender:baby"):
            return "toddler"
        if tl in ("gender:unisex",):
            return "men"  # Use men's table for unisex (standard in sneaker industry)

    # Combine name + tags for keyword search
    name_lower = name.lower()

    # Fallback: check product name for common keywords using word boundaries
    # to avoid false positives like 'low' matching 'w'
    toddler_patterns = [r'\btd\b', r'\btoddler\b', r'\binfant\b', r'\bbaby\b', r'\bcrib\b']
    kids_patterns = [r'\bgs\b', r'\bgrade school\b', r'\bjunior\b', r'\byouth\b', r'\bkids\b', r'\bbig kid\b', r'\blittle kid\b']
    womens_patterns = [r'\bwmns\b', r'\bwomens\b', r"\bwomen's\b", r'\bwoman\b']

    if any(re.search(p, name_lower) for p in toddler_patterns):
        return "toddler"
    if any(re.search(p, name_lower) for p in kids_patterns):
        return "kids"
    if any(re.search(p, name_lower) for p in womens_patterns):
        return "women"

    return "men"


def convert_to_eu(raw_label: str, category: str = "sneakers", gender: str = "men") -> str:
    """Convert a size label to EU format. Returns the EU size string.

    Args:
        raw_label: The raw size string from the store (e.g. "9.5", "US 8", "42")
        category: Product category ('sneakers', 'clothing', 'accessories', etc.)
        gender: Product gender ('men', 'women', 'kids', 'toddler')

    Handles formats like:
    - "42" or "42.5" (already EU) -> "42" / "42.5"
    - "US 9.5" or "US9.5" -> "43"
    - "UK 8" -> "42"
    - "9.5" (bare number, ambiguous) -> detect by range + gender
    - "EU 42 / US 9.5" (combo) -> "42"
    - "S", "M", "L" (clothing) -> pass through unchanged
    """
    label = raw_label.strip()
    label_lower = label.lower()

    # Clothing sizes pass through
    if label_lower in _CLOTHING_SIZES:
        return label.upper()

    # Combo format: "EU 42 / US 9.5" -> extract EU part
    eu_match = re.search(r'EU\s*([\d]+\.?[\d]*)', label, re.IGNORECASE)
    if eu_match:
        return eu_match.group(1)

    # Explicit "US X" format
    us_match = re.match(r'^US\s*([\d]+\.?[\d]*)$', label, re.IGNORECASE)
    if us_match:
        num = us_match.group(1)
        return _convert_us_to_eu(num, category, gender)

    # Explicit "UK X" format
    uk_match = re.match(r'^UK\s*([\d]+\.?[\d]*)$', label, re.IGNORECASE)
    if uk_match:
        num = uk_match.group(1)
        if num in UK_TO_EU:
            return UK_TO_EU[num]
        return label

    # Bare number — detect if EU or US by range
    num_match = re.match(r'^([\d]+\.?[\d]*)$', label)
    if num_match:
        num = num_match.group(1)
        val = float(num)

        # EU range: 18-55 (covers toddler through adult)
        if val >= 18:
            return num  # already EU

        # US range: 2-16 -> convert using gender-aware table
        return _convert_us_to_eu(num, category, gender)

    # Can't parse — return as-is
    return label


def _convert_us_to_eu(num: str, category: str, gender: str) -> str:
    """Convert a US size number to EU using the correct table based on gender/category."""
    if category == 'toddler' or gender == 'toddler':
        if num in US_TODDLER_TO_EU:
            return US_TODDLER_TO_EU[num]

    if category == 'kids' or gender == 'kids':
        if num in US_KIDS_TO_EU:
            return US_KIDS_TO_EU[num]

    if gender == 'women':
        if num in US_WOMENS_TO_EU:
            return US_WOMENS_TO_EU[num]
        # Fall through to men's for large women's sizes (12+)

    if num in US_MENS_TO_EU:
        return US_MENS_TO_EU[num]

    return num  # can't convert, return as-is
