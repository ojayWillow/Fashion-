"""Pydantic models for API request/response schemas."""
from pydantic import BaseModel, HttpUrl
from typing import Optional


# --- Request Models ---

class ManualProductInput(BaseModel):
    """Schema for manually adding a product (e.g., from END Clothing)."""
    name: str
    brand: str
    sale_price: float
    product_url: str
    original_price: Optional[float] = None
    colorway: Optional[str] = None
    sku: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = ""
    store_id: int = 2  # Default to END Clothing
    images: list[str] = []
    sizes: list[str] = []
    featured: bool = False


class ShopifyFetchInput(BaseModel):
    """Schema for auto-fetching a Shopify product by URL."""
    product_url: str
    store_id: int = 1  # Default to AFEW Store
    featured: bool = False


# --- Response Models ---

class StoreOut(BaseModel):
    id: int
    name: str
    base_url: str
    shipping_cost: float
    free_ship_min: Optional[float]
    currency: str


class ProductImageOut(BaseModel):
    image_url: str
    position: int
    alt_text: Optional[str]


class ProductSizeOut(BaseModel):
    size_label: str
    in_stock: bool


class ProductCardOut(BaseModel):
    """Slim model for catalog grid cards."""
    id: int
    name: str
    brand: str
    slug: str
    colorway: Optional[str]
    original_price: float
    sale_price: float
    discount_pct: int
    in_stock: bool
    featured: bool
    store_name: str
    shipping_cost: float
    image_url: Optional[str] = None  # Main image only
    added_at: str


class ProductDetailOut(BaseModel):
    """Full model for product detail page."""
    id: int
    name: str
    brand: str
    slug: str
    sku: Optional[str]
    colorway: Optional[str]
    original_price: float
    sale_price: float
    discount_pct: int
    description: Optional[str]
    product_url: str
    in_stock: bool
    featured: bool
    store_name: str
    shipping_cost: float
    free_ship_min: Optional[float]
    images: list[ProductImageOut]
    sizes: list[ProductSizeOut]
    added_at: str
