from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# -------------------------------------------------------------------
# ZONA HORARIA CORRECTA PARA LOS TICKETS DE VENTA
# -------------------------------------------------------------------
# Antes la hora se guardaba con datetime.utcnow(), es decir, en hora de
# Inglaterra (UTC), por eso las ventas aparecían varias horas adelantadas.
# Usamos la zona horaria de Ciudad de México (zona Centro de México:
# UTC-6, sin horario de verano desde la reforma de 2022), para que el
# tiquet siempre muestre la hora real en la que se hizo la venta.
try:
    from zoneinfo import ZoneInfo
    MEXICO_TZ = ZoneInfo("America/Mexico_City")
except Exception:
    # Si por alguna razón el sistema no tiene la base de datos de zonas
    # horarias instalada (poco común, sobre todo en Windows sin el
    # paquete 'tzdata'), usamos un huso horario fijo de UTC-6, que es
    # correcto para todo el centro de México.
    MEXICO_TZ = timezone(timedelta(hours=-6))


def mexico_now():
    """Devuelve la fecha y hora actual, correcta para México (sin el
    desfase de horas que provocaba datetime.utcnow())."""
    return datetime.now(MEXICO_TZ).replace(tzinfo=None)

# ===========================================================================
# USUARIOS / PERFILES (login real con usuario y contraseña)
# ===========================================================================
# - role='owner'    -> el Dueño (Alan). Es el ÚNICO que puede crear,
#   desactivar/reactivar o restablecer la contraseña de los demás usuarios,
#   desde el apartado "Usuarios".
# - role='employee' -> cualquier otra cuenta que el Dueño dé de alta. Cada
#   una funciona como si fuera SU PROPIO programa independiente: su propio
#   inventario, sus propios códigos de barras, sus propias ventas, sus
#   propios préstamos y sus propias finanzas. Nada se comparte ni se mezcla
#   entre cuentas distintas. La única cuenta con un permiso extra es la del
#   Dueño (gestionar usuarios); todo lo demás es igual para todos.
#
# La contraseña nunca se guarda en texto plano: se guarda un "hash"
# (una huella digital de un solo sentido) con werkzeug.security, la misma
# librería de seguridad que usa Flask. Ni abriendo el archivo .db se puede
# leer la contraseña real de nadie.
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='employee')  # 'owner' | 'employee'
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=lambda: mexico_now())
    # Protección anti fuerza bruta: si alguien falla la contraseña varias
    # veces seguidas, esta cuenta se bloquea temporalmente (ver app.py).
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    # Cada cuenta (usuario) tiene su PROPIO catálogo de secciones/categorías,
    # totalmente separado del de cualquier otra cuenta (como si cada quien
    # tuviera su propia tiendita). Por eso el nombre ya NO es único a nivel
    # global, sino único DENTRO DE CADA USUARIO (dos personas sí pueden
    # tener, cada una, una sección llamada "Bebidas", son cosas distintas).
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    products = db.relationship('Product', backref='category_rel', lazy=True)
    __table_args__ = (db.UniqueConstraint('user_id', 'name', name='uq_category_user_name'),)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # LLAVE DE NEGOCIO: el nombre comercial identifica al producto DENTRO
    # DEL CATÁLOGO DE SU DUEÑO (ya no es único en toda la base de datos,
    # porque ahora cada cuenta tiene su propio inventario independiente).
    name = db.Column(db.String(100), nullable=False)
    # El código de barras también es único solo DENTRO de cada cuenta, no
    # globalmente: dos personas distintas pueden registrar el mismo código
    # de barras cada una en su propio inventario, sin ningún conflicto.
    barcode = db.Column(db.String(50), nullable=True)
    # Marca/fabricante del producto (ej. "Coca-Cola", "Bimbo"). Es distinta
    # de la Sección/Categoría: la Sección es la forma en que TÚ organizas
    # tu tienda, la Marca es un dato del producto en sí. Se puede llenar
    # sola al escanear un código de barras nuevo.
    brand = db.Column(db.String(100), nullable=True)
    cost_price = db.Column(db.Float, nullable=False)
    sale_price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    # De quién es este producto. NULLABLE por compatibilidad con productos
    # que ya existían antes de este cambio (se les asigna dueño una sola
    # vez al arrancar, ver app.py); en productos nuevos siempre se llena.
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    __table_args__ = (
        db.UniqueConstraint('user_id', 'name', name='uq_product_user_name'),
        db.UniqueConstraint('user_id', 'barcode', name='uq_product_user_barcode'),
    )

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=mexico_now)
    total_sale = db.Column(db.Float, nullable=False)
    total_profit = db.Column(db.Float, nullable=False)
    # Si esta venta viene de liquidar un préstamo/fiado, aquí se guarda el
    # nombre del cliente que pagó, solo para mostrarlo en el historial
    # (no afecta ningún cálculo). En ventas normales de mostrador queda en NULL.
    customer_name = db.Column(db.String(100), nullable=True)
    # Quién hizo esta venta. Se deja NULLABLE (en vez de obligatorio) para
    # no romper las ventas que ya existían ANTES de agregar el sistema de
    # usuarios: esas ventas viejas se le asignan una sola vez al Dueño en
    # el arranque del servidor (ver app.py), pero la columna en sí admite
    # NULL para nunca depender de que ese dato exista en filas antiguas.
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    details = db.relationship('SaleDetail', backref='sale', lazy=True)

class SaleDetail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sale.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    sale_price = db.Column(db.Float, nullable=False)
    unit_cost = db.Column(db.Float, nullable=False)
    # Relación para poder consultar fácilmente el nombre del producto
    # vendido en cada detalle (usado en el apartado de Finanzas para
    # mostrar qué productos se vendieron en cada ticket).
    product = db.relationship('Product')


# ===========================================================================
# PRÉSTAMOS / FIADO: productos que se le dan a una persona de confianza sin
# cobrarle en ese momento. Mientras la cuenta esté abierta (sin pagar), NO
# cuenta como ingreso en Finanzas (solo se descuenta del inventario, porque
# el producto sí salió físicamente de la tienda). En cuanto se marca como
# "Pagado", se convierte en una Sale normal (sí entra a Finanzas) y el
# préstamo se elimina de esta lista.
# ===========================================================================

class Loan(db.Model):
    """Una 'cuenta' o 'fiado' abierta a nombre de una persona. Puede tener
    varios artículos agregados en distintas fechas (cada vez que la
    persona pide algo nuevo, se le suma a la MISMA cuenta)."""
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=mexico_now)
    # Quién le abrió la cuenta a este cliente. Cada usuario solo ve (y
    # puede cobrar/cancelar) los préstamos que ÉL registró. NULLABLE por
    # la misma razón que en Sale: no romper cuentas de préstamo abiertas
    # ANTES de este cambio (se le asignan al Dueño una sola vez).
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    items = db.relationship('LoanItem', backref='loan', lazy=True, cascade='all, delete-orphan')

class LoanItem(db.Model):
    """Un artículo individual dentro de una cuenta de préstamo, con su
    propia fecha (para que se pueda ver exactamente qué pidió la persona
    y cuándo, aunque todo esté agrupado en la misma cuenta)."""
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey('loan.id'), nullable=False)
    # product_id puede quedar en NULL si el producto se borra del
    # inventario más adelante; por eso se guarda también una "foto" del
    # nombre y los precios en el momento del préstamo (product_name,
    # unit_price, unit_cost), para que la cuenta y el historial nunca
    # se rompan ni pierdan información aunque el producto cambie después.
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True)
    product_name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    unit_cost = db.Column(db.Float, nullable=False)
    date = db.Column(db.DateTime, default=mexico_now)


# ===========================================================================
# PROVEEDORES: para llevar el control de qué proveedor visita la tienda,
# qué días viene, y qué productos se le van a pedir en la próxima visita
# (con el precio al que se los va a comprar). Es propio de cada cuenta,
# igual que el resto de su información (inventario, ventas, préstamos):
# el proveedor que registra un empleado no lo ve el Dueño ni otro empleado.
# ===========================================================================
class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(100), nullable=False)  # Marca / nombre del proveedor
    # Días de la semana en que visita, guardados como texto separado por
    # comas (ej. "Lunes,Jueves") para no complicar el modelo con otra tabla.
    visit_days = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=mexico_now)
    items = db.relationship('SupplierItem', backref='supplier', lazy=True, cascade='all, delete-orphan')


class SupplierItem(db.Model):
    """Un producto de preventa que se le va a pedir a este proveedor en su
    próxima visita, con el precio acordado. Es una lista de pedido, no un
    historial: se marca o se borra conforme ya se recibió el pedido."""
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    product_name = db.Column(db.String(150), nullable=False)
    price = db.Column(db.Float, nullable=False, default=0)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    received = db.Column(db.Boolean, nullable=False, default=False)


# ===========================================================================
# NOTAS: espacio libre para anotar cualquier pendiente del negocio que no
# encaja en ningún otro apartado -- por ejemplo cuánto se le pagó a un
# proveedor, qué producto ya se acabó, o qué hace falta comprar. Cada nota
# tiene una categoría (para poder identificarla rápido de un vistazo) y un
# monto opcional (útil sobre todo para las notas de tipo "Pago"). Es propia
# de cada cuenta, igual que el resto de la información (inventario, ventas,
# préstamos, proveedores): las notas de un empleado no las ve el Dueño ni
# otro empleado.
# ===========================================================================
class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # 'pago'    -> dinero que se le pagó a un proveedor u otro gasto.
    # 'falta'   -> producto nuevo que hace falta pedir/traer.
    # 'agotado' -> producto que ya no hay en existencia.
    # 'general' -> cualquier otro recordatorio.
    category = db.Column(db.String(20), nullable=False, default='general')
    content = db.Column(db.Text, nullable=False)
    amount = db.Column(db.Float, nullable=True)
    done = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=mexico_now)
    created_at = db.Column(db.DateTime, default=mexico_now)