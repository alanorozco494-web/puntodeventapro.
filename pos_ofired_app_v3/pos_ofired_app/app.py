import os
import difflib
import secrets
import threading
from functools import wraps

from flask import Flask, render_template, request, jsonify, session, g
from sqlalchemy.orm import joinedload
from models import db, Product, Sale, SaleDetail, Category, Loan, LoanItem, User, Supplier, SupplierItem, Note, mexico_now
from nlp_parser import parse_smart_command, strip_accents

# ---------------------------------------------------------------------------
# CONFIGURACIÓN DE LA BASE DE DATOS
# ---------------------------------------------------------------------------
# Se usa una ruta ABSOLUTA hacia instance/pos_database.db (en lugar de una
# ruta relativa) para que el archivo de la base de datos SIEMPRE sea el
# mismo sin importar desde qué carpeta se ejecute "python app.py" o desde
# qué configuración se abra el proyecto en VSCode.
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
os.makedirs(INSTANCE_DIR, exist_ok=True)
DB_PATH = os.path.join(INSTANCE_DIR, 'pos_database.db')

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# -----------------------------------------------------------------------
# SESIONES / INICIO DE SESIÓN
# -----------------------------------------------------------------------
# 'secret_key' es necesaria para que Flask pueda firmar la cookie de
# sesión (así sabe que un usuario sigue conectado, y que nadie pudo
# fabricar esa cookie a mano). ANTES estaba escrita fija en el código
# ('pos-ofired-app-clave-de-sesion-local-2026'): eso es un problema de
# seguridad real si este programa se vende a varios negocios, porque
# TODAS las copias vendidas compartirían la misma llave, y quien la
# conociera podría fabricar una sesión válida para cualquier instalación.
#
# Ahora, en el primer arranque, se genera una llave única y aleatoria
# (imposible de adivinar) y se guarda en instance/secret.key SOLO en esa
# computadora. Cada copia vendida del programa tendrá su propia llave,
# nunca compartida con otras instalaciones ni escrita en el código.
SECRET_KEY_PATH = os.path.join(INSTANCE_DIR, 'secret.key')
if os.path.exists(SECRET_KEY_PATH):
    with open(SECRET_KEY_PATH, 'r') as f:
        app.secret_key = f.read().strip()
else:
    app.secret_key = secrets.token_hex(32)
    with open(SECRET_KEY_PATH, 'w') as f:
        f.write(app.secret_key)

from datetime import datetime, timedelta
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)
# La cookie de sesión no se puede leer desde JavaScript (HttpOnly, ya es
# el valor por defecto de Flask) y no se manda a sitios distintos a este
# (SameSite=Lax), para dificultar que otra página intente usarla.
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# -----------------------------------------------------------------------
# CUENTA DEL DUEÑO (se crea SOLO la primera vez que se enciende el
# programa, si todavía no existe ningún usuario en la base de datos). En
# cuanto exista, estos valores ya no se vuelven a usar: la contraseña
# real vive únicamente como huella digital (hash) dentro de la base de
# datos, y se recomienda cambiarla desde "Mi Cuenta" en cuanto entres.
# -----------------------------------------------------------------------
OWNER_SEED_USERNAME = 'AdminAlanOrozco'
OWNER_SEED_PASSWORD = 'PuntoDeVentaPro'
OWNER_SEED_DISPLAY_NAME = 'Alan Orozco'

# Cuenta que se queda con TODO lo que el programa ya tenía capturado antes
# de existir el sistema de usuarios (el inventario, ventas y préstamos que
# ya llevabas). Es una cuenta normal (no es el Dueño), simplemente hereda
# tu trabajo previo para que nunca se pierda.
LEGACY_SEED_USERNAME = 'admin ale'
LEGACY_SEED_PASSWORD = '12345678'
LEGACY_SEED_DISPLAY_NAME = 'Admin Ale'

# -----------------------------------------------------------------------
# PROTECCIÓN CONTRA FUERZA BRUTA (adivinar contraseñas a lo loco)
# -----------------------------------------------------------------------
# Además del bloqueo por usuario que ya vive en la base de datos (ver
# User.failed_attempts / locked_until), se lleva un control simple en
# memoria por dirección IP: si desde una misma IP fallan muchos intentos
# de login seguidos (aunque prueben usuarios distintos), esa IP se
# bloquea unos minutos. Esto frena a un atacante que intente adivinar
# usuarios Y contraseñas al mismo tiempo.
_LOGIN_MAX_ATTEMPTS = 8
_LOGIN_LOCKOUT_MINUTES = 10
_login_ip_attempts = {}
_login_ip_lock = threading.Lock()


def _client_ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr) or 'desconocida'


def _ip_is_locked(ip):
    with _login_ip_lock:
        entry = _login_ip_attempts.get(ip)
        if not entry:
            return False
        count, locked_until = entry
        if locked_until and mexico_now() < locked_until:
            return True
        if locked_until and mexico_now() >= locked_until:
            _login_ip_attempts.pop(ip, None)
        return False


def _register_failed_ip_attempt(ip):
    with _login_ip_lock:
        count, _ = _login_ip_attempts.get(ip, (0, None))
        count += 1
        locked_until = None
        if count >= _LOGIN_MAX_ATTEMPTS:
            locked_until = mexico_now() + timedelta(minutes=_LOGIN_LOCKOUT_MINUTES)
        _login_ip_attempts[ip] = (count, locked_until)


def _clear_ip_attempts(ip):
    with _login_ip_lock:
        _login_ip_attempts.pop(ip, None)


db.init_app(app)

with app.app_context():
    # -----------------------------------------------------------------
    # ¡IMPORTANTE! Ya NO se borra la base de datos al iniciar el server.
    # -----------------------------------------------------------------
    # Antes este bloque ejecutaba db.drop_all() seguido de db.create_all(),
    # lo cual BORRABA TODA LA INFORMACIÓN (productos, ventas, categorías)
    # cada vez que se reiniciaba la aplicación o se cerraba VSCode.
    #
    # db.create_all() por sí solo es seguro: únicamente crea las tablas
    # que todavía no existan (por ejemplo, las nuevas tablas de
    # Préstamos). Si el archivo .db ya existe y tiene tablas y datos, los
    # respeta exactamente como están. Así tu inventario, tus ventas y tus
    # secciones se conservan para siempre entre reinicios, apagones, o
    # cierres de VSCode.
    db.create_all()

    # -----------------------------------------------------------------
    # MIGRACIÓN AUTOMÁTICA DE COLUMNAS NUEVAS
    # -----------------------------------------------------------------
    # db.create_all() NO modifica tablas que ya existían (solo crea las
    # que faltan). Como agregamos columnas nuevas a tablas que ya tenías
    # ("brand" en producto, "customer_name" en venta), hay que añadirlas
    # a mano la primera vez que se detectan ausentes, sin tocar ni borrar
    # ningún dato que ya tuvieras guardado.
    import sqlite3

    def _add_column_if_missing(table, column, coltype):
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if cur.fetchone():
            cur.execute(f"PRAGMA table_info({table})")
            existing_cols = [row[1] for row in cur.fetchall()]
            if column not in existing_cols:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
                con.commit()
        con.close()

    _add_column_if_missing('product', 'brand', 'VARCHAR(100)')
    _add_column_if_missing('sale', 'customer_name', 'VARCHAR(100)')
    # Columnas nuevas del sistema de usuarios (login real con contraseña):
    # dicen QUIÉN hizo cada venta y QUIÉN abrió cada cuenta de préstamo, y
    # de quién es cada producto/categoría del inventario.
    _add_column_if_missing('sale', 'user_id', 'INTEGER')
    _add_column_if_missing('loan', 'user_id', 'INTEGER')
    _add_column_if_missing('product', 'user_id', 'INTEGER')
    _add_column_if_missing('category', 'user_id', 'INTEGER')

    # -----------------------------------------------------------------
    # RECONSTRUIR 'category' Y 'product' SIN LA RESTRICCIÓN VIEJA
    # -----------------------------------------------------------------
    # Antes, 'category.name' y 'product.name'/'product.barcode' eran
    # ÚNICOS EN TODA LA BASE DE DATOS (un solo inventario compartido).
    # Ahora que cada cuenta tiene su propio inventario, esa restricción
    # ya no debe ser global, sino única DENTRO DE CADA CUENTA (dos
    # personas sí pueden tener, cada una, una sección o un producto con
    # el mismo nombre). Agregar la columna user_id (arriba) no quita esa
    # restricción vieja por sí solo: SQLite la sigue aplicando porque
    # quedó grabada en la definición original de la tabla. Aquí se
    # reconstruyen ambas tablas con la restricción correcta, copiando
    # TODOS los datos exactamente como estaban (mismo id, mismo nombre,
    # mismo precio, mismo stock, todo). Se hace UNA SOLA VEZ: se marca
    # con un archivo en la carpeta instance/ para no repetirlo en cada
    # arranque.
    _schema_v2_marker = os.path.join(INSTANCE_DIR, '.schema_v2_multi_tenant')
    if not os.path.exists(_schema_v2_marker):
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='category'")
        row = cur.fetchone()

        cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='product'")
        product_sql_row = cur.fetchone()
        product_sql = product_sql_row[0] if product_sql_row else ''
        category_sql = row[0] if row else ''

        rebuild_category = 'name VARCHAR(50) NOT NULL UNIQUE' in category_sql or (
            'UNIQUE' in category_sql and 'uq_category_user_name' not in category_sql
        )
        rebuild_product = (
            'name VARCHAR(100) NOT NULL UNIQUE' in product_sql
            or 'barcode VARCHAR(50) UNIQUE' in product_sql
            or ('UNIQUE' in product_sql and 'uq_product_user_name' not in product_sql)
        )

        if rebuild_category:
            cur.execute("ALTER TABLE category RENAME TO category_old_v1")
            cur.execute("""
                CREATE TABLE category (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(50) NOT NULL,
                    user_id INTEGER,
                    CONSTRAINT uq_category_user_name UNIQUE (user_id, name)
                )
            """)
            cur.execute("INSERT INTO category (id, name, user_id) SELECT id, name, user_id FROM category_old_v1")
            cur.execute("DROP TABLE category_old_v1")

        if rebuild_product:
            cur.execute("ALTER TABLE product RENAME TO product_old_v1")
            cur.execute("""
                CREATE TABLE product (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    barcode VARCHAR(50),
                    brand VARCHAR(100),
                    cost_price FLOAT NOT NULL,
                    sale_price FLOAT NOT NULL,
                    stock INTEGER NOT NULL,
                    category_id INTEGER NOT NULL,
                    user_id INTEGER,
                    CONSTRAINT uq_product_user_name UNIQUE (user_id, name),
                    CONSTRAINT uq_product_user_barcode UNIQUE (user_id, barcode)
                )
            """)
            cur.execute("""
                INSERT INTO product (id, name, barcode, brand, cost_price, sale_price, stock, category_id, user_id)
                SELECT id, name, barcode, brand, cost_price, sale_price, stock, category_id, user_id FROM product_old_v1
            """)
            cur.execute("DROP TABLE product_old_v1")

        con.commit()
        con.close()
        with open(_schema_v2_marker, 'w') as f:
            f.write('ok')

    # -----------------------------------------------------------------
    # CREACIÓN DE CUENTAS (solo la primera vez)
    # -----------------------------------------------------------------
    # Se crean DOS cuentas la primerísima vez que se enciende el programa
    # con este cambio:
    #
    # 1) El DUEÑO (OWNER_SEED_USERNAME) -> único que puede entrar a
    #    "Usuarios" para crear más cuentas. No trae inventario propio de
    #    fábrica: empieza limpio, como cualquier cuenta nueva.
    #
    # 2) La cuenta "admin ale" (LEGACY_SEED_USERNAME) -> es la cuenta que
    #    se queda con TODO lo que ya existía en el programa ANTES de este
    #    cambio (los 971 productos, las 1,190 ventas y los 11 préstamos
    #    originales), para que ese trabajo nunca se pierda ni se mezcle
    #    con cuentas nuevas.
    if User.query.count() == 0:
        owner = User(
            username=OWNER_SEED_USERNAME.strip().lower(),
            display_name=OWNER_SEED_DISPLAY_NAME,
            role='owner',
            active=True,
        )
        owner.set_password(OWNER_SEED_PASSWORD)
        db.session.add(owner)

        legacy_user = User(
            username=LEGACY_SEED_USERNAME.strip().lower(),
            display_name=LEGACY_SEED_DISPLAY_NAME,
            role='employee',
            active=True,
        )
        legacy_user.set_password(LEGACY_SEED_PASSWORD)
        db.session.add(legacy_user)
        db.session.commit()
    else:
        owner = User.query.filter_by(role='owner').first()
        legacy_user = User.query.filter_by(username=LEGACY_SEED_USERNAME.strip().lower()).first()

    # -----------------------------------------------------------------
    # NO TOCAR HISTORIAL NI PRODUCTOS: las ventas, préstamos, productos y
    # categorías que ya existían ANTES de este cambio no tienen dueño
    # asignado todavía (user_id = NULL) porque no existía el concepto de
    # usuarios cuando se guardaron. Se les asigna la cuenta "admin ale"
    # UNA SOLA VEZ (esta consulta ya no vuelve a encontrar filas para
    # actualizar en arranques futuros), sin modificar ningún otro dato:
    # mismos productos, mismas cantidades, mismos totales, misma fecha,
    # todo exactamente igual.
    if legacy_user:
        Sale.query.filter_by(user_id=None).update({'user_id': legacy_user.id})
        Loan.query.filter_by(user_id=None).update({'user_id': legacy_user.id})
        Product.query.filter_by(user_id=None).update({'user_id': legacy_user.id})
        Category.query.filter_by(user_id=None).update({'user_id': legacy_user.id})
        db.session.commit()

    # Categorías/secciones completas del catálogo (SOLO para la cuenta
    # legacy "admin ale": son las secciones con las que ya venía
    # trabajando esa tienda desde antes; una cuenta nueva empieza sin
    # ninguna sección, y cada quien crea las suyas).
    _needed_cats = [
        'General', 'Bimbo', 'Marinela', 'Gamesa', 'Isadora',
        'Sabritas', 'Barcel', 'Coca-Cola', 'La Costeña', 'Nestlé',
        'Colgate-Palmolive', 'P&G', 'La Corona', 'Herdez',
    ]
    existing_cat_names = {c.name for c in Category.query.filter_by(user_id=legacy_user.id).all()} if legacy_user else set()
    for cat_name in _needed_cats:
        if legacy_user and cat_name not in existing_cat_names:
            db.session.add(Category(name=cat_name, user_id=legacy_user.id))
    db.session.commit()

    # NOTA: _seed_catalog_products() se llama más abajo, después de que
    # la función queda definida (Python no tiene hoisting de funciones).


def _seed_catalog_products():
    """Carga inicial del catálogo completo de la tienda, ÚNICAMENTE para
    la cuenta legacy "admin ale" (la que ya traía este catálogo desde
    antes). Las cuentas nuevas que el Dueño cree NO reciben este catálogo
    automáticamente: cada una empieza con su inventario vacío y arma el
    suyo propio desde cero.
    Idempotente: si el producto ya existe en el catálogo de esa cuenta
    (mismo nombre exacto) lo omite y no toca precio ni stock que el dueño
    haya capturado después.
    Barcodes = None (el dueño los asigna escaneando para garantizar exactitud).
    Stock = 0: el dueño captura el stock real al recibirlos."""
    legacy_user = User.query.filter_by(username=LEGACY_SEED_USERNAME.strip().lower()).first()
    if not legacy_user:
        return

    def _cat(name):
        c = Category.query.filter_by(name=name, user_id=legacy_user.id).first()
        if not c:
            c = Category(name=name, user_id=legacy_user.id)
            db.session.add(c)
            db.session.flush()
        return c.id

    # (nombre, costo, precio_venta, sección)
    catalog = [
        # ── BIMBO ────────────────────────────────────────────────────────
        ('Pan Blanco Bimbo Grande',             27.0, 34.0, 'Bimbo'),
        ('Pan Blanco Bimbo Mediano',            17.0, 22.0, 'Bimbo'),
        ('Pan Integral Bimbo Grande',           29.0, 37.0, 'Bimbo'),
        ('Pan Integral Bimbo Mediano',          18.0, 24.0, 'Bimbo'),
        ('Pan Bimbo Cero Cero',                 29.0, 37.0, 'Bimbo'),
        ('Pan Linaza Bimbo',                    29.0, 37.0, 'Bimbo'),
        ('Medias Noches Bimbo (8 piezas)',       18.0, 23.0, 'Bimbo'),
        ('Medias Noches Bimbo (12 piezas)',      25.0, 32.0, 'Bimbo'),
        ('Pan para Hamburguesa Bimbo (8 piezas)',18.0, 23.0, 'Bimbo'),
        ('Bimbollos Super Bimbo (6 piezas)',     18.0, 23.0, 'Bimbo'),
        ('Mantecadas Bimbo Vainilla (4 piezas)', 17.0, 22.0, 'Bimbo'),
        ('Mantecadas Bimbo Chocolate (4 piezas)',17.0, 22.0, 'Bimbo'),
        ('Donas Bimbo Espolvoreadas (4 piezas)', 19.0, 25.0, 'Bimbo'),
        ('Donitas Bimbo Espolvoreadas',          17.0, 22.0, 'Bimbo'),
        ('Donas Bimbo Azucaradas (4 piezas)',    19.0, 25.0, 'Bimbo'),
        ('Nito Bimbo',                           10.0, 14.0, 'Bimbo'),
        ('Bimbuñuelos Bimbo (6 piezas)',         17.0, 22.0, 'Bimbo'),
        ('Colchones Bimbo (6 piezas)',           17.0, 22.0, 'Bimbo'),
        ('Panqué Bimbo Casero',                  22.0, 28.0, 'Bimbo'),
        ('Panqué Bimbo Con Pasas',               22.0, 28.0, 'Bimbo'),
        ('Panqué Bimbo Con Nuez',                22.0, 28.0, 'Bimbo'),
        ('Rebanadas Bimbo',                       9.0, 13.0, 'Bimbo'),
        ('Conchas Bimbo Vainilla (2 piezas)',    10.0, 14.0, 'Bimbo'),
        ('Conchas Bimbo Chocolate (2 piezas)',   10.0, 14.0, 'Bimbo'),
        ('Cuernitos Bimbo (4 piezas)',           14.0, 18.0, 'Bimbo'),
        ('Roles Bimbo Con Pasas (3 piezas)',     14.0, 18.0, 'Bimbo'),
        ('Roles Bimbo Glaseados (3 piezas)',     14.0, 18.0, 'Bimbo'),
        ('Roles Bimbo Canela Familiar (6 piezas)',20.0,26.0, 'Bimbo'),
        ('Pan Tostado Bimbo Clásico',            22.0, 28.0, 'Bimbo'),
        ('Pan Tostado Bimbo Integral',           22.0, 28.0, 'Bimbo'),
        ('Pan Tostado Bimbo Doble Fibra',        22.0, 28.0, 'Bimbo'),
        ('Embozados Bimbo Chocolate',            16.0, 21.0, 'Bimbo'),
        ('Teleras Bimbo (4 piezas)',             14.0, 18.0, 'Bimbo'),
        ('Pan Molido Bimbo Clásico',             18.0, 23.0, 'Bimbo'),
        ('Pan Molido Bimbo Crujiente',           18.0, 23.0, 'Bimbo'),
        # ── MARINELA ─────────────────────────────────────────────────────
        ('Gansito Marinela',                     11.0, 15.0, 'Marinela'),
        ('Chocoroles Marinela (2 piezas)',        11.0, 15.0, 'Marinela'),
        ('Pingüinos Marinela (2 piezas)',         11.0, 15.0, 'Marinela'),
        ('Submarinos Marinela Vainilla (3 piezas)',14.0,18.0,'Marinela'),
        ('Submarinos Marinela Fresa (3 piezas)',  14.0, 18.0,'Marinela'),
        ('Submarinos Marinela Chocolate (3 piezas)',14.0,18.0,'Marinela'),
        ('Napolitano Marinela',                   11.0, 15.0,'Marinela'),
        ('Sponch Marinela',                       11.0, 15.0,'Marinela'),
        ('Barritas Marinela Fresa',               11.0, 15.0,'Marinela'),
        ('Barritas Marinela Piña',                11.0, 15.0,'Marinela'),
        ('Principe Marinela Chocolate',           14.0, 18.0,'Marinela'),
        ('Principe Marinela Blanco',              14.0, 18.0,'Marinela'),
        ('Canelitas Marinela',                    14.0, 18.0,'Marinela'),
        ('Triki-Trakes Marinela',                 14.0, 18.0,'Marinela'),
        ('Polvorones Marinela Naranja',           14.0, 18.0,'Marinela'),
        ('Parchís Marinela',                      14.0, 18.0,'Marinela'),
        ('Pipuchos Marinela',                     11.0, 15.0,'Marinela'),
        # ── GAMESA ───────────────────────────────────────────────────────
        ('Galletas Marías Gamesa (Rollo)',        13.0, 17.0, 'Gamesa'),
        ('Galletas Marías Gamesa Caja Familiar',  28.0, 36.0, 'Gamesa'),
        ('Emperador Chocolate Gamesa',            13.0, 17.0, 'Gamesa'),
        ('Emperador Combinado Gamesa',            13.0, 17.0, 'Gamesa'),
        ('Emperador Vainilla Gamesa',             13.0, 17.0, 'Gamesa'),
        ('Emperador Limón Gamesa',                13.0, 17.0, 'Gamesa'),
        ('Chokis Clásicas Gamesa',               13.0, 17.0, 'Gamesa'),
        ('Chokis Choco-Base Gamesa',             13.0, 17.0, 'Gamesa'),
        ('Chokis Brownie Gamesa',                13.0, 17.0, 'Gamesa'),
        ('Saladitas Gamesa (Paquete mediano)',    13.0, 17.0, 'Gamesa'),
        ('Saladitas Gamesa Caja Grande',         28.0, 36.0, 'Gamesa'),
        ('Crackets Gamesa',                      13.0, 17.0, 'Gamesa'),
        ('Arcoíris Gamesa',                      13.0, 17.0, 'Gamesa'),
        ('Mamut Gamesa',                         13.0, 17.0, 'Gamesa'),
        ('Mamut Gamesa Flipy',                   13.0, 17.0, 'Gamesa'),
        ('Surtido Rico Gamesa',                  13.0, 17.0, 'Gamesa'),
        ('Galletas Giro Gamesa',                 13.0, 17.0, 'Gamesa'),
        ('Galletas Hawaianas Gamesa',            13.0, 17.0, 'Gamesa'),
        ('Galletas Sugar Wafers Fresa Gamesa',   13.0, 17.0, 'Gamesa'),
        ('Galletas Sugar Wafers Chocolate Gamesa',13.0,17.0, 'Gamesa'),
        ('Galletas Animalitos Gamesa (Bolsa chica)',10.0,14.0,'Gamesa'),
        ('Galletas Animalitos Gamesa Familiar',  20.0, 26.0, 'Gamesa'),
        ('Quaker Barras de Avena con Chispas (6 piezas)',22.0,28.0,'Gamesa'),
        # ── ISADORA ──────────────────────────────────────────────────────
        ('Frijoles Refritos Bayos Isadora',      22.0, 28.0, 'Isadora'),
        ('Frijoles Refritos Negros Isadora',     22.0, 28.0, 'Isadora'),
        ('Frijoles Refritos Con Queso Isadora',  24.0, 31.0, 'Isadora'),
        ('Frijoles Refritos Con Chorizo Isadora',24.0, 31.0, 'Isadora'),
        ('Frijoles Enteros de Olla Bayos Isadora',22.0,28.0, 'Isadora'),
        ('Frijoles Enteros de Olla Negros Isadora',22.0,28.0,'Isadora'),
        ('Frijoles Refritos Peruanos Isadora',   22.0, 28.0, 'Isadora'),
        ('Frijoles Refritos Con Chicharrón Isadora',24.0,31.0,'Isadora'),
        # ── SABRITAS ─────────────────────────────────────────────────────
        ('Papas Sabritas Originales Con Sal',    11.0, 16.0, 'Sabritas'),
        ('Papas Sabritas Adobadas',              11.0, 16.0, 'Sabritas'),
        ('Papas Sabritas Crema y Especias',      11.0, 16.0, 'Sabritas'),
        ('Ruffles Queso Sabritas',               11.0, 16.0, 'Sabritas'),
        ('Ruffles Originales Sabritas',          11.0, 16.0, 'Sabritas'),
        ('Doritos Nacho',                        11.0, 16.0, 'Sabritas'),
        ('Doritos Flamin Hot',                   11.0, 16.0, 'Sabritas'),
        ('Doritos Pizzerola',                    11.0, 16.0, 'Sabritas'),
        ('Cheetos Torciditos Queso',             11.0, 16.0, 'Sabritas'),
        ('Cheetos Flamin Hot',                   11.0, 16.0, 'Sabritas'),
        ('Cheetos Puffs',                        11.0, 16.0, 'Sabritas'),
        ('Fritos Sal y Limón',                   11.0, 16.0, 'Sabritas'),
        ('Fritos Chorizo',                       11.0, 16.0, 'Sabritas'),
        ('Tostitos Originales',                  11.0, 16.0, 'Sabritas'),
        ('Tostitos Flamin Hot',                  11.0, 16.0, 'Sabritas'),
        ('Crujitos Queso y Chile',               11.0, 16.0, 'Sabritas'),
        ('Pake-Taxo Mezcla Quexo',               11.0, 16.0, 'Sabritas'),
        ('Pake-Taxo Mezcla Botanera',            11.0, 16.0, 'Sabritas'),
        ('Cacahuates Sabritas Salados',          10.0, 14.0, 'Sabritas'),
        ('Cacahuates Sabritas Enchilados',       10.0, 14.0, 'Sabritas'),
        ('Cacahuates Sabritas Japoneses',        10.0, 14.0, 'Sabritas'),
        ('Karameladas Sabritas Palomitas',       10.0, 14.0, 'Sabritas'),
        # ── BARCEL ───────────────────────────────────────────────────────
        ('Takis Fuego Barcel',                   11.0, 16.0, 'Barcel'),
        ('Takis Zombie Barcel',                  11.0, 16.0, 'Barcel'),
        ('Takis Originales Barcel',              11.0, 16.0, 'Barcel'),
        ('Chips Barcel Sal de San Felipe',       11.0, 16.0, 'Barcel'),
        ('Chips Barcel Fuego',                   11.0, 16.0, 'Barcel'),
        ('Chips Barcel Jalapeño',                11.0, 16.0, 'Barcel'),
        ('Chips Barcel Papatinas',               11.0, 16.0, 'Barcel'),
        ('Runners Barcel',                       11.0, 16.0, 'Barcel'),
        ('Kiwis Barcel',                         11.0, 16.0, 'Barcel'),
        ('Toreadas Barcel Habanero',             11.0, 16.0, 'Barcel'),
        ('Krankys Ricolino',                     10.0, 14.0, 'Barcel'),
        ('Paleta Payaso Ricolino',               10.0, 14.0, 'Barcel'),
        ('Panditas Ricolino Clásicos',           10.0, 14.0, 'Barcel'),
        ('Chocoretas Ricolino',                  10.0, 14.0, 'Barcel'),
        ('Duvalín Trisabor',                      9.0, 13.0, 'Barcel'),
        ('Bubulubu Ricolino',                     9.0, 13.0, 'Barcel'),
        # ── COCA-COLA ────────────────────────────────────────────────────
        ('Coca-Cola Original Lata 355 ml',       12.0, 17.0, 'Coca-Cola'),
        ('Coca-Cola Original Botella 600 ml',    12.0, 17.0, 'Coca-Cola'),
        ('Coca-Cola Original Botella 1.25 L',    20.0, 27.0, 'Coca-Cola'),
        ('Coca-Cola Original Botella 2.5 L',     30.0, 40.0, 'Coca-Cola'),
        ('Coca-Cola Original Botella 3 L',       36.0, 47.0, 'Coca-Cola'),
        ('Coca-Cola Sin Azúcar Botella 600 ml',  12.0, 17.0, 'Coca-Cola'),
        ('Coca-Cola Light Botella 600 ml',       12.0, 17.0, 'Coca-Cola'),
        ('Sidral Mundet Manzana 600 ml',         11.0, 16.0, 'Coca-Cola'),
        ('Sprite Limón 600 ml',                  11.0, 16.0, 'Coca-Cola'),
        ('Fanta Naranja 600 ml',                 11.0, 16.0, 'Coca-Cola'),
        ('Fresca Toronja 600 ml',                11.0, 16.0, 'Coca-Cola'),
        ('Agua Ciel 600 ml',                      8.0, 12.0, 'Coca-Cola'),
        ('Agua Ciel 1 Litro',                    11.0, 16.0, 'Coca-Cola'),
        ('Del Valle Reserva Mango 1 L',          18.0, 24.0, 'Coca-Cola'),
        ('Del Valle Reserva Durazno 1 L',        18.0, 24.0, 'Coca-Cola'),
        ('Del Valle Reserva Manzana 1 L',        18.0, 24.0, 'Coca-Cola'),
        ('Pulpy Del Valle Naranja 400 ml',       12.0, 17.0, 'Coca-Cola'),
        ('Santa Clara Leche Entera 1 L',         20.0, 26.0, 'Coca-Cola'),
        ('Santa Clara Leche Deslactosada 1 L',   22.0, 28.0, 'Coca-Cola'),
        ('Santa Clara Leche Semidescremada 1 L', 20.0, 26.0, 'Coca-Cola'),
        ('Santa Clara Chocolate 250 ml',         11.0, 15.0, 'Coca-Cola'),
        ('Santa Clara Fresa 250 ml',             11.0, 15.0, 'Coca-Cola'),
        ('Santa Clara Vainilla 250 ml',          11.0, 15.0, 'Coca-Cola'),
        ('Monster Energy Verde Clásico',         30.0, 40.0, 'Coca-Cola'),
        ('Monster Energy Ultra Blanco',          30.0, 40.0, 'Coca-Cola'),
        ('Monster Energy Mango Loco',            30.0, 40.0, 'Coca-Cola'),
        ('Predator Energy',                      20.0, 28.0, 'Coca-Cola'),
        # ── LA COSTEÑA ───────────────────────────────────────────────────
        ('Salsa Casera La Costeña 220g',         18.0, 24.0, 'La Costeña'),
        ('Salsa Verde La Costeña 220g',          18.0, 24.0, 'La Costeña'),
        ('Frijoles Refritos Bayos La Costeña 400g',16.0,22.0,'La Costeña'),
        ('Frijoles Refritos Negros La Costeña 400g',16.0,22.0,'La Costeña'),
        ('Frijoles Enteros Bayos La Costeña 560g',18.0,24.0, 'La Costeña'),
        ('Frijoles Enteros Negros La Costeña 560g',18.0,24.0,'La Costeña'),
        ('Chiles Chipotle Adobados La Costeña 220g',16.0,22.0,'La Costeña'),
        ('Chiles Jalapeños Enteros La Costeña 220g',14.0,20.0,'La Costeña'),
        ('Chiles Jalapeños Rajas La Costeña 220g',14.0,20.0,'La Costeña'),
        ('Ensalada de Verduras La Costeña 220g', 14.0, 20.0, 'La Costeña'),
        ('Puré de Tomate La Costeña 210g',       12.0, 17.0, 'La Costeña'),
        ('Vinagre Blanco La Costeña 520 ml',     14.0, 19.0, 'La Costeña'),
        # ── NESTLÉ ───────────────────────────────────────────────────────
        ('Nescafé Clásico Frasco 120g',          72.0, 92.0, 'Nestlé'),
        ('Nescafé Clásico Frasco 60g',           40.0, 52.0, 'Nestlé'),
        ('Nescafé Dolca Frasco 170g',            60.0, 78.0, 'Nestlé'),
        ('Nescafé Cappuccino Café de Olla Sobre', 8.0, 12.0, 'Nestlé'),
        ('Coffee-Mate Crema para Café Frasco',   38.0, 50.0, 'Nestlé'),
        ('Nesquik Sabor Chocolate Bolsa',        38.0, 50.0, 'Nestlé'),
        ('Leche Condensada La Lechera Lata',     28.0, 36.0, 'Nestlé'),
        ('Leche Evaporada Carnation Clavel Lata',24.0, 32.0, 'Nestlé'),
        ('Media Crema Nestlé 190g',              18.0, 24.0, 'Nestlé'),
        ('Chocolate Carlos V',                    9.0, 13.0, 'Nestlé'),
        ('Chocolate KitKat',                     14.0, 19.0, 'Nestlé'),
        # ── COLGATE-PALMOLIVE ────────────────────────────────────────────
        ('Crema Dental Colgate Triple Acción 90 ml',22.0,30.0,'Colgate-Palmolive'),
        ('Crema Dental Colgate Máxima Protección',  26.0,34.0,'Colgate-Palmolive'),
        ('Jabón Palmolive Naturals Oliva 100g',  10.0, 15.0, 'Colgate-Palmolive'),
        ('Fabuloso Lavanda 1 L',                 22.0, 30.0, 'Colgate-Palmolive'),
        ('Fabuloso Mar Fresco 1 L',              22.0, 30.0, 'Colgate-Palmolive'),
        ('Axion Lavatrastes Líquido Limón 400 ml',14.0,20.0, 'Colgate-Palmolive'),
        ('Axion Lavatrastes Crema Limón 425g',   16.0, 22.0, 'Colgate-Palmolive'),
        ('Suavitel Fresca Primavera 850 ml',     28.0, 37.0, 'Colgate-Palmolive'),
        ('Suavitel Momentos Mágicos',            28.0, 37.0, 'Colgate-Palmolive'),
        ('Shampoo Caprice Acti-Ceramidas 750 ml',38.0, 50.0, 'Colgate-Palmolive'),
        # ── P&G ──────────────────────────────────────────────────────────
        ('Ariel Detergente Polvo Regular 1 kg',  44.0, 58.0, 'P&G'),
        ('Ariel Detergente Líquido Concentrado 750 ml',40.0,52.0,'P&G'),
        ('Ace Detergente Polvo Blanco Diamante 1 kg',38.0,50.0,'P&G'),
        ('Pantene Shampoo Nutrición Profunda 400 ml',50.0,65.0,'P&G'),
        ('Head & Shoulders Limpieza Renovadora',  44.0, 58.0, 'P&G'),
        ('Gillette Prestobarba 3',               18.0, 25.0, 'P&G'),
        # ── LA CORONA ────────────────────────────────────────────────────
        ('Jabón Zote Blanco 400g',               14.0, 19.0, 'La Corona'),
        ('Jabón Zote Rosa 400g',                 14.0, 19.0, 'La Corona'),
        ('Foca Detergente Líquido 1 L',          22.0, 30.0, 'La Corona'),
        ('Foca Detergente Polvo 1 kg',           22.0, 30.0, 'La Corona'),
        ('Carisma Detergente Líquido 1 L',       22.0, 30.0, 'La Corona'),
        ('Blanca Nieves Suavizante 1 L',         18.0, 25.0, 'La Corona'),
        ('Roma Detergente Polvo 1 kg',           20.0, 28.0, 'La Corona'),
        ('Corona Jabón Líquido Traste 500 ml',   16.0, 22.0, 'La Corona'),
        # ── HERDEZ ───────────────────────────────────────────────────────
        ('Champiñones Troceados Herdez',         16.0, 22.0, 'Herdez'),
        ('Elote Dorado Herdez 220g',             14.0, 20.0, 'Herdez'),
        ('Chícharos con Zanahoria Herdez',       14.0, 20.0, 'Herdez'),
        ('Salsa Casera Herdez',                  18.0, 24.0, 'Herdez'),
        ('Salsa Verde Herdez',                   18.0, 24.0, 'Herdez'),
        ('Atún en Agua Herdez',                  20.0, 27.0, 'Herdez'),
        ('Atún en Aceite Herdez',                20.0, 27.0, 'Herdez'),
        # ── GENERAL ──────────────────────────────────────────────────────
        ('Huevo Blanco (pieza)',                   2.5,  4.0, 'General'),
        ('Azúcar Estándar (kilo)',                16.0, 22.0, 'General'),
        ('Frijol Negro a Granel (kilo)',          28.0, 38.0, 'General'),
        ('Frijol Bayo a Granel (kilo)',           26.0, 36.0, 'General'),
        ('Arroz Extra Limpio a Granel (kilo)',    24.0, 32.0, 'General'),
        ('Queso Oaxaca Fresco a Granel (kilo)',  120.0,160.0, 'General'),
        ('Queso Panela Fresco a Granel (kilo)',  100.0,135.0, 'General'),
        ('Jamón de Pierna Económico (kilo)',      80.0,110.0, 'General'),
        ('Salchicha de Pavo FUD Paquete',         26.0, 35.0, 'General'),
        ('Mantequilla Lala Con Sal Barra',        28.0, 37.0, 'General'),
        ('Yoghurt Lala Bebible Fresa',            12.0, 17.0, 'General'),
        ('Yoghurt Danone Bebible Fresa',          12.0, 17.0, 'General'),
        ('Aceite Nutrioli Puro de Soya',          44.0, 58.0, 'General'),
        ('Aceite 1-2-3 Vegetal',                  38.0, 50.0, 'General'),
        ('Atún en Agua Dolores',                  18.0, 25.0, 'General'),
        ('Atún en Aceite Dolores',                18.0, 25.0, 'General'),
        ('Mayonesa McCormick con Limón',          32.0, 42.0, 'General'),
        ('Salsa Catsup Del Monte',                22.0, 30.0, 'General'),
        ('Salsa Valentina Etiqueta Amarilla',     16.0, 22.0, 'General'),
        ('Sopa Fideo La Moderna 200g',            10.0, 14.0, 'General'),
        ('Sopa Codo La Moderna 200g',             10.0, 14.0, 'General'),
        ('Maruchan Vaso Pollo',                   11.0, 16.0, 'General'),
        ('Maruchan Vaso Camarón con Limón',       11.0, 16.0, 'General'),
        ('Jumex Único Naranja 1 L',               16.0, 22.0, 'General'),
        ('Jumex Único Verde 1 L',                 16.0, 22.0, 'General'),
        ('Jumex Néctar Mango 500 ml',             12.0, 17.0, 'General'),
        ('Tang Limón Sobre',                       4.0,  6.0, 'General'),
        ('Tang Naranja Sobre',                     4.0,  6.0, 'General'),
        ('Zuko Horchata Sobre',                    4.0,  6.0, 'General'),
        ('Sal de Mesa La Fina 1 kg',              14.0, 19.0, 'General'),
        ('Té Covent Garden 12 Flores',            16.0, 22.0, 'General'),
        ('Té Hierbabuena La Pastora',             10.0, 15.0, 'General'),
        ('Pedigree Pouch Res',                    14.0, 20.0, 'General'),
        ('Whiskas Pouch Atún',                    14.0, 20.0, 'General'),
        ('Cigarros Link Azul con Cápsula',        60.0, 80.0, 'General'),
        ('Cigarros Marlboro Rojo Clásico',        70.0, 90.0, 'General'),
        ('Encendedor Bic Clásico',                10.0, 15.0, 'General'),
        ('Sal de Uvas Picot Sobre',                6.0,  9.0, 'General'),
        ('Alka-Seltzer Caja',                     18.0, 25.0, 'General'),
        ('Alcohol Morelos 96° 1 Litro',           30.0, 40.0, 'General'),
        ('Toallas Femeninas Kotex Nocturna',      30.0, 40.0, 'General'),
        ('Papel Higiénico Regio Luxury 4 rollos', 38.0, 50.0, 'General'),
        ('Papel Higiénico Pétalo Rendimax 4 rollos',32.0,42.0,'General'),
        ('Cloralex Original 950 ml',              18.0, 25.0, 'General'),
        ('Pinol Limpiador Líquido',               18.0, 25.0, 'General'),
        ('Poett Primavera Multiusos',             18.0, 25.0, 'General'),
        ('Fibra Scotch-Brite Verde',               8.0, 12.0, 'General'),
        ('Pegamento Kola Loka Original',           9.0, 14.0, 'General'),
        ('Pilas Duracell AA (2 piezas)',           22.0, 30.0, 'General'),
        ('Vasos Desechables Reyma No. 8',          8.0, 12.0, 'General'),
        ('Servilletas Pétalo Paquete',             8.0, 12.0, 'General'),
    ]

    added = 0
    for name, cost, price, section in catalog:
        if Product.query.filter_by(name=name, user_id=legacy_user.id).first():
            continue
        cat_id = _cat(section)
        db.session.add(Product(
            name=name, barcode=None, brand=None,
            cost_price=cost, sale_price=price,
            stock=0, category_id=cat_id, user_id=legacy_user.id,
        ))
        added += 1

    if added:
        db.session.commit()


# La llamada al seed se hace aquí, DESPUÉS de que la función ya está
# definida, envuelta en un app context explícito (igual que el bloque
# de inicialización de arriba).
with app.app_context():
    _seed_catalog_products()


@app.route('/')
def pos_view():
    return render_template('index.html')


# ===========================================================================
# AUTENTICACIÓN: cada persona tiene SU PROPIO usuario y contraseña
# ===========================================================================
# - role='owner'    -> el Dueño. Único que puede entrar a "Usuarios" para
#   crear, desactivar o restablecer la contraseña de los demás. Ve los
#   montos de Finanzas.
# - role='employee' -> cualquier persona que el Dueño dé de alta. Usa el
#   POS, Inventario, Préstamos y "Más Vendidos" igual que el Dueño, pero
#   NUNCA ve los montos de Finanzas ni el historial/préstamos de otra
#   persona: cada quien ve solo lo que ÉL registró.
#
# La protección no es solo "ocultar con CSS": el decorador login_required
# de abajo bloquea las peticiones al servidor si no hay una sesión válida
# de un usuario que exista y esté activo, así que aunque alguien intente
# llamar a la API directamente sin haber iniciado sesión (o sin ser Dueño
# en las rutas que lo requieren), el servidor responde con error y no
# entrega los datos.

def login_required(role=None):
    """Decorador para proteger rutas de la API.
    - login_required()         -> exige estar logueado (cualquier perfil).
    - login_required('owner')  -> exige estar logueado como Dueño.
    Además de revisar la sesión, vuelve a consultar en la base de datos
    que ese usuario TODAVÍA exista y esté activo (por si el Dueño lo
    desactivó hace un momento): así una cuenta desactivada pierde acceso
    de inmediato, sin tener que esperar a que expire la sesión.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user_id = session.get('user_id')
            current_role = session.get('role')
            if not user_id or not current_role:
                return jsonify({'error': 'Debes iniciar sesión para continuar'}), 401

            user = User.query.get(user_id)
            if not user or not user.active:
                session.clear()
                return jsonify({'error': 'Tu cuenta ya no tiene acceso. Contacta al Dueño.'}), 401

            if role and current_role != role:
                return jsonify({'error': 'No tienes permisos suficientes para esta acción'}), 403

            g.current_user = user
            return f(*args, **kwargs)
        return wrapper
    return decorator


@app.route('/api/login', methods=['POST'])
def login():
    """Inicio de sesión único para todos los perfiles (usuario + contraseña).
    Incluye protección anti fuerza bruta en dos niveles: por cuenta (se
    bloquea ESA cuenta tras varios intentos fallidos) y por dirección IP
    (se bloquea a quien esté probando muchas combinaciones seguidas)."""
    ip = _client_ip()
    if _ip_is_locked(ip):
        return jsonify({'success': False, 'message': 'Demasiados intentos fallidos. Espera unos minutos e inténtalo de nuevo.'}), 429

    data = request.json or {}
    username = (data.get('username') or '').strip().lower()
    password = data.get('password') or ''

    if not username or not password:
        return jsonify({'success': False, 'message': 'Escribe tu usuario y contraseña.'}), 400

    user = User.query.filter_by(username=username).first()

    # Mensaje genérico en todos los casos de fallo (no decir si el
    # usuario existe o no), para no ayudarle a un atacante a adivinar qué
    # usuarios son válidos.
    generic_error = 'Usuario o contraseña incorrectos.'

    if not user or not user.active:
        _register_failed_ip_attempt(ip)
        return jsonify({'success': False, 'message': generic_error}), 401

    if user.locked_until and mexico_now() < user.locked_until:
        return jsonify({'success': False, 'message': 'Esta cuenta está bloqueada temporalmente por varios intentos fallidos. Inténtalo de nuevo en unos minutos.'}), 429

    if not user.check_password(password):
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= 5:
            user.locked_until = mexico_now() + timedelta(minutes=10)
            user.failed_attempts = 0
        db.session.commit()
        _register_failed_ip_attempt(ip)
        return jsonify({'success': False, 'message': generic_error}), 401

    # Login correcto: se limpian los contadores de intentos fallidos.
    user.failed_attempts = 0
    user.locked_until = None
    db.session.commit()
    _clear_ip_attempts(ip)

    session.permanent = True
    session['user_id'] = user.id
    session['role'] = user.role
    session['display_name'] = user.display_name
    return jsonify({'success': True, 'role': user.role, 'display_name': user.display_name})


@app.route('/api/session', methods=['GET'])
def get_session():
    """Permite al frontend saber si ya hay una sesión activa (por ejemplo,
    al recargar la página) sin tener que volver a pedir el inicio de sesión."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'role': None})
    user = User.query.get(user_id)
    if not user or not user.active:
        session.clear()
        return jsonify({'role': None})
    return jsonify({'role': user.role, 'display_name': user.display_name})


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})


@app.route('/api/me/change_password', methods=['POST'])
@login_required()
def change_my_password():
    """Cualquier usuario logueado (incluyendo el Dueño) puede cambiar su
    PROPIA contraseña, siempre que primero escriba la contraseña actual
    correcta. Así el Dueño puede (y debe) cambiar la contraseña con la
    que se creó su cuenta la primera vez, y nadie más puede cambiarle la
    contraseña a otra persona por aquí (para eso existe /api/users, que
    solo el Dueño puede usar)."""
    data = request.json or {}
    current_password = data.get('current_password') or ''
    new_password = data.get('new_password') or ''

    if not g.current_user.check_password(current_password):
        return jsonify({'error': 'Tu contraseña actual no es correcta.'}), 401
    if len(new_password) < 8:
        return jsonify({'error': 'La nueva contraseña debe tener al menos 8 caracteres.'}), 400

    g.current_user.set_password(new_password)
    db.session.commit()
    return jsonify({'message': 'Contraseña actualizada correctamente.'})


# ===========================================================================
# GESTIÓN DE USUARIOS: SOLO EL DUEÑO puede crear, desactivar/reactivar o
# restablecer la contraseña de otras personas. Nunca se permite crear
# otra cuenta con role='owner' desde aquí, para que siempre exista un
# único Dueño (el que ya se creó al encender el programa por primera
# vez).
# ===========================================================================

@app.route('/api/users', methods=['GET'])
@login_required('owner')
def list_users():
    users = User.query.order_by(User.created_at.asc()).all()
    return jsonify([{
        'id': u.id,
        'username': u.username,
        'display_name': u.display_name,
        'role': u.role,
        'active': u.active,
        'created_at': u.created_at.strftime('%d/%m/%Y') if u.created_at else '',
    } for u in users])


@app.route('/api/users', methods=['POST'])
@login_required('owner')
def create_user():
    data = request.json or {}
    username = (data.get('username') or '').strip().lower()
    password = data.get('password') or ''
    display_name = (data.get('display_name') or '').strip() or username

    if not username or len(username) < 3:
        return jsonify({'error': 'El usuario debe tener al menos 3 caracteres.'}), 400
    if len(password) < 8:
        return jsonify({'error': 'La contraseña debe tener al menos 8 caracteres.'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Ya existe un usuario con ese nombre.'}), 400

    new_user = User(username=username, display_name=display_name, role='employee', active=True)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    return jsonify({'message': f'Usuario "{display_name}" creado correctamente.'})


@app.route('/api/users/<int:user_id>', methods=['PUT'])
@login_required('owner')
def update_user(user_id):
    """Edita el nombre para mostrar y/o activa o desactiva a un usuario.
    No se permite editar al Dueño desde aquí, ni desactivarse a sí mismo
    por accidente."""
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    if user.role == 'owner':
        return jsonify({'error': 'No se puede modificar la cuenta del Dueño desde aquí.'}), 403

    data = request.json or {}
    if 'display_name' in data:
        display_name = (data.get('display_name') or '').strip()
        if display_name:
            user.display_name = display_name
    if 'active' in data:
        user.active = bool(data.get('active'))

    db.session.commit()
    return jsonify({'message': 'Usuario actualizado.'})


@app.route('/api/users/<int:user_id>/reset_password', methods=['POST'])
@login_required('owner')
def reset_user_password(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    if user.role == 'owner':
        return jsonify({'error': 'No se puede restablecer la contraseña del Dueño desde aquí.'}), 403

    data = request.json or {}
    new_password = data.get('new_password') or ''
    if len(new_password) < 8:
        return jsonify({'error': 'La contraseña debe tener al menos 8 caracteres.'}), 400

    user.set_password(new_password)
    user.failed_attempts = 0
    user.locked_until = None
    db.session.commit()
    return jsonify({'message': f'Contraseña de "{user.display_name}" restablecida.'})


# ===========================================================================
# BÚSQUEDA INTELIGENTE LOCAL (sin ninguna API): permite que tanto el
# inventario manual como la IA de comandos de texto encuentren productos
# o secciones aunque el usuario teclee con errores, sin acentos, en
# singular/plural, o solo escriba una parte del nombre.
# ===========================================================================

def find_product_exact_ci(name, user_id):
    """Coincidencia EXACTA ignorando mayúsculas/minúsculas y acentos,
    buscando ÚNICAMENTE dentro del inventario del usuario indicado.
    Se usa para detectar duplicados reales al registrar un producto."""
    target = strip_accents((name or '').strip().lower())
    if not target:
        return None
    for p in Product.query.filter_by(user_id=user_id).all():
        if strip_accents(p.name.lower()) == target:
            return p
    return None


def find_product_fuzzy(name, user_id):
    """Busca, DENTRO DEL INVENTARIO DEL USUARIO INDICADO, el producto que
    mejor coincide con el nombre dado.

    Estrategia (de más a menos estricta):
      1. Coincidencia exacta ignorando acentos/mayúsculas.
      2. Coincidencia por contención (ej. 'coca' encuentra 'Coca Cola 600ml').
      3. Coincidencia aproximada tolerante a errores de tecleo, usando
         difflib (incluido en Python estándar; NO es una API externa,
         es pura comparación matemática de similitud de texto local).

    Devuelve una tupla (producto_o_None, lista_de_sugerencias).
    """
    target = strip_accents((name or '').strip().lower())
    if not target:
        return None, []

    products = Product.query.filter_by(user_id=user_id).all()
    if not products:
        return None, []

    # 1. Exacta
    for p in products:
        if strip_accents(p.name.lower()) == target:
            return p, []

    # 2. Por contención
    contains = [p for p in products if target in strip_accents(p.name.lower())]
    if len(contains) == 1:
        return contains[0], []

    # 3. Aproximada (tolera errores de tecleo, plurales, etc.)
    names_map = {strip_accents(p.name.lower()): p for p in products}
    close = difflib.get_close_matches(target, names_map.keys(), n=3, cutoff=0.6)

    if len(contains) > 1:
        contains_map = {strip_accents(p.name.lower()): p for p in contains}
        best = difflib.get_close_matches(target, contains_map.keys(), n=1, cutoff=0.0)
        if best:
            return contains_map[best[0]], [p.name for p in contains]
        return contains[0], [p.name for p in contains]

    if len(close) == 1:
        return names_map[close[0]], []
    if len(close) > 1:
        return None, [names_map[c].name for c in close]

    return None, []


def find_category_fuzzy(name, user_id):
    """Igual que find_product_fuzzy, pero para secciones/categorías,
    buscando ÚNICAMENTE dentro de las secciones del usuario indicado."""
    target = strip_accents((name or '').strip().lower())
    if not target:
        return None

    cats = Category.query.filter_by(user_id=user_id).all()
    for c in cats:
        if strip_accents(c.name.lower()) == target:
            return c

    names_map = {strip_accents(c.name.lower()): c for c in cats}
    close = difflib.get_close_matches(target, names_map.keys(), n=1, cutoff=0.6)
    return names_map[close[0]] if close else None


def _remove_category(category, user_id):
    """Reasigna los productos de la sección eliminada a 'General' (DENTRO
    DEL MISMO USUARIO) y la borra.

    IMPORTANTE: se reasigna usando 'prod.category_rel = general_cat' (el
    objeto de la relación) y NO 'prod.category_id = general_cat.id' (el
    campo crudo). Si se asigna solo el campo crudo, SQLAlchemy no se da
    cuenta de que el producto ya no pertenece a la categoría que se está
    borrando, y al eliminarla intenta poner en NULL la columna category_id
    de esos productos (lo cual viola la restricción NOT NULL y tira un
    error). Usando la relación, SQLAlchemy sincroniza todo correctamente
    antes de borrar la sección.
    """
    general_cat = Category.query.filter_by(name='General', user_id=user_id).first()
    if not general_cat:
        general_cat = Category(name='General', user_id=user_id)
        db.session.add(general_cat)
        db.session.flush()

    for prod in list(category.products):
        prod.category_rel = general_cat

    db.session.flush()
    db.session.delete(category)
    db.session.commit()


# --- ENDPOINTS DE CATEGORÍAS/SECCIONES DINÁMICAS ---

@app.route('/api/categories', methods=['GET', 'POST'])
@login_required()
def manage_categories():
    if request.method == 'POST':
        data = request.json
        name_clean = data.get('name', '').strip()
        if Category.query.filter_by(name=name_clean, user_id=g.current_user.id).first():
            return jsonify({'error': 'Esa sección ya se encuentra registrada'}), 400
        
        new_cat = Category(name=name_clean, user_id=g.current_user.id)
        db.session.add(new_cat)
        db.session.commit()
        return jsonify({'message': 'Sección creada', 'id': new_cat.id, 'name': new_cat.name})
        
    categories = Category.query.filter_by(user_id=g.current_user.id).all()
    return jsonify([{'id': c.id, 'name': c.name} for c in categories])

@app.route('/api/categories/<int:cat_id>', methods=['DELETE'])
@login_required()
def delete_category(cat_id):
    category = Category.query.get(cat_id)
    if not category or category.user_id != g.current_user.id:
        return jsonify({'error': 'Sección no encontrada'}), 404
    
    general_cat = Category.query.filter_by(name='General', user_id=g.current_user.id).first()
    if general_cat and category.id == general_cat.id:
        return jsonify({'error': 'La sección general es un pilar del sistema y no puede eliminarse'}), 400

    _remove_category(category, g.current_user.id)
    return jsonify({'message': 'Sección removida con éxito'})

# --- ENDPOINTS DE PRODUCTOS Y VENTAS ---

@app.route('/api/product/<barcode>', methods=['GET'])
@login_required()
def get_product(barcode):
    product = Product.query.filter_by(barcode=barcode, user_id=g.current_user.id).first()
    if product:
        return jsonify({'id': product.id, 'name': product.name, 'price': product.sale_price, 'stock': product.stock})
    return jsonify({'error': 'Producto no encontrado'}), 404

@app.route('/api/product/search', methods=['GET'])
@login_required()
def search_product():
    query = request.args.get('q', '')
    product = Product.query.filter(
        Product.user_id == g.current_user.id
    ).filter((Product.barcode == query) | (Product.name.ilike(f"%{query}%"))).first()
    if product:
        return jsonify({'id': product.id, 'name': product.name, 'price': product.sale_price, 'stock': product.stock})
    return jsonify({'error': 'No se encontraron coincidencias'}), 404

# ---------------------------------------------------------------------------
# AUTOCOMPLETAR NOMBRE DE PRODUCTO A PARTIR DEL CÓDIGO DE BARRAS
# ---------------------------------------------------------------------------
# El código de barras es único por producto en el mundo real, así que al
# escanear uno NUEVO (que todavía no está en este inventario) se puede
# aprovechar para autocompletar el nombre comercial usando una base de
# datos pública y gratuita de productos por código de barras
# (Open Food Facts: https://world.openfoodfacts.org), sin necesidad de
# ninguna llave/API key.
#
# Si el código YA existe en este inventario, se avisa que es un
# duplicado en lugar de buscarlo afuera (para no pisar el nombre real
# que el negocio ya le puso al artículo).
#
# Si no hay internet o el código no aparece en la base pública, no se
# rompe nada: simplemente se le dice al usuario que no se encontró
# información y puede teclear el nombre él mismo, como hacía antes.
import json
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

_barcode_executor = ThreadPoolExecutor(max_workers=2)


# ---------------------------------------------------------------------------
# MAPA MARCA → SECCIÓN (categoría)
# ---------------------------------------------------------------------------
# Cuando Open Food Facts identifica un producto por su código de barras y
# devuelve la marca/fabricante, este diccionario convierte esa marca en el
# nombre de la Sección/Categoría que usa tu tienda. Si la marca no está en
# el mapa, la sección sugerida es "General". Si esa sección no existe aún
# en la base de datos, el frontend la crea automáticamente.
_BRAND_TO_CATEGORY = {
    'bimbo': 'Bimbo',
    'marinela': 'Marinela',
    'gamesa': 'Gamesa',
    'quaker': 'Gamesa',
    'isadora': 'Isadora',
    'sabritas': 'Sabritas',
    'frito-lay': 'Sabritas', 'fritolay': 'Sabritas',
    'doritos': 'Sabritas', 'cheetos': 'Sabritas',
    'ruffles': 'Sabritas', 'fritos': 'Sabritas', 'tostitos': 'Sabritas',
    'barcel': 'Barcel', 'ricolino': 'Barcel', 'takis': 'Barcel',
    'coca-cola': 'Coca-Cola', 'coca cola': 'Coca-Cola',
    'ciel': 'Coca-Cola', 'del valle': 'Coca-Cola',
    'santa clara': 'Coca-Cola', 'monster': 'Coca-Cola',
    'monster energy': 'Coca-Cola', 'sprite': 'Coca-Cola',
    'fanta': 'Coca-Cola', 'fresca': 'Coca-Cola',
    'sidral': 'Coca-Cola', 'sidral mundet': 'Coca-Cola', 'predator': 'Coca-Cola',
    'la costeña': 'La Costeña', 'la costena': 'La Costeña',
    'nestlé': 'Nestlé', 'nestle': 'Nestlé',
    'nescafé': 'Nestlé', 'nescafe': 'Nestlé',
    'coffee-mate': 'Nestlé', 'coffeemate': 'Nestlé',
    'la lechera': 'Nestlé', 'carnation': 'Nestlé', 'nesquik': 'Nestlé',
    'colgate': 'Colgate-Palmolive', 'palmolive': 'Colgate-Palmolive',
    'fabuloso': 'Colgate-Palmolive', 'axion': 'Colgate-Palmolive',
    'suavitel': 'Colgate-Palmolive', 'caprice': 'Colgate-Palmolive',
    'ariel': 'P&G', 'ace': 'P&G', 'pantene': 'P&G',
    'head & shoulders': 'P&G', 'head and shoulders': 'P&G', 'gillette': 'P&G',
    'zote': 'La Corona', 'foca': 'La Corona', 'carisma': 'La Corona',
    'blanca nieves': 'La Corona', 'roma': 'La Corona', 'la corona': 'La Corona',
    'herdez': 'Herdez',
}

def _brand_to_category(brand_raw: str) -> str:
    """Devuelve el nombre de la Sección que corresponde a una marca."""
    if not brand_raw:
        return 'General'
    key = strip_accents(brand_raw.strip().lower())
    return _BRAND_TO_CATEGORY.get(key, 'General')


def _fetch_openfoodfacts(barcode):
    url = f'https://world.openfoodfacts.org/api/v2/product/{barcode}.json?fields=product_name,brands'
    req = urllib.request.Request(url, headers={'User-Agent': 'POS-Ofired-App/1.0'})
    with urllib.request.urlopen(req, timeout=4) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _lookup_barcode_publicly(barcode):
    """Consulta Open Food Facts. Devuelve (nombre, marca) o (None, None)."""
    future = _barcode_executor.submit(_fetch_openfoodfacts, barcode)
    try:
        payload = future.result(timeout=4)
    except (urllib.error.URLError, ValueError, OSError, FutureTimeoutError):
        return None, None

    if payload.get('status') != 1:
        return None, None

    info = payload.get('product') or {}
    name = (info.get('product_name') or '').strip()
    brand = (info.get('brands') or '').strip().split(',')[0].strip()

    if not name:
        return None, None
    return name, (brand or None)


@app.route('/api/barcode_lookup/<barcode>', methods=['GET'])
@login_required()
def barcode_lookup(barcode):
    barcode = (barcode or '').strip()
    if not barcode:
        return jsonify({'found': False})

    existing = Product.query.filter_by(barcode=barcode, user_id=g.current_user.id).first()
    if existing:
        cat_name = existing.category_rel.name if existing.category_rel else 'General'
        return jsonify({
            'found': True,
            'duplicate': True,
            'name': existing.name,
            'category_name': cat_name,
            'category_id': existing.category_id,
        })

    suggested_name, suggested_brand = _lookup_barcode_publicly(barcode)
    if suggested_name:
        # Determinar la sección a partir de la marca.
        cat_name = _brand_to_category(suggested_brand or '')
        # Si esa sección ya existe en la BD (de ESTE usuario), incluir su
        # ID para que el frontend pueda seleccionarla directo sin
        # llamadas extra al API.
        cat = Category.query.filter(Category.name.ilike(cat_name), Category.user_id == g.current_user.id).first()
        return jsonify({
            'found': True,
            'duplicate': False,
            'name': suggested_name,
            'category_name': cat_name,
            'category_id': cat.id if cat else None,
        })

    return jsonify({'found': False, 'duplicate': False})


@app.route('/api/checkout', methods=['POST'])
@login_required()
def checkout():
    data = request.json
    cart = data.get('cart', [])
    if not cart: return jsonify({'error': 'El carrito está vacío'}), 400

    total_sale, total_cost = 0, 0
    new_sale = Sale(total_sale=0, total_profit=0, user_id=g.current_user.id)
    db.session.add(new_sale)
    db.session.flush()

    # Detalle de la venta, para construir el ticket en el frontend con
    # datos confirmados por el servidor (no solo lo que mandó el navegador).
    ticket_items = []

    for item in cart:
        product = Product.query.get(item['id'])
        if not product or product.user_id != g.current_user.id:
            db.session.rollback()
            return jsonify({'error': 'Uno de los productos no pertenece a tu inventario'}), 400
        if product.stock < item['qty']:
            db.session.rollback()
            return jsonify({'error': f'Stock insuficiente para {product.name if product else "el producto"}'}), 400

        product.stock -= item['qty']
        subtotal = round(product.sale_price * item['qty'], 2)
        total_sale += product.sale_price * item['qty']
        total_cost += product.cost_price * item['qty']

        detail = SaleDetail(sale_id=new_sale.id, product_id=product.id, quantity=item['qty'], sale_price=product.sale_price, unit_cost=product.cost_price)
        db.session.add(detail)

        ticket_items.append({
            'product_name': product.name,
            'quantity': item['qty'],
            'sale_price': product.sale_price,
            'subtotal': subtotal
        })

    new_sale.total_sale = total_sale
    new_sale.total_profit = total_sale - total_cost
    db.session.commit()

    return jsonify({
        'message': 'Venta registrada',
        'sale': {
            'id': new_sale.id,
            'timestamp': new_sale.timestamp.strftime('%d/%m/%Y %H:%M:%S'),
            'items': ticket_items,
            'total': round(total_sale, 2)
        }
    })

# --- ENDPOINTS DE INVENTARIO ---

def _parse_money(value):
    """Convierte a número el Costo/Precio capturado. Si el campo se dejó
    vacío (None, cadena vacía, o solo espacios) porque el dueño no lo
    quiso llenar al guardar, se usa 0.0 en vez de fallar."""
    if value is None:
        return 0.0
    value = str(value).strip()
    if not value:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def _parse_int(value):
    """Igual que _parse_money pero para Stock (entero)."""
    if value is None:
        return 0
    value = str(value).strip()
    if not value:
        return 0
    try:
        return int(float(value))
    except ValueError:
        return 0


@app.route('/api/inventory', methods=['GET', 'POST'])
@login_required()
def manage_inventory():
    if request.method == 'POST':
        data = request.json
        name_clean = data.get('name', '').strip()
        if not name_clean:
            return jsonify({'error': 'El nombre comercial es obligatorio'}), 400

        if Product.query.filter_by(name=name_clean, user_id=g.current_user.id).first():
            return jsonify({'error': 'Ya existe un producto registrado con ese nombre comercial'}), 400

        barcode_clean = (data.get('barcode') or '').strip() or None
        if barcode_clean and Product.query.filter_by(barcode=barcode_clean, user_id=g.current_user.id).first():
            return jsonify({'error': 'Ese código de barras ya está asignado a otro artículo'}), 400

        brand_clean = (data.get('brand') or '').strip() or None

        # Costo, Precio y Stock son OPCIONALES al dar de alta un producto:
        # si el dueño no los conoce todavía (por ejemplo, va a completar
        # esos datos después, o solo quiere reservar el nombre/código de
        # barras), se guardan en 0 en vez de exigir que se llenen para
        # poder guardar. Se pueden editar después desde "Editar".
        new_prod = Product(
            name=name_clean,
            barcode=barcode_clean,
            brand=brand_clean,
            cost_price=_parse_money(data.get('cost')),
            sale_price=_parse_money(data.get('price')),
            stock=_parse_int(data.get('stock')),
            category_id=int(data['category_id']),
            user_id=g.current_user.id,
        )
        db.session.add(new_prod)
        db.session.commit()
        return jsonify({'message': 'Producto agregado'})
        
    # RENDIMIENTO: antes, por cada producto se hacía una consulta aparte a
    # la base de datos para saber el nombre de su categoría (p.category_rel).
    # Con joinedload, todo llega en UNA sola consulta combinada (un JOIN),
    # sin importar cuántos productos tengas en el inventario.
    products = Product.query.options(joinedload(Product.category_rel)).filter_by(user_id=g.current_user.id).all()
    return jsonify([{
        'id': p.id, 'barcode': p.barcode or '', 'name': p.name, 'brand': p.brand or '',
        'cost': p.cost_price, 'price': p.sale_price, 'stock': p.stock,
        'category_id': p.category_id,
        'category_name': p.category_rel.name if p.category_rel else 'General'
    } for p in products])

@app.route('/api/inventory/<int:product_id>', methods=['PUT', 'DELETE'])
@login_required()
def update_delete_product(product_id):
    product = Product.query.get(product_id)
    if not product or product.user_id != g.current_user.id:
        return jsonify({'error': 'Producto no encontrado'}), 404

    if request.method == 'DELETE':
        db.session.delete(product)
        db.session.commit()
        return jsonify({'message': 'Producto eliminado'})

    if request.method == 'PUT':
        data = request.json
        name_clean = data.get('name', '').strip()
        if not name_clean:
            return jsonify({'error': 'El nombre comercial es obligatorio'}), 400

        existing_name = Product.query.filter_by(name=name_clean, user_id=g.current_user.id).first()
        if existing_name and existing_name.id != product_id:
            return jsonify({'error': 'Ese nombre comercial ya pertenece a otro artículo'}), 400

        barcode_clean = (data.get('barcode') or '').strip() or None
        if barcode_clean:
            existing_barcode = Product.query.filter_by(barcode=barcode_clean, user_id=g.current_user.id).first()
            if existing_barcode and existing_barcode.id != product_id:
                return jsonify({'error': 'Código asignado a otro artículo'}), 400

        product.name = name_clean
        product.barcode = barcode_clean
        product.brand = (data.get('brand') or '').strip() or None
        product.cost_price = _parse_money(data.get('cost'))
        product.sale_price = _parse_money(data.get('price'))
        product.stock = _parse_int(data.get('stock'))
        product.category_id = int(data['category_id'])
        db.session.commit()
        return jsonify({'message': 'Producto actualizado'})

# --- ENDPOINTS ADYACENTES ---

@app.route('/api/today', methods=['GET'])
@login_required()
def get_today():
    """Le dice al navegador qué fecha es 'hoy' según la hora de México
    (la misma que usa el servidor para calcular Finanzas). Así, tanto el
    perfil Administrador como el perfil Usuario pueden mostrar por
    default la tabla de 'Ventas de Hoy' sin depender de la zona horaria
    o el reloj de la computadora donde se esté viendo la página."""
    today = mexico_now().date()
    return jsonify({'date_iso': today.isoformat(), 'date': today.strftime('%d/%m/%Y')})


@app.route('/api/finances', methods=['GET'])
@login_required()
def get_finances():
    """Finanzas en 3 niveles, de las ventas de LA CUENTA QUE HIZO LA
    PETICIÓN únicamente (cada cuenta es como su propio negocio
    independiente, con sus propios números):
    - 'today': solo las ventas de HOY (se reinicia automáticamente cada
      día, porque simplemente se filtra por la fecha de hoy).
    - 'history': un resumen por cada día anterior (para poder consultar
      cómo te fue ayer, antier, etc.), del más reciente al más antiguo.
    - 'general': el acumulado de SIEMPRE, sin reiniciarse nunca (lo que
      ya tenías antes).
    Ningún dato se borra de la base de datos: 'today' y 'history' son
    solo formas distintas de mirar las mismas ventas guardadas."""
    # NOTA DE RENDIMIENTO: este endpoint (Finanzas) nunca tuvo el problema
    # de "N+1 consultas" que sí tenían Ventas/Inventario/Préstamos, porque
    # nunca tocaba s.details ni s.product: solo sumaba montos que ya traía
    # en la misma consulta. Sumar 2,000-3,000 números en Python es cosa de
    # milisegundos, así que se deja aquí tal cual como estaba en el diseño
    # original (comprobado y estable), solo pidiendo las 3 columnas que en
    # verdad se usan en vez del objeto completo, para bajar un poco más el
    # trabajo de la base de datos sin arriesgar nada.
    rows = db.session.query(Sale.timestamp, Sale.total_sale, Sale.total_profit).filter(
        Sale.user_id == g.current_user.id
    ).all()
    today = mexico_now().date()

    general_income = sum(r.total_sale for r in rows)
    general_profit = sum(r.total_profit for r in rows)

    by_day = {}
    for r in rows:
        d = (r.timestamp or mexico_now()).date()
        entry = by_day.setdefault(d, {'income': 0.0, 'profit': 0.0, 'count': 0})
        entry['income'] += r.total_sale
        entry['profit'] += r.total_profit
        entry['count'] += 1

    today_vals = by_day.get(today, {'income': 0.0, 'profit': 0.0, 'count': 0})

    history = []
    for d in sorted(by_day.keys(), reverse=True):
        if d == today:
            continue
        vals = by_day[d]
        history.append({
            'date': d.strftime('%d/%m/%Y'),
            'date_iso': d.isoformat(),
            'income': round(vals['income'], 2),
            'costs': round(vals['income'] - vals['profit'], 2),
            'profit': round(vals['profit'], 2),
            'count': vals['count']
        })

    return jsonify({
        'today': {
            'date': today.strftime('%d/%m/%Y'),
            'date_iso': today.isoformat(),
            'income': round(today_vals['income'], 2),
            'costs': round(today_vals['income'] - today_vals['profit'], 2),
            'profit': round(today_vals['profit'], 2),
        },
        'general': {
            'income': round(general_income, 2),
            'costs': round(general_income - general_profit, 2),
            'profit': round(general_profit, 2),
        },
        'history': history
    })

@app.route('/api/sales', methods=['GET'])
@login_required()
def get_sales_history():
    """Historial de ventas para el Dashboard Financiero. Incluye el
    detalle de QUÉ productos (y cuántos de cada uno) se vendieron en cada
    ticket, para poder mostrarlo en Finanzas.

    Acepta un parámetro opcional ?date=YYYY-MM-DD para mostrar solo las
    ventas de ESE día (usado para "Hoy" y para el historial por día). Si
    no se manda ninguna fecha, regresa TODAS las ventas de siempre (usado
    en la vista "General").

    Cada usuario ve ÚNICAMENTE las ventas que ÉL registró (nunca las de
    otro perfil): se filtra por user_id en el servidor, no solo en la
    pantalla. Como cada cuenta funciona como su propio negocio
    independiente, el campo 'profit' (utilidad/ganancia) se incluye
    siempre (es información de la propia cuenta, no de otra persona)."""
    date_filter = request.args.get('date')

    # RENDIMIENTO: el problema real aquí NO era el filtro de fecha, era que
    # por cada venta se hacía una consulta aparte por sus productos
    # (s.details) y otra más por cada producto vendido dentro de ella
    # (d.product) — con 2,000 ventas de 3 artículos en promedio, eso eran
    # miles de consultas separadas solo para abrir esta tabla. joinedload
    # trae los detalles y sus productos en la MISMA consulta combinada, sin
    # cambiar en nada la forma de filtrar por fecha (se deja en Python,
    # igual que como ya funcionaba, para no arriesgar nada ahí).
    query = Sale.query.options(
        joinedload(Sale.details).joinedload(SaleDetail.product)
    ).filter(Sale.user_id == g.current_user.id).order_by(Sale.timestamp.desc())

    sales = query.all()
    if date_filter:
        try:
            target_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Fecha inválida, usa el formato YYYY-MM-DD'}), 400
        sales = [s for s in sales if (s.timestamp or mexico_now()).date() == target_date]

    result = []
    for s in sales:
        items = [{
            'product_name': d.product.name if d.product else 'Producto eliminado',
            'quantity': d.quantity,
            'sale_price': d.sale_price,
            'subtotal': round(d.sale_price * d.quantity, 2)
        } for d in s.details]

        entry = {
            'id': s.id,
            'timestamp': s.timestamp.strftime('%d/%m/%Y %H:%M:%S'),
            'total': s.total_sale,
            'items': items,
            'customer_name': s.customer_name or None,
            'profit': s.total_profit,
        }

        result.append(entry)
    return jsonify(result)

@app.route('/api/sales/<int:sale_id>', methods=['DELETE'])
@login_required()
def cancel_sale(sale_id):
    sale = Sale.query.get(sale_id)
    if not sale: return jsonify({'error': 'No existe la transacción'}), 404
    if sale.user_id != g.current_user.id:
        return jsonify({'error': 'Esta venta no pertenece a tu cuenta.'}), 403
    for d in sale.details:
        p = Product.query.get(d.product_id)
        if p: p.stock += d.quantity
    SaleDetail.query.filter_by(sale_id=sale_id).delete()
    db.session.delete(sale)
    db.session.commit()
    return jsonify({'message': 'Venta revocada'})


@app.route('/api/finances/day/<date_iso>', methods=['DELETE'])
@login_required()
def delete_finances_day(date_iso):
    """Borra las FINANZAS (las ventas) de UN SOLO DÍA de la cuenta que
    hace la petición. A diferencia de 'Cancelar' una venta individual,
    aquí NO se devuelve el stock al inventario (el producto de verdad
    salió de la tienda ese día), solo se elimina el registro de la
    venta para que deje de contar en Finanzas. No se toca el catálogo
    de productos, categorías, ni ninguna otra tabla."""
    try:
        target_date = datetime.strptime(date_iso, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Fecha inválida, usa el formato YYYY-MM-DD'}), 400

    sales = Sale.query.filter(Sale.user_id == g.current_user.id).all()
    sales_to_delete = [s for s in sales if (s.timestamp or mexico_now()).date() == target_date]

    if not sales_to_delete:
        return jsonify({'message': 'No había ventas registradas ese día.', 'deleted': 0})

    for s in sales_to_delete:
        SaleDetail.query.filter_by(sale_id=s.id).delete()
        db.session.delete(s)
    db.session.commit()
    return jsonify({'message': f'Se borraron {len(sales_to_delete)} venta(s) de ese día.', 'deleted': len(sales_to_delete)})


@app.route('/api/finances/all', methods=['DELETE'])
@login_required()
def delete_finances_all():
    """Borra TODAS las finanzas (todas las ventas de siempre) de la
    cuenta que hace la petición, dejando el inventario y los productos
    completamente intactos. Es un reinicio total del historial de
    ventas y de los montos de Finanzas; no se puede deshacer."""
    sale_ids = [row.id for row in db.session.query(Sale.id).filter(Sale.user_id == g.current_user.id).all()]
    if sale_ids:
        SaleDetail.query.filter(SaleDetail.sale_id.in_(sale_ids)).delete(synchronize_session=False)
        Sale.query.filter(Sale.id.in_(sale_ids)).delete(synchronize_session=False)
        db.session.commit()
    return jsonify({'message': f'Se borraron {len(sale_ids)} venta(s). Las finanzas quedaron en $0.', 'deleted': len(sale_ids)})


# ===========================================================================
# MÁS VENDIDOS: qué productos se venden más, calculado a partir de las
# ventas que CADA usuario registró (igual que el resto de sus datos, no
# se mezcla con lo que vendieron otros perfiles). Disponible para todos
# los perfiles (Dueño y empleados), porque solo muestra cantidades de
# productos, nunca montos de dinero.
# ===========================================================================

@app.route('/api/analytics/top_products', methods=['GET'])
@login_required()
def top_products():
    rows = db.session.query(
        Product.id,
        Product.name,
        Product.brand,
        db.func.sum(SaleDetail.quantity).label('total_qty'),
        db.func.sum(SaleDetail.quantity * SaleDetail.sale_price).label('total_revenue'),
    ).join(SaleDetail, SaleDetail.product_id == Product.id
    ).join(Sale, Sale.id == SaleDetail.sale_id
    ).filter(Sale.user_id == g.current_user.id
    # El "1" es un atajo interno para cobrar montos sueltos que no
    # corresponden a ningún producto real del inventario (por ejemplo,
    # un cargo rápido de "$1 el que sea"), así que aunque se venda mucho
    # no tiene sentido mostrarlo como si fuera "el producto más vendido".
    ).filter(Product.name != '1'
    ).group_by(Product.id
    ).order_by(db.func.sum(SaleDetail.quantity).desc()
    ).limit(15).all()

    total_units_sold = sum(r.total_qty for r in rows) or 0

    return jsonify({
        'products': [{
            'id': r.id,
            'name': r.name,
            'brand': r.brand or '',
            'quantity': int(r.total_qty),
            'revenue': round(r.total_revenue, 2),
        } for r in rows],
        'total_units_sold': int(total_units_sold),
    })


# ===========================================================================
# PRÉSTAMOS / FIADO
# ===========================================================================
# Cuando alguien viene y quiere que le "fíes" un producto: se escanea o
# busca el producto y se le agrega a la cuenta de esa persona. El producto
# SÍ se descuenta del inventario de inmediato (porque físicamente se lo
# llevó), pero NO se contabiliza como ingreso en Finanzas todavía.
#
# Si la misma persona pide más cosas otro día, se le sigue agregando a la
# MISMA cuenta (se busca por nombre, ignorando mayúsculas/acentos), cada
# artículo con su propia fecha.
#
# Cuando la persona paga TODO lo que debe, se presiona "Marcar como
# Pagado": en ese momento se crea una venta normal (con la suma de todo lo
# que debía) que sí aparece en Finanzas, y la cuenta de préstamo se borra
# de esta lista (como pidió el negocio: "si paga sus deudas que sea
# borrado de préstamos").
# ===========================================================================

def _find_open_loan_by_customer(customer_name, user_id):
    """Busca una cuenta de préstamo ABIERTA para este cliente DENTRO DE
    LAS CUENTAS DEL USUARIO ACTUAL, ignorando mayúsculas y acentos (para
    que 'Juan Perez' y 'juan pérez' sean tratados como la misma persona).
    Cada usuario tiene sus propias cuentas de préstamo: si dos empleados
    distintos le fían algo a alguien llamado igual, son cuentas separadas,
    cada quien cobra/administra la suya."""
    target = strip_accents(customer_name.strip().lower())
    for loan in Loan.query.filter_by(user_id=user_id).all():
        if strip_accents(loan.customer_name.strip().lower()) == target:
            return loan
    return None


def _serialize_loan(loan):
    items = sorted(loan.items, key=lambda it: it.date or loan.created_at)
    total = round(sum(it.unit_price * it.quantity for it in items), 2)
    return {
        'id': loan.id,
        'customer_name': loan.customer_name,
        'created_at': loan.created_at.strftime('%d/%m/%Y') if loan.created_at else '',
        'total': total,
        'items': [{
            'id': it.id,
            'product_name': it.product_name,
            'quantity': it.quantity,
            'unit_price': it.unit_price,
            'subtotal': round(it.unit_price * it.quantity, 2),
            'date': it.date.strftime('%d/%m/%Y') if it.date else ''
        } for it in items]
    }


@app.route('/api/loans', methods=['GET'])
@login_required()
def get_loans():
    """Lista las cuentas de préstamo abiertas POR EL USUARIO ACTUAL
    únicamente (cada quien ve y administra solo las que él registró), de
    la más antigua a la más reciente, cada una con todos sus artículos y
    su total."""
    # RENDIMIENTO: joinedload trae todos los artículos de todas las cuentas
    # en una sola consulta combinada, en vez de una consulta aparte por
    # cada cuenta de préstamo (como hacía antes _serialize_loan al leer
    # loan.items).
    loans = Loan.query.options(joinedload(Loan.items)).filter_by(
        user_id=g.current_user.id
    ).order_by(Loan.created_at.asc()).all()
    return jsonify([_serialize_loan(l) for l in loans])


@app.route('/api/loans', methods=['POST'])
@login_required()
def add_loan_item():
    """Agrega UN artículo a la cuenta de préstamo de un cliente, dentro de
    las cuentas del usuario actual. Si ese cliente ya tiene una cuenta
    abierta CON ESTE MISMO USUARIO, se le suma a esa misma cuenta (con la
    fecha de hoy); si no, se le abre una nueva."""
    data = request.json or {}
    customer_name = (data.get('customer_name') or '').strip()
    product_id = data.get('product_id')
    try:
        quantity = int(data.get('quantity') or 1)
    except (TypeError, ValueError):
        return jsonify({'error': 'Cantidad inválida'}), 400

    if not customer_name:
        return jsonify({'error': 'El nombre del cliente es obligatorio'}), 400
    if quantity <= 0:
        return jsonify({'error': 'La cantidad debe ser mayor a 0'}), 400

    product = Product.query.get(product_id)
    if not product or product.user_id != g.current_user.id:
        return jsonify({'error': 'Producto no encontrado'}), 404
    if product.stock < quantity:
        return jsonify({'error': f'No hay suficiente stock de "{product.name}" (disponible: {product.stock})'}), 400

    loan = _find_open_loan_by_customer(customer_name, g.current_user.id)
    if not loan:
        loan = Loan(customer_name=customer_name, user_id=g.current_user.id)
        db.session.add(loan)
        db.session.flush()

    product.stock -= quantity
    item = LoanItem(
        loan_id=loan.id,
        product_id=product.id,
        product_name=product.name,
        quantity=quantity,
        unit_price=product.sale_price,
        unit_cost=product.cost_price,
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({'message': 'Préstamo registrado', 'loan': _serialize_loan(loan)})


@app.route('/api/loans/<int:loan_id>/pay', methods=['POST'])
@login_required()
def pay_loan(loan_id):
    """Liquida TODA la cuenta de un cliente: registra el total como una
    venta normal (entra a Finanzas) y borra la cuenta de Préstamos."""
    loan = Loan.query.get(loan_id)
    if not loan:
        return jsonify({'error': 'No se encontró esa cuenta de préstamo'}), 404
    if loan.user_id != g.current_user.id:
        return jsonify({'error': 'Esa cuenta de préstamo no pertenece a tu usuario.'}), 403

    items = list(loan.items)
    customer_name = loan.customer_name

    if not items:
        db.session.delete(loan)
        db.session.commit()
        return jsonify({'message': 'Cuenta eliminada (no tenía artículos)'})

    total_sale = sum(it.unit_price * it.quantity for it in items)
    total_cost = sum(it.unit_cost * it.quantity for it in items)

    new_sale = Sale(total_sale=total_sale, total_profit=total_sale - total_cost, customer_name=customer_name, user_id=g.current_user.id)
    db.session.add(new_sale)
    db.session.flush()

    for it in items:
        detail = SaleDetail(
            sale_id=new_sale.id,
            product_id=it.product_id,
            quantity=it.quantity,
            sale_price=it.unit_price,
            unit_cost=it.unit_cost,
        )
        db.session.add(detail)

    db.session.delete(loan)  # cascade: también borra sus LoanItem
    db.session.commit()
    return jsonify({
        'message': f'Pago de {customer_name} registrado en Finanzas por ${round(total_sale, 2)}',
        'sale_id': new_sale.id
    })


@app.route('/api/loans/<int:loan_id>', methods=['DELETE'])
@login_required()
def cancel_loan(loan_id):
    """Cancela una cuenta de préstamo COMPLETA sin registrar ningún pago,
    devolviendo el stock de todos sus artículos al inventario (por
    ejemplo, si se registró por error)."""
    loan = Loan.query.get(loan_id)
    if not loan:
        return jsonify({'error': 'No se encontró esa cuenta de préstamo'}), 404
    if loan.user_id != g.current_user.id:
        return jsonify({'error': 'Esa cuenta de préstamo no pertenece a tu usuario.'}), 403

    for it in loan.items:
        if it.product_id:
            p = Product.query.get(it.product_id)
            if p:
                p.stock += it.quantity

    db.session.delete(loan)
    db.session.commit()
    return jsonify({'message': 'Préstamo cancelado y stock devuelto al inventario'})


@app.route('/api/loans/<int:loan_id>/items/<int:item_id>', methods=['DELETE'])
@login_required()
def remove_loan_item(loan_id, item_id):
    """Elimina UN solo artículo de una cuenta de préstamo (por si se
    agregó algo por error), devolviendo su stock. Si era el último
    artículo de esa cuenta, la cuenta completa se elimina también."""
    item = LoanItem.query.get(item_id)
    if not item or item.loan_id != loan_id:
        return jsonify({'error': 'No se encontró ese artículo'}), 404

    parent_loan = Loan.query.get(loan_id)
    if not parent_loan or parent_loan.user_id != g.current_user.id:
        return jsonify({'error': 'Esa cuenta de préstamo no pertenece a tu usuario.'}), 403

    if item.product_id:
        p = Product.query.get(item.product_id)
        if p:
            p.stock += item.quantity

    db.session.delete(item)
    db.session.flush()

    remaining = LoanItem.query.filter_by(loan_id=loan_id).count()
    if remaining == 0:
        loan = Loan.query.get(loan_id)
        if loan:
            db.session.delete(loan)

    db.session.commit()
    return jsonify({'message': 'Artículo eliminado del préstamo'})


# ===========================================================================
# PROVEEDORES: marca, días que visita, y lista de productos de preventa
# que se le van a pedir (con su precio). Propio de cada cuenta, igual que
# el resto de la información (inventario, ventas, préstamos).
# ===========================================================================

def _serialize_supplier(s):
    return {
        'id': s.id,
        'brand': s.brand,
        'visit_days': s.visit_days.split(',') if s.visit_days else [],
        'notes': s.notes or '',
        'items': [{
            'id': it.id,
            'product_name': it.product_name,
            'price': it.price,
            'quantity': it.quantity,
            'received': it.received,
        } for it in s.items],
    }


@app.route('/api/suppliers', methods=['GET', 'POST'])
@login_required()
def manage_suppliers():
    if request.method == 'POST':
        data = request.json or {}
        brand = (data.get('brand') or '').strip()
        if not brand:
            return jsonify({'error': 'La marca/nombre del proveedor es obligatoria'}), 400

        visit_days = data.get('visit_days') or []
        if isinstance(visit_days, list):
            visit_days = ','.join(d.strip() for d in visit_days if d.strip())

        new_supplier = Supplier(
            brand=brand,
            visit_days=visit_days or None,
            notes=(data.get('notes') or '').strip() or None,
            user_id=g.current_user.id,
        )
        db.session.add(new_supplier)
        db.session.commit()
        return jsonify({'message': f'Proveedor "{brand}" agregado', 'id': new_supplier.id})

    suppliers = Supplier.query.filter_by(user_id=g.current_user.id).order_by(Supplier.created_at.desc()).all()
    return jsonify([_serialize_supplier(s) for s in suppliers])


@app.route('/api/suppliers/<int:supplier_id>', methods=['PUT', 'DELETE'])
@login_required()
def update_delete_supplier(supplier_id):
    supplier = Supplier.query.get(supplier_id)
    if not supplier or supplier.user_id != g.current_user.id:
        return jsonify({'error': 'Proveedor no encontrado'}), 404

    if request.method == 'DELETE':
        db.session.delete(supplier)
        db.session.commit()
        return jsonify({'message': 'Proveedor eliminado'})

    data = request.json or {}
    if 'brand' in data:
        brand = (data.get('brand') or '').strip()
        if brand:
            supplier.brand = brand
    if 'visit_days' in data:
        visit_days = data.get('visit_days') or []
        if isinstance(visit_days, list):
            visit_days = ','.join(d.strip() for d in visit_days if d.strip())
        supplier.visit_days = visit_days or None
    if 'notes' in data:
        supplier.notes = (data.get('notes') or '').strip() or None

    db.session.commit()
    return jsonify({'message': 'Proveedor actualizado'})


@app.route('/api/suppliers/<int:supplier_id>/items', methods=['POST'])
@login_required()
def add_supplier_item(supplier_id):
    supplier = Supplier.query.get(supplier_id)
    if not supplier or supplier.user_id != g.current_user.id:
        return jsonify({'error': 'Proveedor no encontrado'}), 404

    data = request.json or {}
    product_name = (data.get('product_name') or '').strip()
    if not product_name:
        return jsonify({'error': 'El nombre del producto es obligatorio'}), 400

    new_item = SupplierItem(
        supplier_id=supplier.id,
        product_name=product_name,
        price=_parse_money(data.get('price')),
        quantity=_parse_int(data.get('quantity')) or 1,
    )
    db.session.add(new_item)
    db.session.commit()
    return jsonify({'message': 'Producto agregado al pedido'})


@app.route('/api/suppliers/<int:supplier_id>/items/<int:item_id>', methods=['PUT', 'DELETE'])
@login_required()
def update_delete_supplier_item(supplier_id, item_id):
    supplier = Supplier.query.get(supplier_id)
    if not supplier or supplier.user_id != g.current_user.id:
        return jsonify({'error': 'Proveedor no encontrado'}), 404

    item = SupplierItem.query.get(item_id)
    if not item or item.supplier_id != supplier_id:
        return jsonify({'error': 'Producto no encontrado en ese proveedor'}), 404

    if request.method == 'DELETE':
        db.session.delete(item)
        db.session.commit()
        return jsonify({'message': 'Producto quitado del pedido'})

    data = request.json or {}
    if 'received' in data:
        item.received = bool(data.get('received'))
    if 'price' in data:
        item.price = _parse_money(data.get('price'))
    if 'quantity' in data:
        item.quantity = _parse_int(data.get('quantity')) or 1
    if 'product_name' in data:
        name = (data.get('product_name') or '').strip()
        if name:
            item.product_name = name

    db.session.commit()
    return jsonify({'message': 'Producto actualizado'})


NOTE_CATEGORIES = {'pago', 'falta', 'agotado', 'general'}


def _serialize_note(n):
    return {
        'id': n.id,
        'category': n.category,
        'content': n.content,
        'amount': n.amount,
        'done': n.done,
        'created_at': n.created_at.strftime('%d/%m/%Y %H:%M') if n.created_at else '',
    }


@app.route('/api/notes', methods=['GET', 'POST'])
@login_required()
def manage_notes():
    """Notas libres de la cuenta (propias de cada quien, igual que el
    resto de la información): pagos a proveedores, productos que hacen
    falta, productos agotados, o cualquier recordatorio general."""
    if request.method == 'POST':
        data = request.json or {}
        content = (data.get('content') or '').strip()
        if not content:
            return jsonify({'error': 'Escribe algo en la nota.'}), 400

        category = (data.get('category') or 'general').strip().lower()
        if category not in NOTE_CATEGORIES:
            category = 'general'

        amount_raw = data.get('amount')
        amount = _parse_money(amount_raw) if amount_raw not in (None, '') else None

        new_note = Note(
            user_id=g.current_user.id,
            category=category,
            content=content,
            amount=amount,
        )
        db.session.add(new_note)
        db.session.commit()
        return jsonify({'message': 'Nota guardada', 'id': new_note.id})

    # Pendientes primero (más recientes arriba), resueltas al final.
    notes = Note.query.filter_by(user_id=g.current_user.id).order_by(
        Note.done.asc(), Note.created_at.desc()
    ).all()
    return jsonify([_serialize_note(n) for n in notes])


@app.route('/api/notes/<int:note_id>', methods=['PUT', 'DELETE'])
@login_required()
def update_delete_note(note_id):
    note = Note.query.get(note_id)
    if not note or note.user_id != g.current_user.id:
        return jsonify({'error': 'Nota no encontrada'}), 404

    if request.method == 'DELETE':
        db.session.delete(note)
        db.session.commit()
        return jsonify({'message': 'Nota eliminada'})

    data = request.json or {}
    if 'done' in data:
        note.done = bool(data.get('done'))
    if 'content' in data:
        content = (data.get('content') or '').strip()
        if content:
            note.content = content
    if 'category' in data:
        category = (data.get('category') or '').strip().lower()
        if category in NOTE_CATEGORIES:
            note.category = category
    if 'amount' in data:
        amount_raw = data.get('amount')
        note.amount = _parse_money(amount_raw) if amount_raw not in (None, '') else None

    db.session.commit()
    return jsonify({'message': 'Nota actualizada'})


# --- ENRUTADOR DE INTELIGENCIA ARTIFICIAL (100% local, sin ninguna API) ---
@app.route('/api/smart_inventory', methods=['POST'])
@login_required()
def smart_inventory():
    data = request.json
    command = data.get('command', '')
    parsed = parse_smart_command(command)
    
    action = parsed.get('action')
    payload = parsed.get('data')

    # -------------------------------------------------------------
    # AYUDA
    # -------------------------------------------------------------
    if action == 'HELP':
        help_text = (
            "Puedo entender comandos en lenguaje natural. Aquí tienes ejemplos:\n\n"
            "📁 Secciones:\n"
            "  • \"crear seccion Sabritas\"\n"
            "  • \"eliminar seccion Sabritas\"\n\n"
            "📦 Productos:\n"
            "  • \"agregar producto Cheetos costo 10 precio 15 stock 20 seccion Sabritas\"\n"
            "  • \"eliminar producto Cheetos\"\n\n"
            "🔄 Existencias:\n"
            "  • \"+10 Cheetos\"  o  \"surtir 10 Cheetos\"\n"
            "  • \"-3 Cheetos\"  o  \"quitar 3 Cheetos\"\n"
            "  • \"+5 cocas, +10 sabritas, -2 chocolates\"\n\n"
            "💲 Precios:\n"
            "  • \"cambiar precio de Cheetos a 18\"\n"
            "  • \"cambiar costo de Cheetos a 11\"\n\n"
            "🔎 Consultas (no modifican nada):\n"
            "  • \"cuanto stock tiene Cheetos\"\n"
            "  • \"cual es el precio de Cheetos\""
        )
        return jsonify({'success': True, 'type': 'HELP', 'message': help_text})

    # -------------------------------------------------------------
    # CREAR SECCIÓN
    # -------------------------------------------------------------
    if action == 'CREATE_CATEGORY':
        name = payload['name']
        if find_category_fuzzy(name, g.current_user.id):
            return jsonify({'success': False, 'message': f'La sección "{name}" ya existe (o una muy similar) en el sistema.'})
        
        new_cat = Category(name=name, user_id=g.current_user.id)
        db.session.add(new_cat)
        db.session.commit()
        return jsonify({
            'success': True, 
            'type': 'CATEGORY_CREATED', 
            'message': f'Sección "{name}" dada de alta correctamente mediante comando de texto.'
        })

    # -------------------------------------------------------------
    # ELIMINAR SECCIÓN
    # -------------------------------------------------------------
    elif action == 'DELETE_CATEGORY':
        name = payload.get('name', '')
        category = find_category_fuzzy(name, g.current_user.id)
        if not category:
            return jsonify({'success': False, 'message': f'No encontré ninguna sección parecida a "{name}".'})

        general_cat = Category.query.filter_by(name='General', user_id=g.current_user.id).first()
        if general_cat and category.id == general_cat.id:
            return jsonify({'success': False, 'message': 'La sección "General" es un pilar del sistema y no puede eliminarse.'})

        deleted_name = category.name
        _remove_category(category, g.current_user.id)
        return jsonify({
            'success': True,
            'type': 'CATEGORY_DELETED',
            'message': f'Sección "{deleted_name}" eliminada; sus productos se reasignaron a "General".'
        })

    # -------------------------------------------------------------
    # AGREGAR PRODUCTO
    # -------------------------------------------------------------
    elif action == 'ADD_PRODUCT':
        if not payload['name']:
            return jsonify({'success': False, 'message': 'Error de sintaxis: Se requiere al menos el Nombre Comercial para el alta.'})

        existing = find_product_exact_ci(payload['name'], g.current_user.id)
        if existing:
            return jsonify({'success': False, 'message': f'Ya existe un producto registrado con el nombre "{existing.name}".'})

        barcode = payload.get('barcode') or None
        if barcode and Product.query.filter_by(barcode=barcode, user_id=g.current_user.id).first():
            return jsonify({'success': False, 'message': f'El código de barras [{barcode}] ya pertenece a otro artículo.'})

        # Búsqueda tolerante a acentos: si el usuario escribió "tia rosa"
        # y ya existe la sección "Tía Rosa", se reutiliza en vez de crear
        # una sección duplicada sin el acento.
        cat = find_category_fuzzy(payload['category_name'], g.current_user.id)
        if not cat:
            cat = Category(name=payload['category_name'], user_id=g.current_user.id)
            db.session.add(cat)
            db.session.flush()
            
        new_prod = Product(
            name=payload['name'],
            barcode=barcode,
            cost_price=payload['cost'],
            sale_price=payload['price'],
            stock=payload['stock'],
            category_id=cat.id,
            user_id=g.current_user.id,
        )
        db.session.add(new_prod)
        db.session.commit()
        return jsonify({
            'success': True,
            'type': 'PRODUCT_ADDED',
            'message': f'Producto nuevo "{payload["name"]}" guardado con éxito bajo la sección "{cat.name}".'
        })

    # -------------------------------------------------------------
    # ELIMINAR PRODUCTO
    # -------------------------------------------------------------
    elif action == 'DELETE_PRODUCT':
        name = payload.get('name', '')
        product, suggestions = find_product_fuzzy(name, g.current_user.id)
        if not product:
            msg = f'No encontré ningún producto parecido a "{name}".'
            if suggestions:
                msg += f' ¿Quisiste decir: {", ".join(suggestions)}?'
            return jsonify({'success': False, 'message': msg})

        deleted_name = product.name
        db.session.delete(product)
        db.session.commit()
        return jsonify({
            'success': True,
            'type': 'PRODUCT_DELETED',
            'message': f'Producto "{deleted_name}" eliminado del inventario mediante comando de texto.'
        })

    # -------------------------------------------------------------
    # CAMBIAR PRECIO / COSTO
    # -------------------------------------------------------------
    elif action in ('UPDATE_PRICE', 'UPDATE_COST'):
        name = payload.get('name', '')
        value = payload.get('value')
        product, suggestions = find_product_fuzzy(name, g.current_user.id)
        if not product:
            msg = f'No encontré ningún producto parecido a "{name}".'
            if suggestions:
                msg += f' ¿Quisiste decir: {", ".join(suggestions)}?'
            return jsonify({'success': False, 'message': msg})

        if action == 'UPDATE_PRICE':
            old_value = product.sale_price
            product.sale_price = value
            db.session.commit()
            return jsonify({
                'success': True, 'type': 'PRICE_UPDATED',
                'message': f'Precio de venta de "{product.name}" actualizado de ${old_value:.2f} a ${value:.2f}.'
            })
        else:
            old_value = product.cost_price
            product.cost_price = value
            db.session.commit()
            return jsonify({
                'success': True, 'type': 'COST_UPDATED',
                'message': f'Costo de "{product.name}" actualizado de ${old_value:.2f} a ${value:.2f}.'
            })

    # -------------------------------------------------------------
    # CONSULTAS DE SOLO LECTURA (no modifican nada)
    # -------------------------------------------------------------
    elif action in ('QUERY_STOCK', 'QUERY_PRICE'):
        name = payload.get('name', '')
        product, suggestions = find_product_fuzzy(name, g.current_user.id)
        if not product:
            msg = f'No encontré ningún producto parecido a "{name}".'
            if suggestions:
                msg += f' ¿Quisiste decir: {", ".join(suggestions)}?'
            return jsonify({'success': False, 'message': msg})

        if action == 'QUERY_STOCK':
            return jsonify({
                'success': True, 'type': 'STOCK_QUERY',
                'message': f'"{product.name}" tiene actualmente {product.stock} unidades en stock.'
            })
        else:
            return jsonify({
                'success': True, 'type': 'PRICE_QUERY',
                'message': f'"{product.name}" tiene un precio de venta de ${product.sale_price:.2f} (costo: ${product.cost_price:.2f}).'
            })

    # -------------------------------------------------------------
    # SUMAR / RESTAR EXISTENCIAS (uno o varios productos a la vez)
    # -------------------------------------------------------------
    elif action == 'UPDATE_STOCK':
        updated_items = []
        warnings = []

        for item in payload:
            product, suggestions = find_product_fuzzy(item['name'], g.current_user.id)
            if not product:
                if suggestions:
                    warnings.append(f'No identifiqué "{item["name"]}". ¿Quisiste decir: {", ".join(suggestions)}?')
                else:
                    warnings.append(f'No encontré ningún producto parecido a "{item["name"]}".')
                continue

            new_stock = product.stock + item['qty']
            clamped = new_stock < 0
            if clamped:
                new_stock = 0
            product.stock = new_stock

            updated_items.append({'name': product.name, 'added': item['qty'], 'new_stock': new_stock})
            if clamped:
                warnings.append(f'"{product.name}" no tenía suficiente stock disponible; se ajustó a 0 en lugar de quedar en negativo.')

        if not updated_items:
            msg = 'No se pudo actualizar ningún producto.'
            if warnings:
                msg += '\n' + '\n'.join(warnings)
            return jsonify({'success': False, 'message': msg})

        db.session.commit()
        return jsonify({
            'success': True,
            'type': 'STOCK_UPDATED',
            'updated': updated_items,
            'warnings': warnings
        })

    # -------------------------------------------------------------
    # COMANDO NO RECONOCIDO
    # -------------------------------------------------------------
    return jsonify({
        'success': False,
        'message': (
            'No reconocí ese comando. Escribe "ayuda" para ver todos los comandos '
            'disponibles, o intenta algo como:\n'
            '- "crear seccion Sabritas"\n'
            '- "agregar producto Cheetos costo 10 precio 15 stock 20 seccion Sabritas"\n'
            '- "+10 Cheetos"'
        )
    })

if __name__ == '__main__':
    # RENDIMIENTO: "debug=True" deja prendido el vigilante de archivos y el
    # depurador de Flask, que consumen memoria/CPU de fondo sin ningún
    # beneficio para el uso normal del día a día (solo sirve mientras se
    # está programando). Se apaga para que el servidor use menos recursos.
    # Si vuelves a necesitar recarga automática mientras editas código,
    # cambia esta línea de nuevo a debug=True.
    app.run(debug=False, threaded=True)
