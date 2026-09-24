from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import User
from werkzeug.security import generate_password_hash

NEON_URL = "postgresql://neondb_owner:npg_fCbguGmOcK21@ep-autumn-dawn-b4sjcqsf-pooler.c-6.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

engine = create_engine(NEON_URL)
Session = sessionmaker(bind=engine)
session = Session()

print("\n--- 🔍 USUARIOS ACTUALES EN NEON ---")
users = session.query(User).all()
if not users:
    print("⚠️ No hay usuarios registrados en Neon.")
else:
    for u in users:
        print(f"ID: {u.id} | Username: '{u.username}' | Role: {getattr(u, 'role', 'N/A')} | Active: {getattr(u, 'active', 'N/A')}")

print("\n--- 🔧 REPARANDO CUENTA AdminAlanOrozco ---")
admin = session.query(User).filter(User.username.ilike('AdminAlanOrozco')).first()

if not admin:
    admin = User(
        username='AdminAlanOrozco',
        display_name='Admin Alan Orozco',
        role='admin'
    )
    session.add(admin)

# Restablecer contraseña y forzar activación / desbloqueo
admin.password_hash = generate_password_hash('PuntoDeVentaPro')

if hasattr(admin, 'active'):
    admin.active = True
if hasattr(admin, 'failed_attempts'):
    admin.failed_attempts = 0
if hasattr(admin, 'locked_until'):
    admin.locked_until = None

session.commit()

print("✅ CUENTA LISTA:")
print(f" Username: {admin.username}")
print(f" Contraseña: PuntoDeVentaPro")
print(f" Estado activo: {getattr(admin, 'active', True)}")