# Changelog

All notable changes to FASHION- are documented here.

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
