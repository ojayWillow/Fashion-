# 🔥 Fashion- | Streetwear Sales Aggregator

A curated streetwear & sneaker deals catalog targeting Latvia. Hand-pick the best sale items from EU retailers, auto-fetch product data, and display them in a futuristic, urgency-driven catalog.

## How It Works

1. **Find a deal** on AFEW Store, END Clothing, or another retailer
2. **Paste the product URL** into the admin tool
3. **System auto-fetches** all product data (name, brand, images, prices, sizes, stock)
4. **Item appears** in the catalog on the website
5. **Stock checker** runs periodically to mark items as sold out

## Target Stores

| Store | Shipping to LV | Free Shipping | Platform |
|-------|---------------|---------------|----------|
| AFEW Store | €7.99 | From €250 | Shopify (auto-fetch) |
| END Clothing | €9.99 | From €250 | Custom (manual entry) |

## Tech Stack

- **Database:** SQLite
- **Backend:** Python + FastAPI
- **Fetcher:** Shopify JSON API (auto) + manual entry
- **Stock Checker:** APScheduler / cron
- **Frontend:** HTML/CSS/JS with dark futuristic theme

## Project Structure

```
backend/
  app.py              # FastAPI main app
  database.py          # SQLite connection + helpers
  models.py            # Pydantic models
  schema.sql           # Database schema
  fetchers/
    shopify.py         # Auto-fetch from Shopify URLs
    manual.py          # Manual product entry
  stock_checker.py     # Periodic availability check
  requirements.txt
frontend/
  index.html           # Catalog grid
  product.html         # Product detail page
  css/style.css        # Dark theme
  js/catalog.js        # Grid rendering
  js/product.js        # Detail page rendering
data/
  catalog.db           # SQLite database
```

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full implementation plan.
