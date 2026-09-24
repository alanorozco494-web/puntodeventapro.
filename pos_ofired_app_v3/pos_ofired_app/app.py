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
# CONFIGURACIÓN DE LA BASE DE DATOS (Neon PostgreSQL / SQLite local)
# ---------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
os.makedirs(INSTANCE_DIR, exist_ok=True)
DB_PATH = os.path.join(INSTANCE_DIR, 'pos_database.db')

app = Flask(__name__)

# Lee la variable de entorno DATABASE_URL configurada en Render (Neon PostgreSQL)
# Si no existe (en entorno local), usa SQLite.
db_url = os.environ.get('DATABASE_URL') or f'sqlite:///{DB_PATH}'
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# -----------------------------------------------------------------------
# SESIONES / INICIO DE SESIÓN
# -----------------------------------------------------------------------
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
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# -----------------------------------------------------------------------
# CUENTA DEL DUEÑO
# -----------------------------------------------------------------------
OWNER_SEED_USERNAME = 'adminalanorozco'
OWNER_SEED_PASSWORD = 'PuntoDeVentaPro'
OWNER_SEED_DISPLAY_NAME = 'Alan Orozco'

LEGACY_SEED_USERNAME = 'admin ale'
LEGACY_SEED_PASSWORD = '12345678'
LEGACY_SEED_DISPLAY_NAME = 'Admin Ale'

# -----------------------------------------------------------------------
# PROTECCIÓN CONTRA FUERZA BRUTA
# -----------------------------------------------------------------------
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
    db.create_all()

    # Migraciones específicas de SQLite local
    if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
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
        _add_column_if_missing('sale', 'user_id', 'INTEGER')
        _add_column_if_missing('loan', 'user_id', 'INTEGER')
        _add_column_if_missing('product', 'user_id', 'INTEGER')
        _add_column_if_missing('category', 'user_id', 'INTEGER')

    # -----------------------------------------------------------------
    # CREACIÓN / ACTUALIZACIÓN GARANTIZADA DE CUENTAS EN NEON Y SQLITE
    # -----------------------------------------------------------------
    owner = User.query.filter(User.username.ilike('AdminAlanOrozco')).first()
    if not owner:
        owner = User(
            username='adminalanorozco',
            display_name=OWNER_SEED_DISPLAY_NAME,
            role='owner',
            active=True,
        )
        db.session.add(owner)
    
    owner.set_password('PuntoDeVentaPro')
    owner.role = 'owner'
    owner.active = True
    owner.failed_attempts = 0
    owner.locked_until = None

    legacy_user = User.query.filter(User.username.ilike('admin ale')).first()
    if not legacy_user:
        legacy_user = User(
            username=LEGACY_SEED_USERNAME.strip().lower(),
            display_name=LEGACY_SEED_DISPLAY_NAME,
            role='employee',
            active=True,
        )
        legacy_user.set_password(LEGACY_SEED_PASSWORD)
        db.session.add(legacy_user)

    db.session.commit()

    if legacy_user:
        Sale.query.filter_by(user_id=None).update({'user_id': legacy_user.id})
        Loan.query.filter_by(user_id=None).update({'user_id': legacy_user.id})
        Product.query.filter_by(user_id=None).update({'user_id': legacy_user.id})
        Category.query.filter_by(user_id=None).update({'user_id': legacy_user.id})
        db.session.commit()


@app.route('/')
def pos_view():
    return render_template('index.html')


def login_required(role=None):
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
    ip = _client_ip()
    if _ip_is_locked(ip):
        return jsonify({'success': False, 'message': 'Demasiados intentos fallidos. Espera unos minutos e inténtalo de nuevo.'}), 429

    data = request.json or {}
    username = (data.get('username') or '').strip().lower()
    password = data.get('password') or ''

    if not username or not password:
        return jsonify({'success': False, 'message': 'Escribe tu usuario y contraseña.'}), 400

    # Búsqueda insensible a mayúsculas/minúsculas
    user = User.query.filter(User.username.ilike(username)).first()

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


if __name__ == '__main__':
    app.run(debug=False, threaded=True)