// =====================================================================
// INICIO DE SESIÓN: cada persona tiene SU PROPIO usuario y contraseña.
// El servidor decide qué rol tiene ('owner' o 'employee') y qué datos
// entrega según ese rol (ver app.py); aquí solo controlamos qué se
// muestra/oculta en pantalla.
// =====================================================================
let currentRole = null; // 'owner' | 'employee' | null
let currentDisplayName = '';
// Ya solo existe el perfil Administrador: cualquier cuenta que inicie
// sesión ve el detalle completo de Finanzas (utilidad y botón de
// cancelar venta) en la tabla de Ventas.
const isAdmin = true;

const loginScreen = document.getElementById('login-screen');
const appShell = document.getElementById('app-shell');
const profileSelect = document.getElementById('profile-select');
const adminLoginForm = document.getElementById('admin-login-form');
const loginError = document.getElementById('login-error');

function showProfileSelect() {
    adminLoginForm.classList.add('hidden');
    adminLoginForm.classList.remove('flex');
    profileSelect.classList.remove('hidden');
    loginError.classList.add('hidden');
    document.getElementById('admin-username').value = '';
    document.getElementById('admin-password').value = '';
}

function showCredentialsForm() {
    profileSelect.classList.add('hidden');
    adminLoginForm.classList.remove('hidden');
    adminLoginForm.classList.add('flex');
    document.getElementById('admin-username').focus();
}

function enterApp(role, displayName) {
    currentRole = role;
    currentDisplayName = displayName || '';
    // -------------------------------------------------------------
    // CORRECCIÓN DE SEGURIDAD/PRIVACIDAD: antes, si un Administrador
    // se quedaba viendo "Finanzas" y cerraba sesión, esa pantalla seguía
    // marcada como "activa" en el HTML. Si justo después alguien entraba
    // como "Usuario", por una fracción de segundo (hasta dar clic de
    // nuevo en Finanzas) se seguían viendo los montos de Administrador,
    // porque eran datos viejos que nunca se borraron del navegador.
    //
    // Ahora, CADA VEZ que se entra a la app (login nuevo o sesión
    // restaurada al recargar la página), forzamos que la pantalla activa
    // sea siempre "Caja Principal" y borramos cualquier número de
    // finanzas que haya quedado de una sesión anterior. Así, aunque el
    // usuario nuevo entre directo a Finanzas, jamás puede llegar a ver
    // ni un instante de información que no le corresponde: tiene que
    // cargarse de nuevo desde el servidor, que ya valida el rol.
    resetToDefaultView();
    clearSensitiveFinanceData();

    loginScreen.classList.add('hidden');
    appShell.classList.remove('hidden');
    document.getElementById('current-role-label').textContent = currentDisplayName || (role === 'owner' ? 'Dueño' : 'Empleado');
    document.getElementById('current-role-sublabel').textContent = role === 'owner' ? 'Dueño' : 'Empleado';

    // El apartado "Usuarios" (crear/desactivar cuentas y contraseñas) es
    // exclusivo del Dueño. El servidor también lo protege por su cuenta
    // (ver app.py: login_required('owner')), esto es solo la parte visual.
    const usersNavBtn = document.querySelector('#nav-menu button[data-target="view-users"]');
    if (usersNavBtn) usersNavBtn.classList.toggle('hidden', role !== 'owner');

    document.getElementById('barcode-input').focus();
}

function resetToDefaultView() {
    navButtons.forEach(b => {
        b.classList.remove('bg-primary-soft', 'text-primary-dark');
        b.classList.add('text-ink/70');
    });
    const posBtn = document.querySelector('#nav-menu button[data-target="view-pos"]');
    if (posBtn) {
        posBtn.classList.remove('text-ink/70');
        posBtn.classList.add('bg-primary-soft', 'text-primary-dark');
    }
    sections.forEach(sec => sec.classList.remove('active'));
    const posSection = document.getElementById('view-pos');
    if (posSection) posSection.classList.add('active');
}

function clearSensitiveFinanceData() {
    document.getElementById('finance-kpis').classList.add('hidden');
    document.getElementById('finance-restricted-note').classList.add('hidden');
    document.getElementById('finance-general-kpis').classList.add('hidden');
    document.getElementById('finance-history-section').classList.add('hidden');
    document.getElementById('th-profit').classList.add('hidden');
    document.getElementById('th-action').classList.add('hidden');
    document.getElementById('fin-income').textContent = '$0.00';
    document.getElementById('fin-costs').textContent = '$0.00';
    document.getElementById('fin-profit').textContent = '$0.00';
    document.getElementById('fin-gen-income').textContent = '$0.00';
    document.getElementById('fin-gen-costs').textContent = '$0.00';
    document.getElementById('fin-gen-profit').textContent = '$0.00';
    document.getElementById('finance-history-list').innerHTML = '';
    document.getElementById('sales-history-body').innerHTML = '';
    document.getElementById('sales-history-title').textContent = 'Ventas de Hoy';
    document.getElementById('btn-back-to-today').classList.add('hidden');
    selectedHistoryDate = null;
}

// Ambos botones (Usuario y Administrador) llevan al MISMO formulario de
// usuario/contraseña: el rol real lo decide el servidor según con qué
// cuenta se entre, no con qué botón se llegó hasta aquí. Se mantienen
// los dos botones solo para que la pantalla de bienvenida se vea y se
// sienta igual que antes.
document.getElementById('btn-profile-admin').addEventListener('click', showCredentialsForm);
document.getElementById('btn-back-to-profiles').addEventListener('click', showProfileSelect);

adminLoginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('admin-username').value.trim();
    const password = document.getElementById('admin-password').value;
    loginError.classList.add('hidden');

    try {
        const res = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            document.getElementById('admin-password').value = '';
            enterApp(data.role, data.display_name);
        } else {
            loginError.textContent = data.message || 'Usuario o contraseña incorrectos.';
            loginError.classList.remove('hidden');
        }
    } catch (err) {
        loginError.textContent = 'No se pudo conectar con el servidor.';
        loginError.classList.remove('hidden');
    }
});

document.getElementById('btn-logout').addEventListener('click', async () => {
    try { await fetch('/api/logout', { method: 'POST' }); } catch (e) { /* ignorar */ }
    currentRole = null;
    clearSensitiveFinanceData();
    resetToDefaultView();
    appShell.classList.add('hidden');
    loginScreen.classList.remove('hidden');
    showProfileSelect();
});

// --- CAMBIAR MI PROPIA CONTRASEÑA (disponible para cualquier perfil) ---
document.getElementById('btn-change-password').addEventListener('click', async () => {
    const current = prompt('Escribe tu contraseña ACTUAL:');
    if (current === null) return;
    const nueva = prompt('Escribe tu NUEVA contraseña (mínimo 8 caracteres):');
    if (nueva === null) return;
    const confirmNueva = prompt('Confirma tu NUEVA contraseña:');
    if (confirmNueva === null) return;

    if (nueva !== confirmNueva) { alert('Las dos contraseñas nuevas no coinciden.'); return; }

    try {
        const res = await fetch('/api/me/change_password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_password: current, new_password: nueva })
        });
        const data = await res.json();
        if (res.ok) alert('✔️ ' + data.message);
        else alert('⚠️ ' + data.error);
    } catch (e) {
        alert('⚠️ Ocurrió un error de conexión.');
    }
});

// Si ya había una sesión activa (por ejemplo, se recargó la página),
// entramos directo sin pedir el login de nuevo.
(async function checkExistingSession() {
    try {
        const res = await fetch('/api/session');
        const data = await res.json();
        if (data.role) enterApp(data.role, data.display_name);
    } catch (e) { /* sin conexión: se queda en la pantalla de login */ }
})();


// --- SISTEMA SPA: NAVEGACIÓN ---
const navButtons = document.querySelectorAll('#nav-menu button');
const sections = document.querySelectorAll('.view-section');

navButtons.forEach(btn => {
    btn.addEventListener('click', async () => {
        navButtons.forEach(b => {
            b.classList.remove('bg-primary-soft', 'text-primary-dark');
            b.classList.add('text-ink/70');
        });
        btn.classList.remove('text-ink/70');
        btn.classList.add('bg-primary-soft', 'text-primary-dark');

        const target = btn.getAttribute('data-target');
        sections.forEach(sec => sec.classList.remove('active'));
        document.getElementById(target).classList.add('active');

        if(target === 'view-pos') document.getElementById('barcode-input').focus();
        if(target === 'view-inventory') {
            await loadCategories();
            await loadInventory();
        }
        if(target === 'view-loans') {
            await loadInventory();
            await loadLoans();
            document.getElementById('loan-barcode-input').focus();
        }
        if(target === 'view-finances') loadFinances();
        if(target === 'view-topsellers') loadTopSellers();
        if(target === 'view-suppliers') loadSuppliers();
        if(target === 'view-notes') loadNotes();
        if(target === 'view-users') loadUsers();
    });
});

// --- OPERATORIA CENTRAL: TERMINAL DE VENTAS ---
let cart = [];
const barcodeInput = document.getElementById('barcode-input');
const manualSearch = document.getElementById('manual-search');
const btnSearch = document.getElementById('btn-search');
const btnClearCart = document.getElementById('btn-clear-cart');
const btnCheckout = document.getElementById('btn-checkout');

document.getElementById('view-pos').addEventListener('click', (e) => {
    if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'BUTTON') barcodeInput.focus();
});

barcodeInput.addEventListener('keypress', async (e) => {
    if (e.key === 'Enter') {
        const barcode = barcodeInput.value.trim();
        barcodeInput.value = '';
        if (barcode) {
            await fetchProduct(barcode, false);
        } else if (cart.length > 0) {
            // Caja vacía (nada escaneado) + Enter con productos en la
            // cuenta = cobrar. Así el cajero puede terminar la venta
            // completa sin soltar el teclado ni tocar el mouse.
            await checkoutCart();
        }
    }
});

async function runManualSearch() {
    const query = manualSearch.value.trim();
    if(query) await fetchProduct(query, true);
    manualSearch.value = '';
    barcodeInput.focus();
}

btnSearch.addEventListener('click', runManualSearch);

// Si el producto se escanea (o se escribe y se da Enter) en esta caja de
// texto visible en vez del campo invisible del escáner, también se agrega
// de inmediato: antes SOLO el botón "Buscar" disparaba la búsqueda, así
// que si el lector de código de barras mandaba el Enter aquí, no pasaba
// nada hasta que se le daba clic al botón a mano.
manualSearch.addEventListener('keypress', async (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        await runManualSearch();
    }
});

btnClearCart.addEventListener('click', () => {
    if(cart.length > 0 && confirm('¿Vaciar los productos de la cuenta actual?')) {
        cart = [];
        renderCart();
    }
    barcodeInput.focus();
});

async function fetchProduct(query, isManual) {
    try {
        const url = isManual ? `/api/product/search?q=${encodeURIComponent(query)}` : `/api/product/${query}`;
        const response = await fetch(url);
        const data = await response.json();
        if (!response.ok) { alert(data.error); return; }
        addToCart(data);
    } catch (e) { console.error('Error REST:', e); }
}

function addToCart(product) {
    const item = cart.find(i => i.id === product.id);
    if (item) {
        if (item.qty < product.stock) item.qty++;
        else alert('Límite de existencias alcanzado.');
    } else {
        if(product.stock > 0) cart.push({ ...product, qty: 1 });
        else alert('Artículo sin existencias.');
    }
    renderCart();
}

function renderCart() {
    const tbody = document.getElementById('cart-body');
    let total = 0;
    // RENDIMIENTO: antes cada artículo del carrito hacía "tbody.innerHTML +="
    // dentro del ciclo. Eso obliga al navegador a re-leer TODO el HTML ya
    // puesto, pegarle el pedazo nuevo, y volver a construir la tabla entera
    // desde cero en cada vuelta del ciclo (cada vez más lento mientras más
    // artículos tiene el carrito). Ahora se arma todo el texto primero y se
    // pinta UNA sola vez al final.
    const rowsHtml = cart.map((item, index) => {
        const sub = item.price * item.qty;
        total += sub;
        return `
            <tr class="hover:bg-paper/50 transition-colors duration-150">
                <td class="py-4 px-6 font-semibold text-ink">${item.name}</td>
                <td class="py-4 px-6 text-muted tabular-nums">$${item.price.toFixed(2)}</td>
                <td class="py-4 px-6 text-center">
                    <input type="number" min="1" max="${item.stock}" value="${item.qty}"
                        onchange="updateCartQty(${index}, this.value)"
                        onclick="this.select()"
                        class="w-20 text-center bg-paper px-2 py-1.5 rounded-full text-ink font-bold tabular-nums outline-none border border-transparent focus:border-primary/50 focus:bg-white transition-all">
                </td>
                <td class="py-4 px-6 text-right font-bold text-primary-dark tabular-nums">$${sub.toFixed(2)}</td>
                <td class="py-4 px-6 text-center"><button onclick="removeFromCart(${index})" class="text-danger hover:text-danger-dark hover:bg-danger-soft w-8 h-8 rounded-full font-bold transition-all duration-150 active:scale-90">✕</button></td>
            </tr>`;
    }).join('');
    tbody.innerHTML = rowsHtml;
    const totalEl = document.getElementById('total-display');
    totalEl.textContent = `$${total.toFixed(2)}`;
    if (total > 0) {
        totalEl.classList.remove('pulse-total');
        // Reiniciar la animación aunque el cambio sea muy seguido
        void totalEl.offsetWidth;
        totalEl.classList.add('pulse-total');
    }
}

window.removeFromCart = function(index) {
    cart.splice(index, 1);
    renderCart();
    barcodeInput.focus();
};

// Permite escribir directamente la cantidad de un artículo del carrito
// (por ejemplo, 11 o 299 piezas) en vez de tener que escanear el mismo
// código de barras una por una. Se limita entre 1 y el stock disponible
// de ese producto, para nunca vender más de lo que hay en existencia.
window.updateCartQty = function(index, rawValue) {
    const item = cart[index];
    if (!item) return;
    let qty = parseInt(rawValue, 10);
    if (isNaN(qty) || qty < 1) qty = 1;
    if (qty > item.stock) {
        qty = item.stock;
        alert(`Solo hay ${item.stock} unidades disponibles de "${item.name}".`);
    }
    item.qty = qty;
    renderCart();
    barcodeInput.focus();
};

async function checkoutCart() {
    if (cart.length === 0) return;
    const res = await fetch('/api/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cart })
    });
    if (res.ok) {
        const data = await res.json();
        cart = [];
        renderCart();
        if (data.sale) showTicket(data.sale);
    } else {
        const data = await res.json(); alert(data.error);
    }
    barcodeInput.focus();
}

btnCheckout.addEventListener('click', checkoutCart);

// --- TICKET DE VENTA: vista previa fiel a un recibo real + impresión ---

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
}

function buildTicketHTML(sale) {
    const itemsRows = sale.items.map(it => `
        <tr><td colspan="2" style="padding-top:5px;">${escapeHtml(it.product_name)}</td></tr>
        <tr>
            <td>${it.quantity} x $${it.sale_price.toFixed(2)}</td>
            <td style="text-align:right; font-weight:700;">$${it.subtotal.toFixed(2)}</td>
        </tr>
    `).join('');

    return `
        <div class="t-center t-brand">PUNTO DE VENTA</div>
        <div class="t-center t-sub">Ticket de compra</div>
        <div class="t-divider"></div>
        <div class="t-row"><span>Folio:</span><span>#TR-${sale.id}</span></div>
        <div class="t-row"><span>Fecha:</span><span>${escapeHtml(sale.timestamp)}</span></div>
        <div class="t-divider"></div>
        <div class="t-items"><table>${itemsRows}</table></div>
        <div class="t-divider"></div>
        <div class="t-row t-total"><span>TOTAL</span><span>$${sale.total.toFixed(2)}</span></div>
        <div class="t-divider"></div>
        <div class="t-center" style="margin-top:6px;">¡Gracias por su compra!</div>
        <div class="t-center t-foot">Conserve este ticket</div>
    `;
}

function showTicket(sale) {
    document.getElementById('ticket-print').innerHTML = buildTicketHTML(sale);
    const modal = document.getElementById('ticket-modal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    // YA NO se imprime automáticamente: se muestra el ticket de "Venta
    // completada" en pantalla y el cajero decide si quiere darle
    // "Imprimir" (o simplemente "Nueva venta" para seguir cobrando sin
    // gastar papel en cada ticket).
}

window.closeTicketModal = function () {
    const modal = document.getElementById('ticket-modal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    barcodeInput.focus();
};

window.printTicket = function () {
    window.print();
};

// --- ENTORNO DE INVENTARIO: SECCIONES Y BUSCADOR ---
let localInventory = [];
let localCategories = [];
let activeSectionFilter = 'ALL';
let searchInventoryQuery = '';

async function loadCategories() {
    const res = await fetch('/api/categories');
    localCategories = await res.json();

    const invSelect = document.getElementById('inv-category');
    const editSelect = document.getElementById('edit-category');
    invSelect.innerHTML = '';
    editSelect.innerHTML = '';

    localCategories.forEach(cat => {
        const opt1 = document.createElement('option');
        opt1.value = cat.id; opt1.textContent = cat.name;
        invSelect.appendChild(opt1);

        const opt2 = document.createElement('option');
        opt2.value = cat.id; opt2.textContent = cat.name;
        editSelect.appendChild(opt2);
    });

    const tabsContainer = document.getElementById('inventory-tabs');
    tabsContainer.innerHTML = `<button data-section="ALL" class="px-4 py-1.5 text-xs rounded-lg transition-all duration-150 ${activeSectionFilter === 'ALL' ? 'bg-white text-ink shadow-soft font-bold' : 'text-muted font-semibold hover:text-ink'}">Todos</button>`;
    
    localCategories.forEach(cat => {
        const isActive = (activeSectionFilter == cat.id);
        tabsContainer.innerHTML += `<button data-section="${cat.id}" class="px-4 py-1.5 text-xs rounded-lg transition-all duration-150 ${isActive ? 'bg-white text-ink shadow-soft font-bold' : 'text-muted font-semibold hover:text-ink'}">${cat.name}</button>`;
    });
    bindTabEvents();

    const catList = document.getElementById('categories-list');
    catList.innerHTML = '';
    localCategories.forEach(cat => {
        catList.innerHTML += `
            <li class="flex justify-between items-center py-1.5">
                <span class="font-medium text-ink">${cat.name}</span>
                ${cat.name !== 'General' ? `<button onclick="deleteCategory(${cat.id})" class="text-danger hover:text-danger-dark font-bold transition-colors duration-150">✕</button>` : '<span class="text-muted italic">Fijo</span>'}
            </li>`;
    });
}

function bindTabEvents() {
    const tabButtons = document.querySelectorAll('#inventory-tabs button');
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            tabButtons.forEach(b => {
                b.className = "px-4 py-1.5 text-xs rounded-lg transition-all duration-150 text-muted font-semibold hover:text-ink";
            });
            btn.className = "px-4 py-1.5 text-xs font-bold rounded-lg transition-all duration-150 bg-white text-ink shadow-soft";
            activeSectionFilter = btn.getAttribute('data-section');
            applyInventoryFilters();
        });
    });
}

document.getElementById('add-category-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = document.getElementById('cat-name');
    const name = input.value.trim();
    const res = await fetch('/api/categories', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
    });
    if (res.ok) {
        input.value = '';
        await loadCategories();
    } else {
        const data = await res.json(); alert(data.error);
    }
});

window.deleteCategory = async function(id) {
    if(!confirm('¿Remover esta sección? Los productos adscritos volverán a la sección "General".')) return;
    const res = await fetch(`/api/categories/${id}`, { method: 'DELETE' });
    if(res.ok) {
        if(activeSectionFilter == id) activeSectionFilter = 'ALL';
        await loadCategories();
        await loadInventory();
    } else {
        const data = await res.json(); alert(data.error);
    }
};

document.getElementById('inventory-search-input').addEventListener('input', (e) => {
    searchInventoryQuery = e.target.value.toLowerCase().trim();
    applyInventoryFilters();
});

// --- AUTOCOMPLETAR NOMBRE DE PRODUCTO AL ESCANEAR CÓDIGO DE BARRAS ---
// Como el código de barras es único por producto, al escanearlo (o
// teclearlo) en el alta de inventario se consulta primero si ya existe
// localmente, y si no, se busca en una base de datos pública de
// productos (Open Food Facts) para autocompletar el nombre comercial,
// ahorrando tecleo. El usuario siempre puede corregir el nombre antes
// de guardar.
(function setupBarcodeAutoFill() {
    const barcodeField = document.getElementById('inv-barcode');
    const nameField = document.getElementById('inv-name');
    const categorySelect = document.getElementById('inv-category');
    const hint = document.getElementById('inv-barcode-hint');
    if (!barcodeField || !hint) return;

    let debounceTimer = null;
    let lastLookedUp = '';

    function setHint(text, kind) {
        hint.textContent = text;
        hint.classList.remove('hidden', 'text-danger', 'text-sage-dark', 'text-muted');
        if (!text) { hint.classList.add('hidden'); return; }
        hint.classList.add(kind === 'error' ? 'text-danger' : kind === 'ok' ? 'text-sage-dark' : 'text-muted');
    }

    async function selectOrCreateCategory(catName, catId) {
        if (!categorySelect || !catName) return;
        // Intentar con el id que ya mandó el servidor
        if (catId) {
            const opt = categorySelect.querySelector(`option[value="${catId}"]`);
            if (opt) { categorySelect.value = catId; return; }
        }
        // Buscar por nombre exacto en el <select>
        for (const opt of categorySelect.options) {
            if (opt.text.trim().toLowerCase() === catName.trim().toLowerCase()) {
                categorySelect.value = opt.value;
                return;
            }
        }
        // Si no existe, crearla en el servidor y agregarla al select
        try {
            const res = await fetch('/api/categories', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: catName })
            });
            if (res.ok) {
                const data = await res.json();
                const newOpt = document.createElement('option');
                newOpt.value = data.id;
                newOpt.textContent = catName;
                categorySelect.appendChild(newOpt);
                categorySelect.value = data.id;
            }
        } catch (e) { /* sin conexión: no pasa nada, el usuario elige manualmente */ }
    }

    async function lookupBarcode(code) {
        if (!code || code.length < 6 || code === lastLookedUp) return;
        lastLookedUp = code;
        setHint('🔎 Buscando producto por código de barras...', 'muted');
        try {
            const res = await fetch(`/api/barcode_lookup/${encodeURIComponent(code)}`);
            const data = await res.json();

            if (data.duplicate) {
                setHint(`⚠️ Este código ya pertenece a "${data.name}" (Sección: ${data.category_name || '?'}).`, 'error');
                return;
            }
            if (data.found) {
                if (!nameField.value.trim()) nameField.value = data.name;
                // Autoseleccionar (o crear) la sección que corresponde
                await selectOrCreateCategory(data.category_name, data.category_id);
                setHint(`✔️ Producto identificado: ${data.name} → Sección asignada: ${data.category_name || 'General'}`, 'ok');
            } else {
                setHint('No se encontró ese código en bases públicas; captura el nombre y la sección manualmente.', 'muted');
            }
        } catch (e) {
            setHint('', null);
        }
    }

    // Los lectores de código de barras "escriben" muy rápido y casi
    // siempre terminan presionando Enter solos: ahí disparamos de
    // inmediato la búsqueda.
    barcodeField.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            clearTimeout(debounceTimer);
            lookupBarcode(barcodeField.value.trim());
        }
    });

    // Si lo teclea a mano, esperamos a que deje de escribir.
    barcodeField.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        const code = barcodeField.value.trim();
        if (!code) { setHint('', null); lastLookedUp = ''; return; }
        debounceTimer = setTimeout(() => lookupBarcode(code), 600);
    });
})();

document.getElementById('add-product-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = {
        barcode: document.getElementById('inv-barcode').value.trim(),
        name: document.getElementById('inv-name').value.trim(),
        brand: document.getElementById('inv-brand').value.trim(),
        category_id: document.getElementById('inv-category').value,
        cost: document.getElementById('inv-cost').value,
        price: document.getElementById('inv-price').value,
        stock: document.getElementById('inv-stock').value
    };
    const res = await fetch('/api/inventory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    if(res.ok) {
        document.getElementById('add-product-form').reset();
        const hint = document.getElementById('inv-barcode-hint');
        if (hint) hint.classList.add('hidden');
        await loadInventory();
    } else { const err = await res.json(); alert(err.error); }
});

async function loadInventory() {
    const res = await fetch('/api/inventory');
    localInventory = await res.json();
    applyInventoryFilters();
}

function applyInventoryFilters() {
    const tbody = document.getElementById('inventory-body');
    const filtered = localInventory.filter(p => {
        const matchSection = (activeSectionFilter === 'ALL' || p.category_id == activeSectionFilter);
        const matchSearch = p.name.toLowerCase().includes(searchInventoryQuery) || p.barcode.includes(searchInventoryQuery);
        return matchSection && matchSearch;
    });

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center py-8 text-muted text-sm">Sin coincidencias registradas.</td></tr>`;
        return;
    }

    // RENDIMIENTO: esta función se ejecuta en CADA tecla que escribes en el
    // buscador de Inventario. Antes reconstruía la tabla entera fila por
    // fila con "tbody.innerHTML +=", lo cual hace que el navegador re-lea y
    // re-arme TODO lo ya puesto en cada vuelta del ciclo — con cientos de
    // productos, cada letra que escribías se sentía más lenta que la
    // anterior. Ahora se arma el texto completo primero (un solo string) y
    // se pinta en la tabla UNA sola vez.
    tbody.innerHTML = filtered.map(p => {
        const stockPill = p.stock < 5
            ? `<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-danger-soft text-danger-dark">${p.stock}</span>`
            : `<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-sage-soft text-sage-dark">${p.stock}</span>`;

        return `
            <tr class="hover:bg-paper/40 border-b border-line transition-colors duration-150">
                <td class="py-3 px-2 font-semibold text-ink">${p.name}</td>
                <td class="py-3 px-2 font-mono text-muted text-sm">${p.barcode ? p.barcode : '<span class="text-muted/60 italic font-sans">Sin código</span>'}</td>
                <td class="py-3 px-2 text-xs"><span class="px-2.5 py-1 bg-paper text-ink/80 rounded-full font-medium">${p.category_name}</span></td>
                <td class="py-3 px-2 text-xs text-ink/70">${p.brand ? p.brand : '<span class="text-muted/60 italic">—</span>'}</td>
                <td class="py-3 px-2 text-muted tabular-nums">$${p.cost.toFixed(2)}</td>
                <td class="py-3 px-2 font-medium text-ink tabular-nums">$${p.price.toFixed(2)}</td>
                <td class="py-3 px-2 text-center">${stockPill}</td>
                <td class="py-3 px-2 text-center">
                    <button onclick='openEditModal(${JSON.stringify(p)})' class="text-primary hover:text-primary-dark font-semibold mr-3 transition-colors duration-150 text-sm">Editar</button>
                    <button onclick='deleteProduct(${p.id})' class="text-danger hover:text-danger-dark font-semibold transition-colors duration-150 text-sm">Eliminar</button>
                </td>
            </tr>`;
    }).join('');
}

const editModal = document.getElementById('edit-modal');

window.openEditModal = function(product) {
    document.getElementById('edit-id').value = product.id;
    document.getElementById('edit-barcode').value = product.barcode;
    document.getElementById('edit-name').value = product.name;
    document.getElementById('edit-brand').value = product.brand || '';
    document.getElementById('edit-category').value = product.category_id;
    document.getElementById('edit-cost').value = product.cost;
    document.getElementById('edit-price').value = product.price;
    document.getElementById('edit-stock').value = product.stock;
    editModal.classList.remove('hidden');
};

window.closeEditModal = function() { editModal.classList.add('hidden'); };

document.getElementById('edit-product-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const id = document.getElementById('edit-id').value;
    const data = {
        barcode: document.getElementById('edit-barcode').value.trim(),
        name: document.getElementById('edit-name').value.trim(),
        brand: document.getElementById('edit-brand').value.trim(),
        category_id: document.getElementById('edit-category').value,
        cost: document.getElementById('edit-cost').value,
        price: document.getElementById('edit-price').value,
        stock: document.getElementById('edit-stock').value
    };
    const res = await fetch(`/api/inventory/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    if(res.ok) { closeEditModal(); await loadInventory(); }
    else { const err = await res.json(); alert(err.error); }
});

window.deleteProduct = async function(id) {
    if(!confirm('¿Eliminar artículo permanentemente?')) return;
    const res = await fetch(`/api/inventory/${id}`, { method: 'DELETE' });
    if(res.ok) await loadInventory();
};

// =====================================================================
// PRÉSTAMOS / FIADO
// =====================================================================
// Cada cliente con una cuenta abierta aparece como una tarjeta con todos
// sus artículos (con su fecha) y el total que debe. Escanear un código
// (o escribir el nombre del producto) lo agrega de inmediato a la
// cuenta del nombre que esté escrito en "Nombre del Cliente".
let localLoans = [];

async function loadLoans() {
    const res = await fetch('/api/loans');
    localLoans = await res.json();
    renderLoans();

    // Sugerencias de autocompletado con los nombres que ya tienen cuenta
    // abierta, para no tener que retecear el nombre completo cada vez.
    const datalist = document.getElementById('loan-customer-suggestions');
    datalist.innerHTML = localLoans.map(l => `<option value="${escapeHtml(l.customer_name)}"></option>`).join('');
}

function renderLoans() {
    const container = document.getElementById('loans-list');
    if (localLoans.length === 0) {
        container.innerHTML = `<div class="text-center py-12 text-muted text-sm">🤝 No hay cuentas de préstamo abiertas por el momento.</div>`;
        return;
    }

    container.innerHTML = localLoans.map(loan => {
        const initial = escapeHtml(loan.customer_name.trim().charAt(0).toUpperCase() || '?');
        // Plegado por default (para no ver una lista gigante si hay
        // muchos artículos o muchos clientes); se recuerda si el usuario
        // ya lo había desplegado antes en esta misma sesión de pantalla.
        const isOpen = expandedLoanIds.has(loan.id);
        const itemsRows = loan.items.map(it => `
            <tr class="border-b border-white/50 last:border-0">
                <td class="py-2 px-3 text-xs text-muted whitespace-nowrap">${it.date}</td>
                <td class="py-2 px-3 text-ink">${escapeHtml(it.product_name)}</td>
                <td class="py-2 px-3 text-center font-semibold">${it.quantity}</td>
                <td class="py-2 px-3 text-right tabular-nums text-muted">$${it.unit_price.toFixed(2)}</td>
                <td class="py-2 px-3 text-right font-bold tabular-nums text-ink">$${it.subtotal.toFixed(2)}</td>
                <td class="py-2 px-3 text-center">
                    <button onclick="removeLoanItem(${loan.id}, ${it.id})" title="Quitar este artículo" class="text-danger/70 hover:text-danger font-bold transition-colors duration-150">✕</button>
                </td>
            </tr>`).join('');

        return `
        <div class="glass-input rounded-2xl border border-white/70 p-5">
            <div class="flex items-center justify-between flex-wrap gap-4 mb-4">
                <div class="flex items-center gap-3">
                    <div class="w-12 h-12 rounded-full bg-primary-soft text-primary-dark flex items-center justify-center font-display font-black text-lg flex-shrink-0">${initial}</div>
                    <div>
                        <p class="font-display font-bold text-ink text-lg leading-tight">${escapeHtml(loan.customer_name)}</p>
                        <p class="text-xs text-muted">Cuenta abierta desde el ${loan.created_at}</p>
                    </div>
                </div>
                <div class="flex items-center gap-3 flex-wrap">
                    <div class="text-right">
                        <p class="text-[10px] text-muted font-bold uppercase tracking-wider">Debe</p>
                        <p class="font-display font-black text-2xl text-danger tabular-nums">$${loan.total.toFixed(2)}</p>
                    </div>
                    <button onclick="payLoan(${loan.id}, '${escapeHtml(loan.customer_name)}')" class="bg-sage hover:bg-sage-dark text-white font-display font-bold px-5 py-2.5 rounded-xl shadow-md transition-all duration-200 active:scale-95 text-sm whitespace-nowrap">✔️ Marcar Pagado</button>
                    <button onclick="cancelLoan(${loan.id}, '${escapeHtml(loan.customer_name)}')" class="text-danger hover:text-danger-dark text-xs font-bold px-2 py-2.5 transition-colors duration-150">Cancelar</button>
                </div>
            </div>
            <button onclick="toggleLoanItems(${loan.id})" class="w-full text-left text-xs font-bold text-primary-dark bg-primary-soft hover:bg-primary/20 px-4 py-2.5 rounded-xl transition-colors mb-2 flex items-center justify-between">
                <span>${isOpen ? '▾ Ocultar' : '▸ Ver'} productos (${loan.items.length})</span>
            </button>
            <div class="overflow-x-auto rounded-xl border border-white/60 ${isOpen ? '' : 'hidden'}">
                <table class="w-full text-sm bg-white/40">
                    <thead class="text-muted uppercase text-[10px] font-bold bg-white/50">
                        <tr>
                            <th class="text-left py-2 px-3">Fecha</th>
                            <th class="text-left py-2 px-3">Producto</th>
                            <th class="text-center py-2 px-3">Cant.</th>
                            <th class="text-right py-2 px-3">P. Unit.</th>
                            <th class="text-right py-2 px-3">Subtotal</th>
                            <th class="py-2 px-3"></th>
                        </tr>
                    </thead>
                    <tbody>${itemsRows}</tbody>
                </table>
            </div>
        </div>`;
    }).join('');
}

// Recuerda qué cuentas de préstamo tiene el usuario desplegadas en esta
// sesión de pantalla, para que no se vuelvan a cerrar solas cada vez que
// se recarga la lista (por ejemplo, después de agregar un artículo).
const expandedLoanIds = new Set();
window.toggleLoanItems = function(loanId) {
    if (expandedLoanIds.has(loanId)) expandedLoanIds.delete(loanId);
    else expandedLoanIds.add(loanId);
    renderLoans();
};

function setLoanHint(text, kind) {
    const hint = document.getElementById('loan-form-hint');
    hint.textContent = text;
    hint.classList.remove('hidden', 'text-danger', 'text-sage-dark', 'text-muted');
    if (!text) { hint.classList.add('hidden'); return; }
    hint.classList.add(kind === 'error' ? 'text-danger' : kind === 'ok' ? 'text-sage-dark' : 'text-muted');
}

async function registerLoanItem() {
    const nameField = document.getElementById('loan-customer-name');
    const barcodeField = document.getElementById('loan-barcode-input');
    const qtyField = document.getElementById('loan-quantity');

    const customerName = nameField.value.trim();
    const query = barcodeField.value.trim();
    const quantity = parseInt(qtyField.value, 10) || 1;

    if (!customerName) {
        setLoanHint('⚠️ Primero escribe el nombre del cliente.', 'error');
        nameField.focus();
        return;
    }
    if (!query) return;

    try {
        const prodRes = await fetch(`/api/product/search?q=${encodeURIComponent(query)}`);
        const prodData = await prodRes.json();
        if (!prodRes.ok) {
            setLoanHint(`⚠️ ${prodData.error}`, 'error');
            barcodeField.value = '';
            return;
        }

        const loanRes = await fetch('/api/loans', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ customer_name: customerName, product_id: prodData.id, quantity })
        });
        const loanData = await loanRes.json();
        if (!loanRes.ok) {
            setLoanHint(`⚠️ ${loanData.error}`, 'error');
            return;
        }

        setLoanHint(`✔️ "${prodData.name}" agregado a la cuenta de ${customerName}.`, 'ok');
        barcodeField.value = '';
        qtyField.value = 1;
        await loadLoans();
        await loadInventory();
    } catch (err) {
        setLoanHint('⚠️ Ocurrió un error de conexión.', 'error');
    }
    barcodeField.focus();
}

document.getElementById('loan-btn-add').addEventListener('click', registerLoanItem);
document.getElementById('loan-barcode-input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); registerLoanItem(); }
});

window.payLoan = async function(loanId, customerName) {
    if (!confirm(`¿Marcar como PAGADA toda la cuenta de "${customerName}"? Esto la registrará en Finanzas y la quitará de Préstamos.`)) return;
    const res = await fetch(`/api/loans/${loanId}/pay`, { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
        await loadLoans();
        alert(data.message);
    } else {
        alert(data.error);
    }
};

window.cancelLoan = async function(loanId, customerName) {
    if (!confirm(`¿Cancelar TODA la cuenta de "${customerName}" sin cobrar nada? El stock de sus artículos regresará al inventario.`)) return;
    const res = await fetch(`/api/loans/${loanId}`, { method: 'DELETE' });
    if (res.ok) {
        await loadLoans();
        await loadInventory();
    } else {
        const data = await res.json(); alert(data.error);
    }
};

window.removeLoanItem = async function(loanId, itemId) {
    if (!confirm('¿Quitar este artículo de la cuenta? Su stock regresará al inventario.')) return;
    const res = await fetch(`/api/loans/${loanId}/items/${itemId}`, { method: 'DELETE' });
    if (res.ok) {
        await loadLoans();
        await loadInventory();
    } else {
        const data = await res.json(); alert(data.error);
    }
};

let selectedHistoryDate = null; // null = viendo "Hoy"; si no, es un date_iso 'YYYY-MM-DD'
let serverTodayIso = null;      // 'hoy' según la hora de México (la calcula el servidor)

async function loadFinances() {
    // Cada cuenta ve sus propias Finanzas completas (ingresos, costos,
    // utilidad e historial), porque cada cuenta funciona como su propio
    // negocio independiente. La única pantalla restringida al Dueño es
    // "Usuarios" (ver enterApp).
    document.getElementById('finance-kpis').classList.remove('hidden');
    document.getElementById('finance-restricted-note').classList.add('hidden');
    document.getElementById('finance-general-kpis').classList.remove('hidden');
    document.getElementById('finance-history-section').classList.remove('hidden');
    document.getElementById('th-profit').classList.remove('hidden');
    document.getElementById('th-action').classList.remove('hidden');

    try {
        const resToday = await fetch('/api/today');
        const dataToday = await resToday.json();
        serverTodayIso = dataToday.date_iso;
        document.getElementById('finance-today-label').textContent = `📅 Hoy · ${dataToday.date}`;
    } catch (e) { /* sin conexión: se sigue intentando mostrar lo que se pueda */ }

    const resFin = await fetch('/api/finances');
    const dataFin = await resFin.json();

    document.getElementById('fin-income').textContent = `$${dataFin.today.income.toFixed(2)}`;
    document.getElementById('fin-costs').textContent = `$${dataFin.today.costs.toFixed(2)}`;
    document.getElementById('fin-profit').textContent = `$${dataFin.today.profit.toFixed(2)}`;

    document.getElementById('fin-gen-income').textContent = `$${dataFin.general.income.toFixed(2)}`;
    document.getElementById('fin-gen-costs').textContent = `$${dataFin.general.costs.toFixed(2)}`;
    document.getElementById('fin-gen-profit').textContent = `$${dataFin.general.profit.toFixed(2)}`;

    renderFinanceHistory(dataFin.history);

    await loadSalesTable();
}

function renderFinanceHistory(history) {
    const container = document.getElementById('finance-history-list');
    if (!history || history.length === 0) {
        container.innerHTML = `<p class="text-muted text-sm">Todavía no hay días anteriores registrados.</p>`;
        return;
    }
    container.innerHTML = history.map(day => `
        <div class="relative group min-w-[120px]">
            <button onclick="viewHistoryDay('${day.date_iso}', '${day.date}')" class="w-full text-left bg-white/60 hover:bg-white border ${selectedHistoryDate === day.date_iso ? 'border-primary ring-2 ring-primary/40' : 'border-white/80'} rounded-xl px-4 py-3 pr-8 transition-all duration-150 hover:-translate-y-0.5">
                <p class="font-display font-bold text-ink text-sm">${day.date}</p>
                <p class="text-[11px] text-muted mb-1">${day.count} venta${day.count === 1 ? '' : 's'}</p>
                <p class="text-sm font-bold text-sage-dark tabular-nums">$${day.income.toFixed(2)}</p>
            </button>
            <button onclick="event.stopPropagation(); deleteFinanceDay('${day.date_iso}', '${day.date}')" title="Borrar las finanzas de este día" class="absolute top-1.5 right-1.5 w-5 h-5 flex items-center justify-center rounded-full bg-danger-soft text-danger hover:bg-danger hover:text-white text-[11px] font-bold transition-all opacity-70 group-hover:opacity-100">✕</button>
        </div>
    `).join('');
}

// Botón para ocultar/mostrar la fila de tarjetas del Historial por Día,
// sin perder ningún dato: solo cambia si se ven o no en pantalla.
let financeHistoryVisible = true;
document.getElementById('btn-toggle-finance-history').addEventListener('click', () => {
    financeHistoryVisible = !financeHistoryVisible;
    document.getElementById('finance-history-list').classList.toggle('hidden', !financeHistoryVisible);
    document.getElementById('btn-toggle-finance-history').textContent = financeHistoryVisible ? '🙈 Ocultar Días' : '👁️ Mostrar Días';
});

// Borra las finanzas (ventas) de UN SOLO DÍA. No toca el inventario ni
// los productos, solo el registro de ventas de ese día.
window.deleteFinanceDay = async function(dateIso, dateLabel) {
    if (!confirm(`¿Borrar las finanzas (ventas) del ${dateLabel}?\n\nEsto NO afecta tu inventario ni tus productos, solo se borrará el registro de ventas de ese día. No se puede deshacer.`)) return;

    const res = await fetch(`/api/finances/day/${dateIso}`, { method: 'DELETE' });
    if (res.ok) {
        if (selectedHistoryDate === dateIso) {
            selectedHistoryDate = null;
            document.getElementById('sales-history-title').textContent = 'Ventas de Hoy';
            document.getElementById('btn-back-to-today').classList.add('hidden');
        }
        await loadFinances();
    } else {
        const data = await res.json(); alert('⚠️ ' + (data.error || 'No se pudo borrar.'));
    }
};

// Borra TODAS las finanzas (todas las ventas de siempre) de la cuenta
// actual. El inventario y los productos quedan completamente intactos.
document.getElementById('btn-delete-all-finances').addEventListener('click', async () => {
    if (!confirm('¿Borrar TODAS las finanzas (todo el historial de ventas) de esta cuenta?\n\nTu inventario y tus productos NO se tocan, pero los montos de Ingresos/Costos/Utilidad y todas las ventas registradas quedarán en $0. Esta acción no se puede deshacer.')) return;
    if (!confirm('Confirma una vez más: se borrará TODO tu historial de ventas. ¿Continuar?')) return;

    const res = await fetch('/api/finances/all', { method: 'DELETE' });
    if (res.ok) {
        selectedHistoryDate = null;
        document.getElementById('sales-history-title').textContent = 'Ventas de Hoy';
        document.getElementById('btn-back-to-today').classList.add('hidden');
        await loadFinances();
        alert('Finanzas borradas correctamente.');
    } else {
        const data = await res.json(); alert('⚠️ ' + (data.error || 'No se pudo borrar.'));
    }
});

window.viewHistoryDay = async function(dateIso, dateLabel) {
    selectedHistoryDate = dateIso;
    document.getElementById('sales-history-title').textContent = `Ventas del ${dateLabel}`;
    document.getElementById('btn-back-to-today').classList.remove('hidden');
    document.querySelectorAll('#finance-history-list button').forEach(b => b.classList.remove('border-primary', 'ring-2', 'ring-primary/40'));
    await loadSalesTable();
};

document.getElementById('btn-back-to-today').addEventListener('click', async () => {
    selectedHistoryDate = null;
    document.getElementById('sales-history-title').textContent = 'Ventas de Hoy';
    document.getElementById('btn-back-to-today').classList.add('hidden');
    await loadSalesTable();
});

async function loadSalesTable() {
    const dateToUse = selectedHistoryDate || serverTodayIso;
    const url = dateToUse ? `/api/sales?date=${dateToUse}` : '/api/sales';

    const resSales = await fetch(url);
    const sales = await resSales.json();
    const tbody = document.getElementById('sales-history-body');
    tbody.innerHTML = '';

    if (sales.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center py-8 text-muted text-sm">No hay ventas registradas en este periodo.</td></tr>`;
        return;
    }

    // RENDIMIENTO: esta tabla puede tener miles de filas en "Histórico
    // General". Antes se reconstruía TODO lo ya puesto en cada vuelta del
    // ciclo con "tbody.innerHTML +=" (más lento mientras más ventas tenga
    // tu historial). Ahora se arma el texto completo de todas las filas
    // primero y se pinta en la tabla UNA sola vez al final.
    const rowsHtml = sales.map(s => {
        const resumen = s.items.map(it => `${it.quantity}x ${it.product_name}`).join(', ') || 'Sin detalle';
        const clienteTag = s.customer_name ? `<span class="ml-2 text-[10px] bg-sage-soft text-sage-dark px-2 py-0.5 rounded-full font-bold">🤝 ${s.customer_name}</span>` : '';
        const detalleFilas = s.items.map(it => `
            <tr>
                <td class="py-1.5 px-2">${it.product_name}</td>
                <td class="py-1.5 px-2 text-center">${it.quantity}</td>
                <td class="py-1.5 px-2 text-right tabular-nums">$${it.sale_price.toFixed(2)}</td>
                <td class="py-1.5 px-2 text-right font-semibold tabular-nums">$${it.subtotal.toFixed(2)}</td>
            </tr>`).join('');

        const profitCell = isAdmin
            ? `<td class="py-3 px-3 text-right font-bold text-sage-dark tabular-nums">$${s.profit.toFixed(2)}</td>`
            : '';
        const actionCell = isAdmin
            ? `<td class="py-3 px-3 text-center"><button onclick="event.stopPropagation(); cancelSale(${s.id})" class="text-xs bg-danger-soft text-danger hover:text-danger-dark px-3 py-1.5 rounded-lg font-bold transition-all duration-150 active:scale-95">Cancelar</button></td>`
            : '';
        const colspan = isAdmin ? 6 : 4;

        return `
            <tr class="hover:bg-paper/40 border-b border-line transition-colors duration-150 cursor-pointer" onclick="toggleSaleDetail(${s.id})" title="Click para ver el detalle de productos">
                <td class="py-3 px-3 font-mono text-muted font-bold">#TR-${s.id}</td>
                <td class="py-3 px-3 text-ink/80">${s.timestamp}</td>
                <td class="py-3 px-3 text-ink/80 text-xs max-w-xs truncate">${resumen} <span class="text-primary font-semibold">▾</span>${clienteTag}</td>
                <td class="py-3 px-3 text-right font-medium text-ink tabular-nums">$${s.total.toFixed(2)}</td>
                ${profitCell}
                ${actionCell}
            </tr>
            <tr id="detail-${s.id}" class="hidden bg-paper/30">
                <td colspan="${colspan}" class="px-8 py-3">
                    <table class="w-full text-xs">
                        <thead class="text-muted uppercase border-b border-line">
                            <tr><th class="text-left py-1 px-2">Producto</th><th class="text-center py-1 px-2">Cant.</th><th class="text-right py-1 px-2">P. Unitario</th><th class="text-right py-1 px-2">Subtotal</th></tr>
                        </thead>
                        <tbody class="divide-y divide-line">${detalleFilas}</tbody>
                    </table>
                </td>
            </tr>`;
    }).join('');
    tbody.innerHTML = rowsHtml;
}

window.toggleSaleDetail = function(saleId) {
    const row = document.getElementById(`detail-${saleId}`);
    if (row) row.classList.toggle('hidden');
};

window.cancelSale = async function(saleId) {
    if (!confirm(`¿Revertir transacción #TR-${saleId}?`)) return;
    const res = await fetch(`/api/sales/${saleId}`, { method: 'DELETE' });
    if (res.ok) { await loadFinances(); alert('Operación revocada.'); }
};

// --- CONTROLADOR INTEGRAL DEL MÓDULO DE INTELIGENCIA ARTIFICIAL ---
document.getElementById('btn-smart').addEventListener('click', async () => {
    const textEl = document.getElementById('smart-text');
    const text = textEl.value.trim();
    if(!text) return;
    
    try {
        const res = await fetch('/api/smart_inventory', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: text })
        });
        
        const data = await res.json();
        const div = document.getElementById('smart-results');
        div.classList.remove('hidden');
        
        if(data.success) {
            div.innerHTML = `<h4 class="font-display font-bold text-sage-dark text-lg mb-3">✨ IA Ejecutó con Éxito:</h4>`;
            
            if(['CATEGORY_CREATED', 'PRODUCT_ADDED', 'CATEGORY_DELETED', 'PRODUCT_DELETED', 'PRICE_UPDATED', 'COST_UPDATED'].includes(data.type)) {
                div.innerHTML += `<p class="text-ink/80 text-sm font-medium">✔️ ${data.message}</p>`;
                await loadCategories();
                await loadInventory();
            } 
            else if(data.type === 'STOCK_UPDATED') {
                data.updated.forEach(item => { 
                    const verbo = item.added >= 0 ? 'Se añadieron' : 'Se restaron';
                    div.innerHTML += `<p class="text-ink/80 text-sm mb-1">📦 <b>${item.name}</b>: ${verbo} ${Math.abs(item.added)} unidades (Stock total: ${item.new_stock}).</p>`; 
                });
                if(data.warnings && data.warnings.length) {
                    data.warnings.forEach(w => { div.innerHTML += `<p class="text-primary-dark text-sm mb-1">⚠️ ${w}</p>`; });
                }
                await loadInventory();
            }
            else if(data.type === 'STOCK_QUERY' || data.type === 'PRICE_QUERY') {
                div.innerHTML += `<p class="text-ink/80 text-sm font-medium">🔎 ${data.message}</p>`;
            }
            else if(data.type === 'HELP') {
                div.innerHTML += `<p class="text-ink/80 text-sm whitespace-pre-line">${data.message}</p>`;
            }
            else {
                div.innerHTML += `<p class="text-ink/80 text-sm font-medium">✔️ ${data.message || 'Operación realizada.'}</p>`;
            }
        } else {
            div.innerHTML = `
                <h4 class="font-display font-bold text-danger-dark text-lg mb-2">⚠️ La IA no pudo procesar la solicitud:</h4>
                <p class="text-ink/70 text-sm whitespace-pre-line">${data.message}</p>
            `;
        }
    } catch (error) {
        console.error("Error en módulo IA:", error);
        alert("Ocurrió un fallo de red al comunicar con el motor conversacional.");
    }
    
    textEl.value = '';
});

// =====================================================================
// MÁS VENDIDOS: barras simples hechas con HTML/CSS (sin librería externa
// de gráficas, para que la app siga funcionando sin internet, igual que
// el resto del programa).
// =====================================================================
async function loadTopSellers() {
    const res = await fetch('/api/analytics/top_products');
    const data = await res.json();
    const listEl = document.getElementById('topsellers-list');
    const emptyEl = document.getElementById('topsellers-empty');
    const winnerBox = document.getElementById('topsellers-winner');

    if (!data.products || data.products.length === 0) {
        listEl.innerHTML = '';
        winnerBox.classList.add('hidden');
        emptyEl.classList.remove('hidden');
        return;
    }
    emptyEl.classList.add('hidden');

    const top = data.products[0];
    winnerBox.classList.remove('hidden');
    document.getElementById('topsellers-winner-name').textContent = top.name;
    document.getElementById('topsellers-winner-detail').textContent = `${top.quantity} unidades vendidas${top.brand ? ' · ' + top.brand : ''}`;

    const maxQty = top.quantity || 1;
    listEl.innerHTML = data.products.map((p, i) => {
        const pct = Math.max(4, Math.round((p.quantity / maxQty) * 100));
        return `
            <div>
                <div class="flex justify-between items-baseline mb-1.5">
                    <span class="font-display font-bold text-ink text-sm">${i + 1}. ${escapeHtml(p.name)}</span>
                    <span class="text-xs font-bold text-primary-dark tabular-nums">${p.quantity} uds.</span>
                </div>
                <div class="w-full bg-paper rounded-full h-3 overflow-hidden">
                    <div class="h-full bg-gradient-to-r from-primary to-primary-light rounded-full transition-all duration-500" style="width: ${pct}%"></div>
                </div>
            </div>`;
    }).join('');
}

// =====================================================================
// USUARIOS (solo Dueño): crear cuentas, activar/desactivar, restablecer
// contraseñas. El servidor vuelve a validar todo esto por su cuenta
// (login_required('owner') en app.py); esto es solo la interfaz.
// =====================================================================
async function loadUsers() {
    const res = await fetch('/api/users');
    if (!res.ok) return;
    const users = await res.json();
    const tbody = document.getElementById('users-list-body');

    tbody.innerHTML = users.map(u => {
        const isOwner = u.role === 'owner';
        const statusBadge = u.active
            ? '<span class="text-[10px] font-bold bg-sage-soft text-sage-dark px-2.5 py-1 rounded-full">Activo</span>'
            : '<span class="text-[10px] font-bold bg-danger-soft text-danger px-2.5 py-1 rounded-full">Desactivado</span>';
        const actions = isOwner
            ? '<span class="text-xs text-muted italic">Cuenta del Dueño</span>'
            : `
                <button onclick="resetUserPassword(${u.id}, '${escapeHtml(u.display_name)}')" class="text-xs font-bold text-primary-dark bg-primary-soft hover:bg-primary/20 px-3 py-1.5 rounded-lg transition-colors mr-2">🔑 Restablecer contraseña</button>
                <button onclick="toggleUserActive(${u.id}, ${u.active})" class="text-xs font-bold ${u.active ? 'text-danger bg-danger-soft hover:bg-danger/20' : 'text-sage-dark bg-sage-soft hover:bg-sage/20'} px-3 py-1.5 rounded-lg transition-colors">${u.active ? 'Desactivar' : 'Reactivar'}</button>
            `;

        return `
            <tr class="hover:bg-paper/40 transition-colors duration-150">
                <td class="py-3 px-4">${escapeHtml(u.display_name)}</td>
                <td class="py-3 px-4 font-mono text-xs text-muted">${escapeHtml(u.username)}</td>
                <td class="py-3 px-4 text-xs">${isOwner ? '👑 Dueño' : 'Empleado'}</td>
                <td class="py-3 px-4">${statusBadge}</td>
                <td class="py-3 px-4 text-xs text-muted">${u.created_at}</td>
                <td class="py-3 px-4 text-center whitespace-nowrap">${actions}</td>
            </tr>`;
    }).join('');
}

function setCreateUserHint(text, kind) {
    const hint = document.getElementById('create-user-hint');
    hint.textContent = text;
    hint.classList.remove('hidden', 'text-danger', 'text-sage-dark');
    if (!text) { hint.classList.add('hidden'); return; }
    hint.classList.add(kind === 'error' ? 'text-danger' : 'text-sage-dark');
}

document.getElementById('create-user-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const display_name = document.getElementById('new-user-displayname').value.trim();
    const username = document.getElementById('new-user-username').value.trim();
    const password = document.getElementById('new-user-password').value;

    try {
        const res = await fetch('/api/users', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ display_name, username, password })
        });
        const data = await res.json();
        if (res.ok) {
            setCreateUserHint(`✔️ ${data.message}`, 'ok');
            document.getElementById('create-user-form').reset();
            await loadUsers();
        } else {
            setCreateUserHint(`⚠️ ${data.error}`, 'error');
        }
    } catch (err) {
        setCreateUserHint('⚠️ Ocurrió un error de conexión.', 'error');
    }
});

window.toggleUserActive = async function(userId, isCurrentlyActive) {
    const action = isCurrentlyActive ? 'desactivar' : 'reactivar';
    if (!confirm(`¿Seguro que quieres ${action} esta cuenta?`)) return;
    const res = await fetch(`/api/users/${userId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active: !isCurrentlyActive })
    });
    if (res.ok) await loadUsers();
    else { const data = await res.json(); alert(data.error); }
};

window.resetUserPassword = async function(userId, displayName) {
    const nueva = prompt(`Escribe la NUEVA contraseña para "${displayName}" (mínimo 8 caracteres):`);
    if (nueva === null) return;
    if (nueva.length < 8) { alert('La contraseña debe tener al menos 8 caracteres.'); return; }

    const res = await fetch(`/api/users/${userId}/reset_password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_password: nueva })
    });
    const data = await res.json();
    if (res.ok) alert('✔️ ' + data.message);
    else alert('⚠️ ' + data.error);
};

// =====================================================================
// PROVEEDORES: marca, días que viene, y lista de productos de preventa
// que se le van a pedir en su próxima visita, con su precio.
// =====================================================================
const WEEKDAYS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];

// Se pintan los botones de días la primera vez que carga la página
// (checkboxes con apariencia de "pastilla", uno por día de la semana).
(function renderSupplierDayPicker() {
    const container = document.getElementById('new-supplier-days');
    if (!container) return;
    container.innerHTML = WEEKDAYS.map(day => `
        <label class="cursor-pointer">
            <input type="checkbox" value="${day}" class="supplier-day-checkbox hidden peer">
            <span class="peer-checked:bg-primary peer-checked:text-white peer-checked:border-primary bg-white text-ink/70 border border-white/70 text-xs font-bold px-3 py-1.5 rounded-full transition-all inline-block">${day}</span>
        </label>`).join('');
})();

// El apartado de Precio en Proveedores está OCULTO por default; este
// botón permite mostrarlo/ocultarlo cuando se necesite (ver el precio
// acordado, el subtotal de cada producto y el total pendiente de pago).
let supplierPricesVisible = false;

document.getElementById('btn-toggle-supplier-prices').addEventListener('click', () => {
    supplierPricesVisible = !supplierPricesVisible;
    document.getElementById('btn-toggle-supplier-prices').textContent = supplierPricesVisible ? '🙈 Ocultar Precios' : '👁️ Mostrar Precios';
    loadSuppliers();
});

async function loadSuppliers() {
    const res = await fetch('/api/suppliers');
    const suppliers = await res.json();
    const listEl = document.getElementById('suppliers-list');
    const emptyEl = document.getElementById('suppliers-empty');

    if (!suppliers.length) {
        listEl.innerHTML = '';
        emptyEl.classList.remove('hidden');
        return;
    }
    emptyEl.classList.add('hidden');

    listEl.innerHTML = suppliers.map(s => {
        const daysHtml = s.visit_days.length
            ? s.visit_days.map(d => `<span class="text-[10px] font-bold bg-primary-soft text-primary-dark px-2.5 py-1 rounded-full">${escapeHtml(d)}</span>`).join(' ')
            : '<span class="text-xs text-muted italic">Sin días definidos</span>';

        const pendingTotal = s.items.filter(it => !it.received).reduce((sum, it) => sum + it.price * it.quantity, 0);

        const itemsHtml = s.items.map(it => `
            <tr class="${it.received ? 'opacity-50' : ''}">
                <td class="py-2 px-3">
                    <label class="flex items-center gap-2 cursor-pointer">
                        <input type="checkbox" ${it.received ? 'checked' : ''} onchange="toggleSupplierItemReceived(${s.id}, ${it.id}, this.checked)" class="rounded w-4 h-4">
                        <span class="${it.received ? 'line-through' : ''}">${escapeHtml(it.product_name)}</span>
                    </label>
                </td>
                <td class="py-2 px-3 text-center tabular-nums">${it.quantity}</td>
                ${supplierPricesVisible ? `<td class="py-2 px-3 text-right tabular-nums">$${it.price.toFixed(2)}</td>` : ''}
                ${supplierPricesVisible ? `<td class="py-2 px-3 text-right font-semibold tabular-nums">$${(it.price * it.quantity).toFixed(2)}</td>` : ''}
                <td class="py-2 px-3 text-center"><button onclick="deleteSupplierItem(${s.id}, ${it.id})" class="text-danger hover:text-danger-dark w-7 h-7 rounded-full font-bold transition-all active:scale-90">✕</button></td>
            </tr>`).join('');

        return `
        <div class="glass-panel border border-white/80 rounded-3xl p-6">
            <div class="flex items-start justify-between mb-3 gap-3">
                <div>
                    <h3 class="font-display font-black text-xl text-ink">${escapeHtml(s.brand)}</h3>
                    <div class="flex flex-wrap gap-1.5 mt-1.5">${daysHtml}</div>
                    ${s.notes ? `<p class="text-xs text-ink/60 mt-2">${escapeHtml(s.notes)}</p>` : ''}
                </div>
                <div class="flex items-center gap-3 flex-shrink-0">
                    ${supplierPricesVisible ? `
                    <div class="text-right">
                        <p class="text-[10px] text-muted font-bold uppercase">Pendiente de pedido</p>
                        <p class="font-display font-black text-lg text-primary-dark">$${pendingTotal.toFixed(2)}</p>
                    </div>` : ''}
                    <button onclick="deleteSupplier(${s.id})" class="text-danger hover:text-danger-dark text-xs font-bold px-2 py-2 transition-colors">Eliminar</button>
                </div>
            </div>

            <form onsubmit="addSupplierItem(event, ${s.id})" class="grid grid-cols-1 ${supplierPricesVisible ? 'sm:grid-cols-[1fr_auto_auto_auto]' : 'sm:grid-cols-[1fr_auto_auto]'} gap-2 mb-3">
                <input type="text" placeholder="Producto a pedir" required class="glass-input rounded-lg px-3 py-2 text-sm outline-none font-medium text-ink">
                <input type="number" min="1" value="1" placeholder="Cant." class="glass-input rounded-lg px-3 py-2 text-sm outline-none font-medium text-ink w-24">
                ${supplierPricesVisible ? `<input type="number" min="0" step="0.01" placeholder="Precio" class="glass-input rounded-lg px-3 py-2 text-sm outline-none font-medium text-ink w-28 supplier-price-input">` : ''}
                <button type="submit" class="bg-primary hover:bg-primary-dark text-white px-4 py-2 rounded-lg font-bold text-sm transition-all active:scale-95">+ Agregar</button>
            </form>

            ${s.items.length ? `
            <div class="overflow-x-auto rounded-xl border border-white/60">
                <table class="w-full text-sm bg-white/40">
                    <thead class="text-muted uppercase text-[10px] font-bold bg-white/50">
                        <tr>
                            <th class="text-left py-2 px-3">Producto</th>
                            <th class="text-center py-2 px-3">Cant.</th>
                            ${supplierPricesVisible ? '<th class="text-right py-2 px-3">Precio</th>' : ''}
                            ${supplierPricesVisible ? '<th class="text-right py-2 px-3">Subtotal</th>' : ''}
                            <th class="py-2 px-3"></th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-white/60">${itemsHtml}</tbody>
                </table>
            </div>` : '<p class="text-xs text-muted italic">Todavía no agregas productos para pedirle a este proveedor.</p>'}
        </div>`;
    }).join('');
}

document.getElementById('create-supplier-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const brand = document.getElementById('new-supplier-brand').value.trim();
    const notes = document.getElementById('new-supplier-notes').value.trim();
    const visit_days = Array.from(document.querySelectorAll('.supplier-day-checkbox:checked')).map(cb => cb.value);

    const res = await fetch('/api/suppliers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ brand, notes, visit_days })
    });
    if (res.ok) {
        document.getElementById('create-supplier-form').reset();
        document.querySelectorAll('.supplier-day-checkbox:checked').forEach(cb => cb.checked = false);
        await loadSuppliers();
    } else {
        const data = await res.json(); alert('⚠️ ' + data.error);
    }
});

window.addSupplierItem = async function(event, supplierId) {
    event.preventDefault();
    const form = event.target;
    const nameInput = form.querySelectorAll('input')[0];
    const qtyInput = form.querySelectorAll('input')[1];
    // El campo de precio solo existe en el formulario cuando los precios
    // están visibles (ver btn-toggle-supplier-prices); si está oculto, se
    // manda como 0 y se puede capturar después mostrando los precios.
    const priceInput = form.querySelector('.supplier-price-input');

    const res = await fetch(`/api/suppliers/${supplierId}/items`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            product_name: nameInput.value.trim(),
            quantity: qtyInput.value,
            price: priceInput ? priceInput.value : 0,
        })
    });
    if (res.ok) await loadSuppliers();
    else { const data = await res.json(); alert('⚠️ ' + data.error); }
};

window.toggleSupplierItemReceived = async function(supplierId, itemId, received) {
    await fetch(`/api/suppliers/${supplierId}/items/${itemId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ received })
    });
    await loadSuppliers();
};

window.deleteSupplierItem = async function(supplierId, itemId) {
    if (!confirm('¿Quitar este producto del pedido?')) return;
    await fetch(`/api/suppliers/${supplierId}/items/${itemId}`, { method: 'DELETE' });
    await loadSuppliers();
};

window.deleteSupplier = async function(supplierId) {
    if (!confirm('¿Eliminar este proveedor y todo su pedido pendiente?')) return;
    await fetch(`/api/suppliers/${supplierId}`, { method: 'DELETE' });
    await loadSuppliers();
};

// ===========================================================================
// NOTAS: pagos a proveedores, productos que hacen falta, productos
// agotados, o cualquier recordatorio general. Propio de cada cuenta.
// ===========================================================================

const NOTE_CATEGORY_META = {
    pago:    { label: '💰 Pago a Proveedor', badge: 'bg-primary-soft text-primary-dark' },
    falta:   { label: '🧾 Falta Comprar',    badge: 'bg-[#F5D9A8] text-[#7A5A15]' },
    agotado: { label: '📦 Ya No Hay',        badge: 'bg-danger-soft text-danger-dark' },
    general: { label: '📌 General',          badge: 'bg-white/70 text-ink/70' },
};

let notesFilter = 'pending'; // 'pending' | 'all' | 'done'
let localNotes = [];

async function loadNotes() {
    const res = await fetch('/api/notes');
    localNotes = await res.json();
    renderNotes();
}

function renderNotes() {
    const listEl = document.getElementById('notes-list');
    const emptyEl = document.getElementById('notes-empty');

    const filtered = localNotes.filter(n => {
        if (notesFilter === 'pending') return !n.done;
        if (notesFilter === 'done') return n.done;
        return true;
    });

    if (!filtered.length) {
        listEl.innerHTML = '';
        emptyEl.classList.remove('hidden');
        emptyEl.textContent = notesFilter === 'done'
            ? 'Todavía no marcas ninguna nota como resuelta.'
            : notesFilter === 'pending'
                ? '🎉 No tienes notas pendientes.'
                : 'No tienes notas todavía.';
        return;
    }
    emptyEl.classList.add('hidden');

    listEl.innerHTML = filtered.map(n => {
        const meta = NOTE_CATEGORY_META[n.category] || NOTE_CATEGORY_META.general;
        const amountHtml = (n.amount !== null && n.amount !== undefined)
            ? `<span class="font-display font-black text-ink tabular-nums">$${Number(n.amount).toFixed(2)}</span>`
            : '';
        return `
        <div class="glass-panel border border-white/80 rounded-2xl p-4 flex items-start gap-4 ${n.done ? 'opacity-60' : ''}">
            <label class="flex items-center pt-1 cursor-pointer">
                <input type="checkbox" ${n.done ? 'checked' : ''} onchange="toggleNoteDone(${n.id}, this.checked)" class="rounded w-5 h-5">
            </label>
            <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 flex-wrap mb-1.5">
                    <span class="text-[10px] font-bold px-2.5 py-1 rounded-full ${meta.badge}">${meta.label}</span>
                    <span class="text-[10px] text-muted font-medium">${n.created_at}</span>
                </div>
                <p class="text-sm font-medium text-ink ${n.done ? 'line-through' : ''}">${escapeHtml(n.content)}</p>
            </div>
            <div class="flex items-center gap-3 flex-shrink-0">
                ${amountHtml}
                <button onclick="deleteNote(${n.id})" class="text-danger hover:text-danger-dark w-7 h-7 rounded-full font-bold transition-all active:scale-90">✕</button>
            </div>
        </div>`;
    }).join('');
}

document.querySelectorAll('.note-filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        notesFilter = btn.getAttribute('data-filter');
        document.querySelectorAll('.note-filter-btn').forEach(b => {
            b.classList.remove('bg-ink', 'text-white');
            b.classList.add('bg-white/70', 'text-ink/70');
        });
        btn.classList.remove('bg-white/70', 'text-ink/70');
        btn.classList.add('bg-ink', 'text-white');
        renderNotes();
    });
});

document.getElementById('create-note-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const category = document.querySelector('input[name="note-category"]:checked').value;
    const content = document.getElementById('new-note-content').value.trim();
    const amountRaw = document.getElementById('new-note-amount').value;

    const res = await fetch('/api/notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            category,
            content,
            amount: amountRaw === '' ? null : amountRaw,
        })
    });
    if (res.ok) {
        document.getElementById('create-note-form').reset();
        document.querySelector('input[name="note-category"][value="pago"]').checked = true;
        await loadNotes();
    } else {
        const data = await res.json(); alert('⚠️ ' + data.error);
    }
});

window.toggleNoteDone = async function(noteId, done) {
    await fetch(`/api/notes/${noteId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ done })
    });
    await loadNotes();
};

window.deleteNote = async function(noteId) {
    if (!confirm('¿Eliminar esta nota?')) return;
    await fetch(`/api/notes/${noteId}`, { method: 'DELETE' });
    await loadNotes();
};