# FASHION-

Curated streetwear deals aggregator. Tracks sale items from stores like AFEW Store and END Clothing, showing prices, sizes, stock status, and shipping costs to Latvia.

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
  fetchers/
    shopify.py     → Fetch from Shopify .json + .js APIs (AFEW etc.)
    end_clothing.py→ END Clothing product processor + category detection
    _end_worker.py → END data fetcher via Algolia search proxy
    manual.py      → Build product from manual input
  utils/
    size_converter.py → UK/US → EU size conversion

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
2. Choose a tab: **Shopify (AFEW)**, **END Clothing**, or **Manual**
3. Paste the product URL and submit
4. The system auto-fetches: name, brand, images, sizes, availability, pricing
5. Category is **auto-detected** (sneakers, clothing, kids, etc.)

### Data Sources

**AFEW Store (Shopify)**
- `/products/{handle}.json` — product data, images, pricing, tags
- `/products/{handle}.js` — real-time variant availability
- Shipping: €7.99 to Latvia

**END Clothing (Algolia)**
- Queries END's Algolia search proxy (`search1web.endclothing.com`)
- Returns: name, brand, SKU, all sizes with per-size stock counts, prices per region (EU/GB/US), 6 product images, colorway, categories
- No Playwright or browser cookies needed — pure HTTP
- Fallback: LD+JSON scrape from product page HTML
- Shipping: €11.99 to Latvia

### Stock Checker
- Runs automatically every 30 minutes via APScheduler
- Shopify products: checked via `.json` endpoint
- END products: skipped (flagged for manual review)
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
- UK sizes from END are auto-converted to EU

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/products | List products (with filters) |
| GET | /api/products/{slug} | Product detail |
| POST | /api/products/shopify | Add product from Shopify URL |
| POST | /api/products/end | Add product from END Clothing URL |
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
