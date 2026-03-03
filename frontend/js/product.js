/* Product detail page logic */

const API_BASE = window.location.hostname === 'localhost'
    ? 'http://localhost:8000'
    : '';

const container = document.getElementById('product-detail');

async function loadProduct() {
    const params = new URLSearchParams(window.location.search);
    const slug = params.get('slug');

    if (!slug) {
        container.innerHTML = '<div class="empty-state"><h2>No product specified</h2></div>';
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/api/products/${slug}`);
        if (!res.ok) throw new Error('Not found');
        const p = await res.json();

        document.title = `${p.name} | FASHION-`;
        container.innerHTML = renderDetail(p);
        initGallery(p.images);
        initSizes();
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

    // Gallery thumbnails
    const thumbs = p.images.map((img, i) => `
        <div class="gallery-thumb ${i === 0 ? 'active' : ''}" data-index="${i}">
            <img src="${img.image_url}" alt="${img.alt_text || p.name}">
        </div>
    `).join('');

    // Sizes
    const sizeButtons = p.sizes.map(s => `
        <button class="size-btn ${s.in_stock ? '' : 'out-of-stock'}"
                ${s.in_stock ? '' : 'disabled'}
                data-size="${esc(s.size_label)}">
            ${esc(s.size_label)}
        </button>
    `).join('');

    const sizesInStock = p.sizes.filter(s => s.in_stock).length;
    const totalSizes = p.sizes.length;

    // Description
    const desc = p.description
        ? `<div class="detail-description">
            <h3>Description</h3>
            <div>${p.description}</div>
           </div>`
        : '';

    return `
        <div class="detail-gallery">
            <div class="gallery-main">
                ${mainImg ? `<img id="main-image" src="${mainImg}" alt="${esc(p.name)}">` : ''}
            </div>
            ${p.images.length > 1 ? `<div class="gallery-thumbs">${thumbs}</div>` : ''}
        </div>

        <div class="detail-info">
            <div>
                <div class="detail-brand">${esc(p.brand)}</div>
                <h1 class="detail-name">${esc(p.name)}</h1>
                ${p.colorway ? `<div class="detail-colorway">${esc(p.colorway)}</div>` : ''}
            </div>

            <div class="detail-price-block">
                <div class="detail-prices">
                    <span class="detail-price-sale">€${p.sale_price.toFixed(2)}</span>
                    ${p.original_price > p.sale_price
                        ? `<span class="detail-price-original">€${p.original_price.toFixed(2)}</span>
                           <span class="detail-discount-badge">-${p.discount_pct}%</span>`
                        : ''}
                </div>
                ${p.original_price > p.sale_price
                    ? `<div class="detail-savings">You save €${savings}</div>`
                    : ''}
                <div class="detail-shipping">
                    Shipping to Latvia: ${freeShip
                        ? '<span style="color: var(--success); font-weight: 600;">FREE</span>'
                        : `<span class="detail-total">€${p.shipping_cost.toFixed(2)}</span> via ${esc(p.store_name)}`
                    }
                    <br>
                    Total cost: <span class="detail-total">€${freeShip ? p.sale_price.toFixed(2) : totalCost.toFixed(2)}</span>
                </div>
            </div>

            ${p.sizes.length > 0 ? `
                <div class="size-selector">
                    <h3>Select Size (${sizesInStock}/${totalSizes} available)</h3>
                    <div class="size-grid">${sizeButtons}</div>
                </div>
            ` : ''}

            <a href="${esc(p.product_url)}" target="_blank" rel="noopener" class="buy-btn">
                Buy Now at ${esc(p.store_name)} →
            </a>
            <p class="buy-btn-subtext">Opens the store in a new tab</p>

            ${desc}
        </div>
    `;
}

function initGallery(images) {
    const mainImg = document.getElementById('main-image');
    if (!mainImg || images.length <= 1) return;

    document.querySelectorAll('.gallery-thumb').forEach(thumb => {
        thumb.addEventListener('click', () => {
            const idx = parseInt(thumb.dataset.index);
            mainImg.src = images[idx].image_url;
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
