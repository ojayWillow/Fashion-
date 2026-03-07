# FASHION- Roadmap

## Completed ✅

### Phase 1: Core Infrastructure
- [x] FastAPI backend + SQLite database
- [x] Shopify product fetcher (`.json` + `.js` endpoints)
- [x] Product grid with dark theme
- [x] Product detail page with gallery, sizes, pricing
- [x] Admin page (paste URL → auto-fetch)
- [x] Manual product entry
- [x] Brand, store filters
- [x] Sort by price, discount, total cost

### Phase 2: Categories & Sizes
- [x] Auto-detect category from Shopify metadata
- [x] Category filter (sneakers, clothing, accessories, kids, toddler)
- [x] Size filter (dynamic per category)
- [x] Edit category on product page
- [x] Delete product
- [x] Migration script for existing products

### Phase 3: Reliability
- [x] Real-time size availability via `.js` endpoint
- [x] Retry with backoff on rate limits
- [x] `check_product_still_online()` function
- [x] Graceful fallback when `.js` fails

### Phase 4: Stock Monitoring
- [x] Scheduled stock checker (every 30 min via APScheduler)
- [x] Mark products as offline/removed on 404
- [x] Manual trigger: `POST /api/stock-check/trigger`
- [x] Status endpoint: `GET /api/stock-check/status`
- [ ] Stock change history
- [ ] Notification when item comes back in stock

### Phase 5: END Clothing Support
- [x] END Clothing fetcher via Algolia search proxy
- [x] Handle non-Shopify product pages
- [x] Per-size stock counts from Algolia `sku_stock`
- [x] LD+JSON fallback when Algolia fails
- [x] curl_cffi for TLS fingerprint spoofing
- [ ] Wire END into stock checker (currently skipped)

### Phase 6: Image Quality
- [x] AFEW CDN packshot scraping (5-6 high-res images vs 1 Shopify thumbnail)
- [x] 1200px resolution, sorted by rotation angle
- [x] `refresh_images.py` script for existing products
- [x] Falls back to Shopify API images if CDN scrape fails

### Phase 7: Gender-Aware Size Conversion
- [x] Detect gender from store tags (`gender:Women`, `gender:Men`)
- [x] Detect gender from product name keywords (WMNS, GS, TD)
- [x] Women's US → EU table (US 5 = EU 35.5, not 37.5)
- [x] Kids and Toddler conversion tables
- [x] `refresh_sizes.py` script for existing products
- [x] END Clothing gender detection from Algolia field

## In Progress 🚧

### Phase 8: UI Polish
- [ ] Show sizes on catalogue cards (at-a-glance)
- [ ] Improve visual design / theme options
- [ ] Mobile responsiveness improvements
- [ ] Product count per filter

### Phase 9: Stock Checker Alignment
- [ ] Wire END products into stock checker (Algolia re-check)
- [ ] Store `variant_id` for END sizes (currently `None`)
- [ ] Fix shipping cost in `schema.sql` seed (END: 9.99 → 11.99)
- [ ] Extract shared `category_detector.py` (remove duplication)

## Planned 📋

### Phase 10: Multi-user & Deploy
- [ ] Admin authentication
- [ ] Deploy to Railway/Render
- [ ] Persistent storage (not just local SQLite)

### Phase 11: Advanced Features
- [ ] Price history tracking
- [ ] Wishlist / saved items
- [ ] Email alerts for price drops
- [ ] Bulk import from store sale pages
- [ ] Search by product name
