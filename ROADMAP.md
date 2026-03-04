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

## In Progress 🚧

### Phase 4: UI Polish
- [ ] Show sizes on catalogue cards (at-a-glance)
- [ ] Improve visual design / theme options
- [ ] Mobile responsiveness improvements
- [ ] Product count per filter

### Phase 5: Stock Monitoring
- [ ] Scheduled stock checker (background task)
- [ ] Mark products as offline/removed
- [ ] Stock change history
- [ ] Notification when item comes back in stock

## Planned 📋

### Phase 6: END Clothing Support
- [ ] END Clothing scraper/fetcher
- [ ] Handle non-Shopify product pages

### Phase 7: Multi-user & Deploy
- [ ] Admin authentication
- [ ] Deploy to Railway/Render
- [ ] Persistent storage (not just local SQLite)

### Phase 8: Advanced Features
- [ ] Price history tracking
- [ ] Wishlist / saved items
- [ ] Email alerts for price drops
- [ ] Bulk import from store sale pages
- [ ] Search by product name
