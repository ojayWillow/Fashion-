/* Catalog grid page logic */

const API_BASE = '';

const grid = document.getElementById('product-grid');
const categoryFilter = document.getElementById('filter-category');
const brandFilter = document.getElementById('filter-brand');
const sizeFilter = document.getElementById('filter-size');
const storeFilter = document.getElementById('filter-store');
const sortSelect = document.getElementById('sort');

async function loadStores() {
    try {
        const res = await fetch(`${API_BASE}/api/stores`);
        const stores = await res.json();
        stores.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.id;
            opt.textContent = `${s.name} (\u20ac${s.shipping_cost} shipping)`;
            storeFilter.appendChild(opt);
        });
    } catch (e) { console.warn('Could not load stores', e); }
}

async function loadBrands() {
    try {
        const res = await fetch(`${API_BASE}/api/brands`);
        const brands = await res.json();
        brandFilter.innerHTML = '<option value="">All Brands</option>';
        brands.forEach(b => {
            const opt = document.createElement('option');
            opt.value = b;
            opt.textContent = b;
            brandFilter.appendChild(opt);
        });
    } catch (e) { console.warn('Could not load brands', e); }
}

async function loadCategories() {
    try {
        const res = await fetch(`${API_BASE}/api/categories`);
        const categories = await res.json();
        categoryFilter.innerHTML = '<option value="">All Categories</option>';
        const labels = {
            'sneakers': '\ud83d\udc5f Sneakers',
            'clothing': '\ud83d\udc55 Clothing',
            'accessories': '\ud83c\udfa9 Accessories',
            'kids': '\ud83e\udde1 Kids',
            'toddler': '\ud83d\udc76 Toddler',
        };
        categories.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c;
            opt.textContent = labels[c] || c.charAt(0).toUpperCase() + c.slice(1);
            categoryFilter.appendChild(opt);
        });
    } catch (e) { console.warn('Could not load categories', e); }
}

async function loadSizes() {
    try {
        const category = categoryFilter.value;
        const url = category
            ? `${API_BASE}/api/sizes?category=${encodeURIComponent(category)}`
            : `${API_BASE}/api/sizes`;
        const res = await fetch(url);
        const sizes = await res.json();
        const current = sizeFilter.value;
        sizeFilter.innerHTML = '<option value="">All Sizes</option>';
        sizes.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s;
            opt.textContent = s;
            if (s === current) opt.selected = true;
            sizeFilter.appendChild(opt);
        });
    } catch (e) { console.warn('Could not load sizes', e); }
}

async function loadProducts() {
    const params = new URLSearchParams();
    if (categoryFilter.value) params.set('category', categoryFilter.value);
    if (brandFilter.value) params.set('brand', brandFilter.value);
    if (sizeFilter.value) params.set('size', sizeFilter.value);
    if (storeFilter.value) params.set('store_id', storeFilter.value);
    params.set('sort', sortSelect.value);
    params.set('in_stock', 'true');

    grid.innerHTML = '<div class="loading">Loading deals\u2026</div>';

    try {
        const res = await fetch(`${API_BASE}/api/products?${params}`);
        const products = await res.json();

        if (!products.length) {
            grid.innerHTML = `
                <div class="empty-state">
                    <h2>No deals found</h2>
                    <p>Try adjusting your filters or <a href="/admin" style="color:var(--accent)">add products</a></p>
                </div>`;
            return;
        }

        grid.innerHTML = products.map(p => renderCard(p)).join('');

        grid.querySelectorAll('.product-card').forEach(card => {
            card.addEventListener('click', () => {
                window.location.href = `/product?slug=${card.dataset.slug}`;
            });
        });
    } catch (e) {
        grid.innerHTML = `
            <div class="empty-state">
                <h2>Could not load products</h2>
                <p>Make sure the server is running</p>
            </div>`;
    }
}

function renderCard(p) {
    const badges = [];
    if (p.featured) badges.push('<span class="badge badge-featured">Featured</span>');
    if (p.discount_pct >= 10) badges.push(`<span class="badge badge-discount">-${p.discount_pct}%</span>`);
    if (!p.in_stock) badges.push('<span class="badge badge-sold-out">Sold Out</span>');

    const catLabels = { sneakers: '\ud83d\udc5f', clothing: '\ud83d\udc55', accessories: '\ud83c\udfa9', kids: '\ud83e\udde1', toddler: '\ud83d\udc76' };
    const catIcon = catLabels[p.category] || '';

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
                <div class="card-brand">${catIcon} ${esc(p.brand)}</div>
                <div class="card-name">${esc(p.name)}</div>
                ${p.colorway ? `<div class="card-colorway">${esc(p.colorway)}</div>` : ''}
                <div class="card-prices">
                    <span class="price-sale">\u20ac${p.sale_price.toFixed(2)}</span>
                    ${p.original_price > p.sale_price
                        ? `<span class="price-original">\u20ac${p.original_price.toFixed(2)}</span>`
                        : ''}
                </div>
                <div class="card-store">
                    <span>${esc(p.store_name)}</span>
                    <span class="store-shipping">\u20ac${p.shipping_cost.toFixed(2)} to LV</span>
                </div>
            </div>
        </div>`;
}

function esc(str) {
    const d = document.createElement('div');
    d.textContent = str || '';
    return d.innerHTML;
}

// When category changes, reload sizes (different size systems)
categoryFilter.addEventListener('change', () => {
    loadSizes();
    loadProducts();
});
brandFilter.addEventListener('change', loadProducts);
sizeFilter.addEventListener('change', loadProducts);
storeFilter.addEventListener('change', loadProducts);
sortSelect.addEventListener('change', loadProducts);

loadStores();
loadBrands();
loadCategories();
loadSizes();
loadProducts();
