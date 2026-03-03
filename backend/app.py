"""FastAPI application — serves the catalog API.

Run with:
    cd backend && uvicorn app:app --reload --port 8000
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
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


@app.on_event("startup")
def startup():
    init_db()


# --- Stores ---

@app.get("/api/stores", response_model=list[StoreOut])
def list_stores():
    """List all configured stores."""
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
    """Get catalog of all curated products with optional filters."""
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

    # Attach main image to each product
    for p in products:
        img = conn.execute(
            "SELECT image_url FROM product_images WHERE product_id = ? ORDER BY position LIMIT 1",
            (p["id"],),
        ).fetchone()
        p["image_url"] = img["image_url"] if img else None

    conn.close()

    # Sort
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
    """Get full product detail by slug."""
    conn = get_db()
    product = get_product_by_slug(conn, slug)
    conn.close()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


# --- Add Products ---

@app.post("/api/products/shopify")
def add_shopify_product(input: ShopifyFetchInput):
    """Auto-fetch and add a product from a Shopify store URL."""
    try:
        product_data = fetch_shopify_product(input.product_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch product: {e}")

    conn = get_db()

    # Find store by base URL or use provided store_id
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
    """Manually add a product (for non-Shopify stores like END Clothing)."""
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
    """Get list of all brands in the catalog."""
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT brand FROM products WHERE in_stock = 1 ORDER BY brand"
    ).fetchall()
    conn.close()
    return [r["brand"] for r in rows]
