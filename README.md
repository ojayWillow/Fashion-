# FASHION-

Curated streetwear deals aggregator. Tracks sale items from stores like AFEW Store, END Clothing, and Sneakersnstuff, showing prices, sizes, stock status, and shipping costs to Latvia.

## Architecture

```
frontend/          → Static HTML/CSS/JS (no framework)
  index.html       → Catalogue grid with filters
  product.html     → Product detail page
  admin.html       → Add products (paste URL or manual entry)
  css/style.css    → Dark theme styling
  js/catalog.js    → Catalogue grid logic
  js/product.js    → Product detail + edit/delete

backend/           → Python FastAPI server
  app.py           → API routes + static file serving + stock scheduler
  database.py      → SQLite connection + queries
  schema.sql       → Database schema
  models.py        → Pydantic request/response models
  stock_checker.py → Scheduled stock verification (every 30 min)
  refresh_images.py→ Re-scrape AFEW CDN images for existing products
  refresh_sizes.py → Re-fetch & re-convert sizes for all stores (AFEW, END, SNS)
  debug_sns.py     → SNS diagnostic: compare .json vs .js availability
  fetchers/
    shopify.py     → Fetch from Shopify .json + .js APIs + AFEW CDN images
    end_clothing.py→ END Clothing product processor + category detection
    _end_worker.py → END data fetcher via Algolia search proxy (3-strategy SKU lookup)
    sns.py         → SNS product processor (US→EU conversion, EAN/GTIN extraction)
    _sns_worker.py → SNS data fetcher via Shopify API with curl_cffi
    manual.py      → Build product from manual input
  utils/
    size_converter.py  → Gender-aware UK/US → EU size conversion (word-boundary regex)
    category_detector.py → Auto-detect product category
    http_retry.py  → HTTP requests with retry + backoff

data/
  catalog.db       → SQLite database (created on first run, gitignored)
```

## Quick Start

```bash
cd backend
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Open http://localhost:8000

## How It Works

### Adding Products
1. Go to http://localhost:8000/admin
2. Choose a tab: **Shopify (AFEW)**, **END Clothing**, **SNS**, or **Manual**
3. Paste the product URL and submit
4. The system auto-fetches: name, brand, images, sizes, availability, pricing
5. Category is **auto-detected** (sneakers, clothing, kids, etc.)
6. Gender is **auto-detected** from store tags or product name for correct size conversion

### Data Sources

**AFEW Store (Shopify)**
- `/products/{handle}.json` — product data, pricing, tags
- `/products/{handle}.js` — real-time variant availability
- Product page HTML → `cdn.afew-store.com` packshot images (5-6 per product at 1200px)
- Gender detection from `gender:Women`/`gender:Men` tags
- Shipping: €7.99 to Latvia

**END Clothing (Algolia)**
- Queries END's Algolia search proxy (`search1web.endclothing.com`)
- 3-strategy product lookup: URL SKU → HTML LD+JSON SKU → product name search
- `footwear_size_label` array = available sizes only (sold-out sizes removed by END)
- Returns: name, brand, SKU, all sizes with per-size stock counts, prices per region (EU/GB/US), 6 product images, colorway, categories
- No Playwright or browser cookies needed — pure HTTP via `curl_cffi`
- Fallback: LD+JSON scrape from product page HTML
- Gender detection from Algolia `gender` field
- Shipping: €11.99 to Latvia

**Sneakersnstuff / SNS (Shopify)**
- `/en-eu/products/{handle}.json` — product data, pricing, tags
- `/en-eu/products/{handle}.js` — real-time variant availability
- HTML LD+JSON — EAN/GTIN data for cross-store matching
- Sizes in US format, converted to EU using gender-aware tables
- Gender detection from Shopify tags, defaults to men's when ambiguous
- Uses `curl_cffi` for anti-bot bypass
- Shipping: free to Latvia

### Images

**AFEW** uses a custom CDN (`cdn.afew-store.com`) separate from Shopify's CDN. The Shopify API only returns 1 thumbnail, so we scrape the product page HTML for the real images:
- Sneakers: 6 rotation angles (0°–150°) at 1200px
- Clothing: 5 rotation angles (0°–120°) at 1200px
- Falls back to Shopify API images if scrape fails

**END** images come from Algolia (8-12 per product, already high quality).

**SNS** images come from standard Shopify CDN.

### Size Conversion

All sizes are converted to EU format. The converter is **gender-aware**:
- Detects gender from store tags (`gender:Women`, `gender:Men`) and product name keywords (`WMNS`, `GS`, `TD`)
- Uses **word-boundary regex** to avoid false positives (e.g. "Low" no longer matches women's `w` pattern)
- Defaults to **men's** sizing when no gender info is available (standard in sneaker industry)
- Women's US 5 = EU 35.5 (men's US 5 = EU 37.5)
- Supports: US Men's, US Women's, UK, Kids, Toddler → EU
- Clothing sizes (S/M/L/XL) pass through unchanged

### Stock Checker
- Runs automatically every 30 minutes via APScheduler
- Shopify products (AFEW, SNS): checked via `.js` endpoint
- END products: skipped (flagged for manual review — needs Algolia re-check)
- 404 responses: product marked as offline/removed
- Manual trigger: `POST /api/stock-check/trigger`
- Status: `GET /api/stock-check/status`

### Category Auto-Detection
Detects from product metadata, tags, and name keywords:
- 👟 **Sneakers** — footwear, shoes, runners, specific models (Dunk, Jordan, Gel-Kayano...)
- 👕 **Clothing** — hoodies, jackets, shirts, pants, sweaters...
- 🎩 **Accessories** — caps, bags, wallets, socks, scarves...
- 🧡 **Kids** — junior, youth, grade school...
- 👶 **Toddler** — infant, baby, toddler, crib...

### Catalogue Features
- Filter by: **category**, **brand**, **size**, **store**
- Sort by: newest, price, discount, total cost (incl. shipping)
- Size filter updates dynamically based on selected category
- UK/US sizes from stores are auto-converted to EU

### Maintenance Scripts

```bash
cd backend
python refresh_images.py              # Re-scrape AFEW CDN images for all products
python refresh_sizes.py               # Re-fetch & re-convert sizes (all stores)
python refresh_sizes.py --store afew  # AFEW only
python refresh_sizes.py --store end   # END only
python refresh_sizes.py --store sns   # SNS only
python debug_sns.py <URL>             # Debug SNS variant data for a product
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/products | List products (with filters) |
| GET | /api/products/{slug} | Product detail |
| POST | /api/products/shopify | Add product from Shopify URL |
| POST | /api/products/end | Add product from END Clothing URL |
| POST | /api/products/sns | Add product from SNS URL |
| POST | /api/products/manual | Add product manually |
| PATCH | /api/products/{slug} | Edit product fields |
| DELETE | /api/products/{slug} | Delete product |
| GET | /api/brands | List all brands |
| GET | /api/categories | List all categories |
| GET | /api/sizes | List available sizes |
| GET | /api/stores | List stores |
| GET | /api/stock-check/status | Stock checker status |
| POST | /api/stock-check/trigger | Trigger manual stock check |

## Stores

| Store | Shipping to LV | Free shipping | Platform |
|-------|---------------|---------------|----------|
| AFEW Store | €7.99 | €250+ | Shopify |
| END Clothing | €11.99 | — | Algolia API |
| Sneakersnstuff (SNS) | Free | — | Shopify + curl_cffi |
