"""FastAPI application — serves the catalog API + frontend."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler

from database import get_db, init_db, insert_product, insert_images, insert_sizes, get_all_products, get_product_by_slug, get_store_by_platform
from models import ManualProductInput, ShopifyFetchInput, EndFetchInput, ProductCardOut, ProductDetailOut, StoreOut
from fetchers.shopify import fetch_shopify_product
from fetchers.manual import build_manual_product
from fetchers.end_clothing import fetch_end_product
from stock_checker import run_stock_check, get_status as get_stock_status

logger = logging.getLogger("fashion")

# --- Scheduler setup ---
scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    scheduler.add_job(
        run_stock_check,
        "interval",
        minutes=30,
        id="stock_checker",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info("[FASHION-] Server ready! Stock checker scheduled every 30 min.")
    print("[FASHION-] Server ready! Stock checker scheduled every 30 min. Open http://127.0.0.1:8000")
    yield
    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("[FASHION-] Scheduler stopped.")


app = FastAPI(title="Fashion Catalog API", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = (Path(__file__).resolve().parent.parent / "frontend")


# ─── Stock Check Endpoints ─────────────────────────

@app.get("/api/stock-check/status")
def stock_check_status():
    """Return info about the scheduled stock checker."""
    status = get_stock_status()
    status["scheduler_running"] = scheduler.running
    next_run = scheduler.get_job("stock_checker")
    status["next_run"] = str(next_run.next_run_time) if next_run else None
    return status


@app.post("/api/stock-check/trigger")
def trigger_stock_check():
    """Manually trigger a stock check now."""
    try:
        result = run_stock_check()
        return {"message": "Stock check completed", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stock check failed: {e}")


# ─── Store Endpoints ─────────────────────────────

@app.get("/api/stores", response_model=list[StoreOut])
def list_stores():
    conn = get_db()
    rows = conn.execute("SELECT * FROM stores").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Product Endpoints ───────────────────────────

@app.get("/api/products")
def list_products(
    brand: Optional[str] = None,
    store_id: Optional[int] = None,
    category: Optional[str] = None,
    size: Optional[str] = None,
    in_stock: bool = True,
    sort: str = Query("newest", enum=["newest", "price_asc", "price_desc", "discount", "total_cost"]),
):
    conn = get_db()
    filters = {}
    if brand:
        filters["brand"] = brand
    if store_id:
        filters["store_id"] = store_id
    if category:
        filters["category"] = category
    if size:
        filters["size"] = size
    if in_stock:
        filters["in_stock"] = True

    products = get_all_products(conn, filters)

    for p in products:
        img = conn.execute(
            "SELECT image_url FROM product_images WHERE product_id = ? ORDER BY position LIMIT 1",
            (p["id"],),
        ).fetchone()
        p["image_url"] = img["image_url"] if img else None

        sizes = conn.execute(
            "SELECT size_label FROM product_sizes WHERE product_id = ? AND in_stock = 1 ORDER BY size_label",
            (p["id"],),
        ).fetchall()
        p["sizes"] = [s["size_label"] for s in sizes]

    conn.close()

    if sort == "price_asc":
        products.sort(key=lambda p: p["sale_price"])
    elif sort == "price_desc":
        products.sort(key=lambda p: p["sale_price"], reverse=True)
    elif sort == "discount":
        products.sort(key=lambda p: p["discount_pct"], reverse=True)
    elif sort == "total_cost":
        products.sort(key=lambda p: p["sale_price"] + p["shipping_cost"])

    return products


@app.get("/api/products/{slug}")
def get_product(slug: str):
    conn = get_db()
    product = get_product_by_slug(conn, slug)
    conn.close()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.patch("/api/products/{slug}")
def update_product(slug: str, updates: dict):
    """Update product fields. Supports: category, name, featured, brand, colorway."""
    conn = get_db()
    product = get_product_by_slug(conn, slug)
    if not product:
        conn.close()
        raise HTTPException(status_code=404, detail="Product not found")

    allowed = {'category', 'name', 'featured', 'brand', 'colorway'}
    fields_to_update = {k: v for k, v in updates.items() if k in allowed}

    if not fields_to_update:
        conn.close()
        raise HTTPException(status_code=400, detail=f"No valid fields. Allowed: {allowed}")

    set_clause = ", ".join(f"{k} = ?" for k in fields_to_update)
    values = list(fields_to_update.values()) + [slug]
    conn.execute(f"UPDATE products SET {set_clause}, updated_at = datetime('now') WHERE slug = ?", values)
    conn.commit()
    conn.close()

    return {"message": "Updated", "fields": list(fields_to_update.keys())}


@app.delete("/api/products/{slug}")
def delete_product(slug: str):
    """Delete a product and its images/sizes."""
    conn = get_db()
    row = conn.execute("SELECT id FROM products WHERE slug = ?", (slug,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Product not found")

    pid = row["id"]
    conn.execute("DELETE FROM product_images WHERE product_id = ?", (pid,))
    conn.execute("DELETE FROM product_sizes WHERE product_id = ?", (pid,))
    conn.execute("DELETE FROM products WHERE id = ?", (pid,))
    conn.commit()
    conn.close()
    return {"message": "Deleted"}


@app.post("/api/products/shopify")
def add_shopify_product(input: ShopifyFetchInput):
    try:
        product_data = fetch_shopify_product(input.product_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch product: {e}")

    conn = get_db()
    store = get_store_by_platform(conn, product_data["_base_url"])
    store_id = store["id"] if store else input.store_id
    product_data["store_id"] = store_id

    if input.category_override:
        product_data["category"] = input.category_override

    try:
        product_id = insert_product(conn, product_data)
        insert_images(conn, product_id, product_data["images"])
        insert_sizes(conn, product_id, product_data["sizes"])
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to save product: {e}")
    finally:
        conn.close()

    return {
        "id": product_id,
        "slug": product_data["slug"],
        "category": product_data.get("category", "sneakers"),
        "message": "Product added",
    }


@app.post("/api/products/end")
def add_end_product(input: EndFetchInput):
    """Fetch and save a product from END Clothing.

    Requires browser_cookie3 + Chrome cookies from endclothing.com.
    """
    try:
        product_data = fetch_end_product(input.product_url)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch END product: {e}")

    conn = get_db()
    store = get_store_by_platform(conn, product_data["_base_url"])
    if not store:
        conn.close()
        raise HTTPException(
            status_code=500,
            detail="END Clothing store not found in database. Run init_db() to seed stores.",
        )

    product_data["store_id"] = store["id"]

    if input.category_override:
        product_data["category"] = input.category_override

    if input.featured:
        product_data["featured"] = 1

    try:
        product_id = insert_product(conn, product_data)
        insert_images(conn, product_id, product_data["images"])
        insert_sizes(conn, product_id, product_data["sizes"])
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to save END product: {e}")
    finally:
        conn.close()

    return {
        "id": product_id,
        "slug": product_data["slug"],
        "name": product_data["name"],
        "brand": product_data["brand"],
        "category": product_data.get("category", "sneakers"),
        "sale_price": product_data["sale_price"],
        "message": "END product added",
    }


@app.post("/api/products/manual")
def add_manual_product(input: ManualProductInput):
    try:
        product_data = build_manual_product(input.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    conn = get_db()
    product_data["store_id"] = input.store_id
    try:
        product_id = insert_product(conn, product_data)
        insert_images(conn, product_id, product_data["images"])
        insert_sizes(conn, product_id, product_data["sizes"])
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to save product: {e}")
    finally:
        conn.close()

    return {"id": product_id, "slug": product_data["slug"], "message": "Product added"}


# ─── Filter Endpoints ────────────────────────────

@app.get("/api/brands")
def list_brands():
    conn = get_db()
    rows = conn.execute("SELECT DISTINCT brand FROM products ORDER BY brand").fetchall()
    conn.close()
    return [r["brand"] for r in rows]


@app.get("/api/categories")
def list_categories():
    conn = get_db()
    rows = conn.execute("SELECT DISTINCT category FROM products ORDER BY category").fetchall()
    conn.close()
    return [r["category"] for r in rows]


@app.get("/api/sizes")
def list_sizes(category: Optional[str] = None):
    conn = get_db()
    if category:
        rows = conn.execute(
            """SELECT DISTINCT ps.size_label FROM product_sizes ps
               JOIN products p ON ps.product_id = p.id
               WHERE ps.in_stock = 1 AND p.category = ?
               ORDER BY ps.size_label""",
            (category,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT size_label FROM product_sizes WHERE in_stock = 1 ORDER BY size_label"
        ).fetchall()
    conn.close()
    return [r["size_label"] for r in rows]


# ─── Serve Frontend ──────────────────────────────

try:
    css_dir = FRONTEND_DIR / "css"
    js_dir = FRONTEND_DIR / "js"

    if css_dir.exists() and js_dir.exists():
        app.mount("/css", StaticFiles(directory=str(css_dir)), name="css")
        app.mount("/js", StaticFiles(directory=str(js_dir)), name="js")

        @app.get("/")
        def serve_index():
            return FileResponse(str(FRONTEND_DIR / "index.html"))

        @app.get("/product")
        def serve_product_page():
            return FileResponse(str(FRONTEND_DIR / "product.html"))

        @app.get("/admin")
        def serve_admin_page():
            return FileResponse(str(FRONTEND_DIR / "admin.html"))

        print(f"[FASHION-] Frontend mounted from {FRONTEND_DIR}")
except Exception as e:
    print(f"[FASHION-] ERROR mounting frontend: {e}")
