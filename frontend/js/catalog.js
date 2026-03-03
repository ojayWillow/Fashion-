/* Catalog grid page logic */

const API_BASE = window.location.hostname === 'localhost'
    ? 'http://localhost:8000'
    : '';  // Same origin in production

const grid = document.getElementById('product-grid');
const brandFilter = document.getElementById('filter-brand');
const storeFilter = document.getElementById('filter-store');
const discountFilter = document.getElementById('filter-discount');
const sortSelect = document.getElementById('sort');

async function loadStores() {
    try {
        const res = await fetch(`${API_BASE}/api/stores`);
        const stores = await res.json();
        stores.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.id;
            opt.textContent = `${s.name} (€${s.shipping_cost} shipping)`;
            storeFilter.appendChild(opt);
        });
    } catch (e) { console.warn('Could not load stores', e); }
}

async function loadBrands() {
    try {
        const res = await fetch(`${API_BASE}/api/brands`);
        const brands = await res.json();
        brands.forEach(b => {
            const opt = document.createElement('option');
            opt.value = b;
            opt.textContent = b;
            brandFilter.appendChild(opt);
        });
    } catch (e) { console.warn('Could not load brands', e); }
}

async function loadProducts() {
    const params = new URLSearchParams();
    if (brandFilter.value) params.set('brand', brandFilter.value);
    if (storeFilter.value) params.set('store_id', storeFilter.value);
    if (discountFilter.value) params.set('min_discount', discountFilter.value);
    params.set('sort', sortSelect.value);
    params.set('in_stock', 'true');

    grid.innerHTML = '<div class="loading">Loading deals…</div>';

    try {
        const res = await fetch(`${API_BASE}/api/products?${params}`);
        const products = await res.json();

        if (!products.length) {
            grid.innerHTML = `
                <div class="empty-state">
                    <h2>No deals found</h2>
                    <p>Try adjusting your filters</p>
                </div>`;
            return;
        }

        grid.innerHTML = products.map(p => renderCard(p)).join('');

        // Click handlers
        grid.querySelectorAll('.product-card').forEach(card => {
            card.addEventListener('click', () => {
                window.location.href = `product.html?slug=${card.dataset.slug}`;
            });
        });
    } catch (e) {
        grid.innerHTML = `
            <div class="empty-state">
                <h2>Could not load products</h2>
                <p>Make sure the API server is running on port 8000</p>
            </div>`;
    }
}

function renderCard(p) {
    const badges = [];
    if (p.featured) badges.push('<span class="badge badge-featured">Featured</span>');
    if (p.discount_pct >= 10) badges.push(`<span class="badge badge-discount">-${p.discount_pct}%</span>`);
    if (!p.in_stock) badges.push('<span class="badge badge-sold-out">Sold Out</span>');

    const imgHtml = p.image_url
        ? `<img src="${p.image_url}" alt="${p.name}" loading="lazy">`
        : '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted)">No image</div>';

    return `
        <div class="product-card ${p.in_stock ? '' : 'sold-out'}" data-slug="${p.slug}">
            <div class="card-image-wrap">
                ${imgHtml}
                <div class="card-badges">${badges.join('')}</div>
            </div>
            <div class="card-info">
                <div class="card-brand">${esc(p.brand)}</div>
                <div class="card-name">${esc(p.name)}</div>
                ${p.colorway ? `<div class="card-colorway">${esc(p.colorway)}</div>` : ''}
                <div class="card-prices">
                    <span class="price-sale">€${p.sale_price.toFixed(2)}</span>
                    ${p.original_price > p.sale_price
                        ? `<span class="price-original">€${p.original_price.toFixed(2)}</span>`
                        : ''}
                </div>
                <div class="card-store">
                    <span>${esc(p.store_name)}</span>
                    <span class="store-shipping">€${p.shipping_cost.toFixed(2)} to LV</span>
                </div>
            </div>
        </div>`;
}

function esc(str) {
    const d = document.createElement('div');
    d.textContent = str || '';
    return d.innerHTML;
}

// Init
brandFilter.addEventListener('change', loadProducts);
storeFilter.addEventListener('change', loadProducts);
discountFilter.addEventListener('change', loadProducts);
sortSelect.addEventListener('change', loadProducts);

loadStores();
loadBrands();
loadProducts();
