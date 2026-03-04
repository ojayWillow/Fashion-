-- Fashion- Database Schema
-- SQLite

CREATE TABLE IF NOT EXISTS stores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    base_url        TEXT NOT NULL,
    platform        TEXT NOT NULL,
    shipping_cost   REAL NOT NULL,
    free_ship_min   REAL,
    currency        TEXT NOT NULL DEFAULT 'EUR',
    logo_url        TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id        INTEGER NOT NULL REFERENCES stores(id),

    -- Identity
    name            TEXT NOT NULL,
    brand           TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE,
    sku             TEXT,
    colorway        TEXT,
    category        TEXT NOT NULL DEFAULT 'sneakers',

    -- Pricing
    original_price  REAL NOT NULL,
    sale_price      REAL NOT NULL,
    discount_pct    INTEGER NOT NULL,

    -- Content
    description     TEXT,
    product_url     TEXT NOT NULL,

    -- Stock
    in_stock        INTEGER NOT NULL DEFAULT 1,
    last_checked    TEXT,

    -- Display
    featured        INTEGER NOT NULL DEFAULT 0,
    sort_order      INTEGER NOT NULL DEFAULT 0,

    -- Timestamps
    added_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS product_images (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    image_url       TEXT NOT NULL,
    position        INTEGER NOT NULL DEFAULT 0,
    alt_text        TEXT
);

CREATE TABLE IF NOT EXISTS product_sizes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    size_label      TEXT NOT NULL,
    size_original   TEXT,
    in_stock        INTEGER NOT NULL DEFAULT 1,
    variant_id      TEXT,
    last_checked    TEXT,

    UNIQUE(product_id, size_label)
);

CREATE TABLE IF NOT EXISTS stock_checks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    checked_at      TEXT NOT NULL DEFAULT (datetime('now')),
    was_in_stock    INTEGER NOT NULL,
    sizes_available INTEGER NOT NULL DEFAULT 0,
    raw_response    TEXT
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_products_store ON products(store_id);
CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_in_stock ON products(in_stock);
CREATE INDEX IF NOT EXISTS idx_products_discount ON products(discount_pct DESC);
CREATE INDEX IF NOT EXISTS idx_product_sizes_product ON product_sizes(product_id);
CREATE INDEX IF NOT EXISTS idx_product_sizes_label ON product_sizes(size_label);
CREATE INDEX IF NOT EXISTS idx_product_images_product ON product_images(product_id);
CREATE INDEX IF NOT EXISTS idx_stock_checks_product ON stock_checks(product_id);

-- Seed stores
INSERT OR IGNORE INTO stores (name, base_url, platform, shipping_cost, free_ship_min)
VALUES
    ('AFEW Store', 'https://en.afew-store.com', 'shopify', 7.99, 250.00),
    ('END Clothing', 'https://www.endclothing.com', 'custom', 9.99, 250.00);
