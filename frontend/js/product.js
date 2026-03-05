/* Product detail page logic */

const API_BASE = '';
const container = document.getElementById('product-detail');

let currentSlug = null;
let currentCategory = null;

/**
 * Transform image URL for display.
 * - END Clothing: route through image proxy
 * - Shopify: request specific width
 * - Other: return as-is
 */
function productImg(url, width) {
    if (!url) return '';
    if (url.includes('media.endclothing.com')) {
        return `${API_BASE}/api/image-proxy?url=${encodeURIComponent(url)}`;
    }
    url = url.replace(/_(pico|icon|thumb|small|compact|medium|large|grande|original|master|\d+x\d*|\d*x\d+)\./i, '.');
    return url.replace(/(\.[a-z]{3,4})(\?.*)?$/i, `_${width}x$1$2`);
}

async function loadProduct() {
    const params = new URLSearchParams(window.location.search);
    const slug = params.get('slug');
    currentSlug = slug;

    if (!slug) {
        container.innerHTML = '<div class="empty-state"><h2>No product specified</h2></div>';
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/api/products/${slug}`);
        if (!res.ok) throw new Error('Not found');
        const p = await res.json();
        currentCategory = p.category || 'sneakers';

        document.title = `${p.name} | FASHION-`;
        container.innerHTML = renderDetail(p);
        initGallery(p.images);
        initSizes();
        initEditCategory();
        initDelete(p.slug, p.name);
    } catch (e) {
        container.innerHTML = `
            <div class="empty-state">
                <h2>Product not found</h2>
                <p><a href="/" class="back-link">Back to catalog</a></p>
            </div>`;
    }
}

function renderDetail(p) {
    const savings = (p.original_price - p.sale_price).toFixed(2);
    const totalCost = p.sale_price + p.shipping_cost;
    const freeShip = p.free_ship_min && p.sale_price >= p.free_ship_min;
    const mainImg = p.images.length > 0 ? p.images[0].image_url : '';

    const catLabels = { sneakers: '\ud83d\udc5f Sneakers', clothing: '\ud83d\udc55 Clothing', accessories: '\ud83c\udfa9 Accessories', kids: '\ud83e\udde1 Kids', toddler: '\ud83d\udc76 Toddler' };
    const catLabel = catLabels[p.category] || p.category || 'Unknown';

    const thumbs = p.images.map((img, i) => `
        <div class="gallery-thumb ${i === 0 ? 'active' : ''}" data-index="${i}">
            <img src="${productImg(img.image_url, 150)}" alt="${img.alt_text || p.name}">
        </div>
    `).join('');

    const sizeButtons = p.sizes.map(s => `
        <button class="size-btn ${s.in_stock ? '' : 'out-of-stock'}"
                ${s.in_stock ? '' : 'disabled'}
                data-size="${esc(s.size_label)}">
            ${esc(s.size_label)}
        </button>
    `).join('');

    const sizesInStock = p.sizes.filter(s => s.in_stock).length;
    const totalSizes = p.sizes.length;

    const desc = p.description
        ? `<div class="detail-description">
            <h3>Description</h3>
            <div>${p.description}</div>
           </div>`
        : '';

    return `
        <div class="detail-gallery">
            <div class="gallery-main">
                ${mainImg ? `<img id="main-image" src="${productImg(mainImg, 1200)}" alt="${esc(p.name)}">` : ''}
            </div>
            ${p.images.length > 1 ? `<div class="gallery-thumbs">${thumbs}</div>` : ''}
        </div>

        <div class="detail-info">
            <div>
                <div class="detail-brand">${esc(p.brand)}</div>
                <h1 class="detail-name">${esc(p.name)}</h1>
                ${p.colorway ? `<div class="detail-colorway">${esc(p.colorway)}</div>` : ''}
            </div>

            <!-- Category (editable) -->
            <div class="detail-category">
                <span class="category-label" id="category-display">${catLabel}</span>
                <button class="edit-btn" id="edit-category-btn" title="Change category">\u270e</button>
                <div class="category-editor hidden" id="category-editor">
                    <select class="filter-select" id="category-select">
                        <option value="sneakers" ${p.category === 'sneakers' ? 'selected' : ''}>\ud83d\udc5f Sneakers</option>
                        <option value="clothing" ${p.category === 'clothing' ? 'selected' : ''}>\ud83d\udc55 Clothing</option>
                        <option value="accessories" ${p.category === 'accessories' ? 'selected' : ''}>\ud83c\udfa9 Accessories</option>
                        <option value="kids" ${p.category === 'kids' ? 'selected' : ''}>\ud83e\udde1 Kids</option>
                        <option value="toddler" ${p.category === 'toddler' ? 'selected' : ''}>\ud83d\udc76 Toddler</option>
                    </select>
                    <button class="save-category-btn" id="save-category-btn">Save</button>
                    <button class="cancel-btn" id="cancel-category-btn">Cancel</button>
                </div>
            </div>

            <div class="detail-price-block">
                <div class="detail-prices">
                    <span class="detail-price-sale">\u20ac${p.sale_price.toFixed(2)}</span>
                    ${p.original_price > p.sale_price
                        ? `<span class="detail-price-original">\u20ac${p.original_price.toFixed(2)}</span>
                           <span class="detail-discount-badge">-${p.discount_pct}%</span>`
                        : ''}
                </div>
                ${p.original_price > p.sale_price
                    ? `<div class="detail-savings">You save \u20ac${savings}</div>`
                    : ''}
                <div class="detail-shipping">
                    Shipping to Latvia: ${freeShip
                        ? '<span style="color: var(--success); font-weight: 600;">FREE</span>'
                        : `<span class="detail-total">\u20ac${p.shipping_cost.toFixed(2)}</span> via ${esc(p.store_name)}`
                    }
                    <br>
                    Total cost: <span class="detail-total">\u20ac${freeShip ? p.sale_price.toFixed(2) : totalCost.toFixed(2)}</span>
                </div>
            </div>

            ${p.sizes.length > 0 ? `
                <div class="size-selector">
                    <h3>Select Size (${sizesInStock}/${totalSizes} available)</h3>
                    <div class="size-grid">${sizeButtons}</div>
                </div>
            ` : ''}

            <a href="${esc(p.product_url)}" target="_blank" rel="noopener" class="buy-btn">
                Buy Now at ${esc(p.store_name)} \u2192
            </a>
            <p class="buy-btn-subtext">Opens the store in a new tab</p>

            <button class="delete-btn" id="delete-btn">\ud83d\uddd1 Delete Product</button>

            ${desc}
        </div>
    `;
}

function initEditCategory() {
    const editBtn = document.getElementById('edit-category-btn');
    const editor = document.getElementById('category-editor');
    const saveBtn = document.getElementById('save-category-btn');
    const cancelBtn = document.getElementById('cancel-category-btn');
    const display = document.getElementById('category-display');
    const select = document.getElementById('category-select');

    if (!editBtn) return;

    editBtn.addEventListener('click', () => {
        editor.classList.remove('hidden');
        editBtn.classList.add('hidden');
    });

    cancelBtn.addEventListener('click', () => {
        editor.classList.add('hidden');
        editBtn.classList.remove('hidden');
    });

    saveBtn.addEventListener('click', async () => {
        const newCategory = select.value;
        try {
            const res = await fetch(`${API_BASE}/api/products/${currentSlug}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ category: newCategory }),
            });
            if (res.ok) {
                const catLabels = { sneakers: '\ud83d\udc5f Sneakers', clothing: '\ud83d\udc55 Clothing', accessories: '\ud83c\udfa9 Accessories', kids: '\ud83e\udde1 Kids', toddler: '\ud83d\udc76 Toddler' };
                display.textContent = catLabels[newCategory] || newCategory;
                editor.classList.add('hidden');
                editBtn.classList.remove('hidden');
                currentCategory = newCategory;
            } else {
                alert('Failed to update category');
            }
        } catch (e) {
            alert('Error: ' + e.message);
        }
    });
}

function initDelete(slug, name) {
    const btn = document.getElementById('delete-btn');
    if (!btn) return;

    btn.addEventListener('click', async () => {
        if (!confirm(`Delete "${name}"? This cannot be undone.`)) return;

        try {
            const res = await fetch(`${API_BASE}/api/products/${slug}`, { method: 'DELETE' });
            if (res.ok) {
                window.location.href = '/';
            } else {
                alert('Failed to delete product');
            }
        } catch (e) {
            alert('Error: ' + e.message);
        }
    });
}

function initGallery(images) {
    const mainImg = document.getElementById('main-image');
    if (!mainImg || images.length <= 1) return;

    document.querySelectorAll('.gallery-thumb').forEach(thumb => {
        thumb.addEventListener('click', () => {
            const idx = parseInt(thumb.dataset.index);
            mainImg.src = productImg(images[idx].image_url, 1200);
            document.querySelectorAll('.gallery-thumb').forEach(t => t.classList.remove('active'));
            thumb.classList.add('active');
        });
    });
}

function initSizes() {
    document.querySelectorAll('.size-btn:not(.out-of-stock)').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.size-btn').forEach(b => b.classList.remove('selected'));
            btn.classList.add('selected');
        });
    });
}

function esc(str) {
    const d = document.createElement('div');
    d.textContent = str || '';
    return d.innerHTML;
}

loadProduct();
