"""FastAPI application — serves the catalog API + frontend.

Run with:
    cd backend && uvicorn app:app --reload --port 8000
"""
import sys
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from typing import Optional

from database import get_db, init_db, insert_product, insert_images, insert_sizes, get_all_products, get_product_by_slug, get_store_by_platform
from models import ManualProductInput, ShopifyFetchInput, ProductCardOut, ProductDetailOut, StoreOut
from fetchers.shopify import fetch_shopify_product
from fetchers.manual import build_manual_product

app = FastAPI(
    title="Fashion Catalog API",
    description="Curated streetwear deals aggregator",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Resolve frontend directory (works from both backend/ and project root)
FRONTEND_DIR = (Path(__file__).resolve().parent.parent / "frontend")
print(f"[FASHION-] Frontend directory: {FRONTEND_DIR}")
print(f"[FASHION-] Frontend exists: {FRONTEND_DIR.exists()}")


@app.on_event("startup")
def startup():
    init_db()
    print("[FASHION-] Server ready! Open http://127.0.0.1:8000 in your browser.")


# --- Stores ---

@app.get("/api/stores", response_model=list[StoreOut])
def list_stores():
    conn = get_db()
    rows = conn.execute("SELECT * FROM stores").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Catalog ---

@app.get("/api/products")
def list_products(
    brand: Optional[str] = None,
    store_id: Optional[int] = None,
    in_stock: bool = True,
    min_discount: Optional[int] = None,
    sort: str = Query("newest", enum=["newest", "price_asc", "price_desc", "discount", "total_cost"]),
):
    conn = get_db()
    filters = {}
    if brand:
        filters["brand"] = brand
    if store_id:
        filters["store_id"] = store_id
    if in_stock:
        filters["in_stock"] = True
    if min_discount:
        filters["min_discount"] = min_discount

    products = get_all_products(conn, filters)

    for p in products:
        img = conn.execute(
            "SELECT image_url FROM product_images WHERE product_id = ? ORDER BY position LIMIT 1",
            (p["id"],),
        ).fetchone()
        p["image_url"] = img["image_url"] if img else None

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


# --- Add Products ---

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


@app.get("/api/brands")
def list_brands():
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT brand FROM products WHERE in_stock = 1 ORDER BY brand"
    ).fetchall()
    conn.close()
    return [r["brand"] for r in rows]


# --- Serve Frontend ---

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
    else:
        print(f"[FASHION-] WARNING: Frontend dirs not found at {FRONTEND_DIR}")
        print(f"[FASHION-]   css exists: {css_dir.exists()}")
        print(f"[FASHION-]   js exists: {js_dir.exists()}")
        print(f"[FASHION-]   API-only mode — use http://127.0.0.1:8000/docs")
except Exception as e:
    print(f"[FASHION-] ERROR mounting frontend: {e}")
    print(f"[FASHION-]   API-only mode — use http://127.0.0.1:8000/docs")
