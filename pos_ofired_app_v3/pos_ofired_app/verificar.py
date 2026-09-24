from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import User
from werkzeug.security import generate_password_hash, check_password_hash

NEON_URL = "postgresql://neondb_owner:npg_fCbguGmOcK21@ep-autumn-dawn-b4sjcqsf-pooler.c-6.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

engine = create_engine(NEON_URL)
Session = sessionmaker(bind=engine)
session = Session()

print("\n=== 1. USUARIOS ACTUALES EN NEON ===")
users = session.query(User).all()
if not users:
    print("⚠️ No hay usuarios registrados en Neon.")
else:
    for u in users:
        print(f"-> ID: {u.id} | Username: '{u.username}' | Role: {getattr(u, 'role', 'N/A')} | Active: {getattr(u, 'active', 'N/A')}")

print("\n=== 2. HABILITANDO USUARIOS Y ASIGNANDO CONTRASEÑA ===")
# Registramos ambas variantes para evitar fallas de mayúsculas/minúsculas
variantes_usuario = ['AdminAlanOrozco', 'adminalanorozco']
clave_nueva = 'PuntoDeVentaPro'
hash_clave = generate_password_hash(clave_nueva)

for uname in variantes_usuario:
    u = session.query(User).filter(User.username == uname).first()
    if not u:
        u = User(username=uname)
        session.add(u)
    
    u.password_hash = hash_clave
    if hasattr(u, 'display_name'): u.display_name = 'Admin Alan Orozco'
    if hasattr(u, 'role'): u.role = 'admin'
    if hasattr(u, 'active'): u.active = True
    if hasattr(u, 'failed_attempts'): u.failed_attempts = 0
    if hasattr(u, 'locked_until'): u.locked_until = None

session.commit()

print("\n=== 3. PRUEBA DE CONTRASEÑA EN PYTHON ===")
u_test = session.query(User).filter_by(username='AdminAlanOrozco').first()
valida = check_password_hash(u_test.password_hash, clave_nueva)
print(f"Usuario: {u_test.username}")
print(f"¿Contraseña '{clave_nueva}' es válida?: {'SI ✅' if valida else 'NO ❌'}")