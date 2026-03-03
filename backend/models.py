"""Pydantic models for API request/response validation."""
from pydantic import BaseModel
from typing import Optional


class ShopifyFetchInput(BaseModel):
    product_url: str
    featured: bool = False
    store_id: Optional[int] = None
    category: Optional[str] = None  # auto-detected if not provided


class ManualProductInput(BaseModel):
    name: str
    brand: str
    colorway: Optional[str] = None
    sku: Optional[str] = None
    original_price: Optional[float] = None
    sale_price: float
    product_url: str
    images: list[str] = []
    sizes: list[str] = []
    description: str = ""
    store_id: int = 1
    featured: bool = False
    category: str = "sneakers"


class StoreOut(BaseModel):
    id: int
    name: str
    base_url: str
    platform: str
    shipping_cost: float
    free_ship_min: Optional[float] = None
    currency: str = "EUR"


class ProductCardOut(BaseModel):
    id: int
    name: str
    brand: str
    slug: str
    colorway: Optional[str] = None
    category: str = "sneakers"
    original_price: float
    sale_price: float
    discount_pct: int
    image_url: Optional[str] = None
    in_stock: bool = True
    store_name: str = ""
    shipping_cost: float = 0


class ProductDetailOut(ProductCardOut):
    sku: Optional[str] = None
    description: Optional[str] = None
    product_url: str = ""
    images: list = []
    sizes: list = []
    free_ship_min: Optional[float] = None
