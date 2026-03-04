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
  app.py           → API routes + static file serving
  database.py      → SQLite connection + queries
  schema.sql       → Database schema
  models.py        → Pydantic request/response models
  fetchers/
    shopify.py     → Fetch product data from Shopify .json + .js APIs
    manual.py      → Build product from manual input
  migrate_categories.py → One-time script to auto-categorize existing products
  debug_afew.py    → Debug script for testing AFEW API responses

data/
  catalog.db       → SQLite database (created on first run, gitignored)
```

## Quick Start

```bash
cd backend
pip install fastapi uvicorn requests pydantic
uvicorn app:app --reload --port 8000
```

Open http://localhost:8000

## How It Works

### Adding Products
1. Go to http://localhost:8000/admin
2. Paste a Shopify product URL (e.g., from AFEW Store)
3. The system fetches: name, brand, images, sizes, availability, pricing
4. Category is **auto-detected** from Shopify product type and tags
5. Product is saved to SQLite database

### Data Sources
- **`/products/{handle}.json`** — Shopify public API for product data, images, pricing, tags
- **`/products/{handle}.js`** — Shopify storefront API for real-time variant availability

### Category Auto-Detection
Detects from Shopify `product_type` field, tags (e.g., `type:footwear`), and product name keywords:
- 👟 **Sneakers** — footwear, shoes, runners, specific models (Dunk, Jordan, Gel-Kayano...)
- 👕 **Clothing** — hoodies, jackets, shirts, pants, sweaters...
- 🎩 **Accessories** — caps, bags, wallets, socks, scarves...
- 🧡 **Kids** — junior, youth, grade school...
- 👶 **Toddler** — infant, baby, toddler, crib...

Category can be changed on the product detail page (pencil icon).

### Catalogue Features
- Filter by: **category**, **brand**, **size**, **store**
- Sort by: newest, price, discount, total cost (incl. shipping)
- Size filter updates dynamically based on selected category
- Shipping costs per store (AFEW €7.99, END €9.99)

### Product Management
- **Edit category** — pencil icon on product detail page
- **Delete product** — red button on product detail page
- **PATCH /api/products/{slug}** — update category, name, brand, colorway
- **DELETE /api/products/{slug}** — remove product

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/products | List products (with filters) |
| GET | /api/products/{slug} | Product detail |
| POST | /api/products/shopify | Add product by URL |
| POST | /api/products/manual | Add product manually |
| PATCH | /api/products/{slug} | Edit product fields |
| DELETE | /api/products/{slug} | Delete product |
| GET | /api/brands | List all brands |
| GET | /api/categories | List all categories |
| GET | /api/sizes | List available sizes |
| GET | /api/stores | List stores |

## Stores

| Store | Shipping to LV | Free shipping | Platform |
|-------|---------------|---------------|----------|
| AFEW Store | €7.99 | €250+ | Shopify |
| END Clothing | €9.99 | €250+ | Custom |
