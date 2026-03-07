# Changelog

All notable changes to FASHION- are documented here.

## [0.5.0] - 2026-03-07

### Fixed
- **END size availability** — `footwear_size_label` only contains available sizes (sold-out sizes are removed by END). All sizes in the array are now correctly marked as in-stock instead of guessing from `sku_stock` offsets
- **END SKU lookup** — new 3-strategy fallback: URL SKU → HTML LD+JSON SKU → product name search. Fixes products where END changed the SKU (e.g. Jordan 11 Retro: URL has `FV1565-101` but real SKU is `IH0296-400`)
- **Gender detection false positive** — `detect_gender_from_tags` used loose substring matching (`' w'`, `'w '`) which matched words like `low` in product names (e.g. "Air Force 1 **Low** x Kobe" → detected as women's). Fixed with word-boundary regex (`\bwmns\b`, `\bwomens\b`, etc.)
- **SNS size conversion** — sizes were shifted by ~2 EU sizes on products with no gender tags (default was `unisex` → now defaults to `men` since most sneakers use men's sizing)

### Added
- **SNS store support** in `refresh_sizes.py` — re-fetches from `.json`/`.js` endpoints with corrected gender detection
- **`_find_product_in_algolia()`** — unified search function for END with 3 strategies (URL SKU, HTML SKU, product name)
- **`_extract_product_name_from_url()`** — extracts human-readable name from END URL slugs for name-based search fallback
- **`debug_sns.py`** — diagnostic script comparing SNS `.json` vs `.js` variant data with size conversion preview

### Changed
- `refresh_sizes.py` now supports all 3 stores: `--store afew`, `--store end`, `--store sns`
- `detect_gender_from_tags()` default changed from `unisex` to `men`
- `convert_to_eu()` default gender changed from `unisex` to `men`
- END `_parse_sizes()` rewritten: trusts `footwear_size_label` as source of truth, matches non-zero `sku_stock` entries to labels for quantity counts

## [0.4.0] - 2026-03-05

### Added
- **END Clothing Algolia fetcher** — queries END's own search proxy for complete product data
- Full size availability with per-size stock counts from Algolia
- Multi-region price support (EU/GB/US) with sale detection
- 6 product images per END product via media_gallery
- Colorway, gender, season, and category data from Algolia
- HTML LD+JSON fallback if Algolia misses

### Changed
- Replaced Playwright-based END scraper with Algolia search proxy approach
- No more Playwright, BeautifulSoup, browser_cookie3, or lxml dependencies for END
- Only requires `curl_cffi` (already installed)
- Admin page END form: removed cookie warning, updated hints
- Manual store dropdown now shows correct €11.99 END shipping cost

### Fixed
- END product fetching no longer blocked by Akamai bot protection
- END products now get proper size and stock data (was empty before)

## [0.3.0] - 2026-03-04

### Added
- **Auto-detect category** from Shopify product type, tags, and name keywords
- Category filter on catalogue page (👟 Sneakers, 👕 Clothing, 🎩 Accessories, 🧡 Kids, 👶 Toddler)
- Size filter on catalogue page (updates dynamically per category)
- Edit category on product detail page (pencil icon)
- Delete product on product detail page
- PATCH /api/products/{slug} endpoint
- DELETE /api/products/{slug} endpoint
- GET /api/categories endpoint
- GET /api/sizes endpoint (supports ?category= filter)
- Migration script to auto-categorize existing products
- Success message shows detected category after adding product

### Fixed
- Category now auto-detected instead of always defaulting to sneakers
- Admin page no longer sends a category override (was overwriting auto-detection)
- Removed min discount filter (not useful)

### Changed
- Admin Shopify form simplified: just paste URL and go
- ShopifyFetchInput model uses `category_override` (only when user explicitly picks)

## [0.2.0] - 2026-03-03

### Added
- Real-time size availability using Shopify `.js` endpoint
- Retry with backoff on 429 rate limits (3s, 6s, 9s)
- `check_product_still_online()` function for stock monitoring
- Product detail page with image gallery, sizes, pricing
- Admin page with Shopify auto-fetch and manual entry tabs
- Buy Now button linking to store
- Shipping cost display per store

### Fixed
- Variant availability showing null (was using .json, now uses .js)
- Images missing (removed /products/ path filter, accept all CDN paths)
- Rate limiting issues (added delays between API calls)

## [0.1.0] - 2026-03-03

### Added
- Initial project setup
- FastAPI backend with SQLite database
- Shopify product fetcher (.json endpoint)
- Dark theme frontend with product grid
- Brand and store filters
- Discount badge and sale pricing
- AFEW Store and END Clothing as seed stores
