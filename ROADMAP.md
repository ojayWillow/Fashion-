# Roadmap

## Phase 1: Database & Data Layer
> Get the foundation bulletproof before anything else.

- [x] Define database schema (`backend/schema.sql`)
- [ ] Create `database.py` — SQLite connection, init, helpers
- [ ] Seed `stores` table with AFEW Store and END Clothing
- [ ] Write unit tests for all DB operations (insert, update, query)

## Phase 2: Shopify Fetcher (AFEW Store)
> The core data pipeline. Paste a URL → get everything.

- [ ] Build `fetchers/shopify.py` — extract handle from URL, hit `.json` endpoint
- [ ] Map Shopify JSON fields to our DB schema:
  - `product.title` → `products.name`
  - `product.vendor` → `products.brand`
  - `product.handle` → `products.slug`
  - `variants[].sku` → `products.sku`
  - `variants[].compare_at_price` → `products.original_price`
  - `variants[].price` → `products.sale_price`
  - `variants[].option1` → `product_sizes.size_label`
  - `variants[].available` → `product_sizes.in_stock`
  - `variants[].id` → `product_sizes.variant_id`
  - `images[].src` → `product_images.image_url`
  - `tags` (color:X) → `products.colorway`
  - `body_html` → `products.description`
- [ ] Handle edge cases: no `compare_at_price`, no images, empty variants
- [ ] Test with 5+ real AFEW sale product URLs
- [ ] Validate: every fetched product has name, brand, ≥1 price, ≥1 size, ≥1 image

## Phase 3: Manual Entry (END Clothing & others)
> For stores without API access.

- [ ] Build `fetchers/manual.py` — POST endpoint accepting JSON product data
- [ ] Define the manual entry JSON schema (what fields are required vs optional)
- [ ] Build a simple admin HTML form for quick manual entry
- [ ] Test: add 3 END Clothing products manually, verify DB storage

## Phase 4: Stock Checker
> Keep the catalog accurate — mark sold-out items.

- [ ] Build `stock_checker.py` — loop all Shopify products, check `.json` availability
- [ ] Update `product_sizes.in_stock` per variant
- [ ] Update `products.in_stock` (false if ALL sizes are out)
- [ ] Log every check in `stock_checks` table
- [ ] Handle errors gracefully (store down, timeout, 404 = product removed)
- [ ] Schedule: run every 30 min via APScheduler
- [ ] For non-Shopify products: flag for manual review (don't auto-check)

## Phase 5: Backend API
> Serve product data to the frontend.

- [ ] `GET /api/products` — catalog list with filters (brand, store, size, price range, discount %)
- [ ] `GET /api/products/{slug}` — single product with images + sizes
- [ ] `GET /api/stores` — store list with shipping info
- [ ] `POST /api/products/fetch` — paste Shopify URL, auto-fetch + store
- [ ] `POST /api/products/manual` — manual product entry
- [ ] `PATCH /api/products/{id}` — update product (featured, sort_order, etc.)
- [ ] `DELETE /api/products/{id}` — remove product from catalog

## Phase 6: Frontend — Catalog Grid
> The main page users see.

- [ ] Dark/futuristic theme with Tailwind CSS
- [ ] Product card: image, brand, name, original price (strikethrough), sale price, discount badge, store badge + shipping
- [ ] Filter sidebar: brand, store, size, price range, discount %
- [ ] Sort: biggest discount, lowest price, newest, lowest total cost
- [ ] "Low stock" / "Selling fast" urgency indicators
- [ ] Responsive: works on mobile

## Phase 7: Frontend — Product Detail
> The page you land on when clicking a product card.

- [ ] Image gallery (2-3 images, swipeable)
- [ ] Full product name, brand, colorway
- [ ] Price block: original → sale, discount %, "You save €X"
- [ ] Size selector: buttons per size, grayed if sold out
- [ ] Total cost calculator: sale price + shipping to Latvia
- [ ] "Buy Now" button → redirects to store product page
- [ ] Description section

## Phase 8: Deploy
> Go live.

- [ ] Backend → Railway (free tier)
- [ ] Frontend → Vercel (free tier)
- [ ] Set up stock checker cron on Railway
- [ ] Test full flow: add item → appears in catalog → click → detail → buy now → store
- [ ] Domain setup (optional)

---

## Decision Log

| Decision | Choice | Why |
|----------|--------|-----|
| Database | SQLite | Zero config, single file, <1000 products |
| Scraping approach | Curated/hand-picked, not mass scrape | Quality over quantity, legal safety |
| AFEW data source | Shopify `/products/{handle}.json` | Free, structured, all data in one call |
| END data source | Manual entry | Akamai bot protection blocks auto-fetch |
| Stock checking | Auto for Shopify, manual for others | Pragmatic — auto where possible |
| Frontend | Vanilla + Tailwind | Simple, fast, no framework overhead |
