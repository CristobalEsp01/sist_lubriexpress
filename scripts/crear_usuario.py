"""Crea o actualiza un usuario con contraseña hasheada.

Todavía no hay pantalla de administración de usuarios (Propuesta 3.5: Roles y
Perfiles), así que mientras tanto los usuarios se dan de alta por acá.

Uso:
    .venv/bin/python scripts/crear_usuario.py
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from src.auth import hash_password  # noqa: E402
from src.database import SessionLocal  # noqa: E402
from src.models import Usuario  # noqa: E402

ROLES = ("ADMINISTRADOR", "SUPERVISOR", "USUARIO_NORMAL")


def main() -> None:
    nombre = input("Nombre completo: ").strip()
    username = input("Usuario (login): ").strip()

    rol = ""
    while rol not in ROLES:
        rol = input(f"Rol {ROLES}: ").strip().upper()

    password = getpass.getpass("Contraseña: ")
    confirmacion = getpass.getpass("Repite la contraseña: ")
    if password != confirmacion:
        print("Las contraseñas no coinciden. Nada se guardó.")
        return
    if len(password) < 6:
        print("La contraseña debe tener al menos 6 caracteres. Nada se guardó.")
        return

    with SessionLocal() as db:
        existente = db.scalar(select(Usuario).where(Usuario.username == username))
        if existente:
            existente.password_hash = hash_password(password)
            existente.nombre = nombre
            existente.rol = rol
            existente.activo = True
            db.commit()
            print(f"Usuario '{username}' actualizado (rol {rol}).")
        else:
            db.add(Usuario(
                nombre=nombre, username=username,
                password_hash=hash_password(password), rol=rol, activo=True,
            ))
            db.commit()
            print(f"Usuario '{username}' creado con rol {rol}.")


if __name__ == "__main__":
    main()
