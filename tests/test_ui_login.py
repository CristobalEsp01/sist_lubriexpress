"""El inicio de sesión contra un usuario real: clave mala, cuenta desactivada
y entrada correcta, con el aviso en la misma ventana."""
import pytest
from PySide6.QtWidgets import QDialog
from conftest import rut_de_prueba
from sqlalchemy import select

from src.auth import Sesion, hash_password
from src.database import SessionLocal
from src.models import Usuario


@pytest.fixture
def cuenta():
    username = f"qa_login_{rut_de_prueba()}"
    with SessionLocal() as db:
        db.add(Usuario(nombre="Cajera QA", username=username,
                       password_hash=hash_password("aceite2026"), rol="SUPERVISOR"))
        db.commit()
    yield username
    Sesion.cerrar()
    with SessionLocal() as db:
        db.delete(db.scalar(select(Usuario).where(Usuario.username == username)))
        db.commit()


def test_el_login_avisa_en_la_ventana_y_abre_la_sesion(app, cuenta):
    from src.ui import LoginDialog

    dialogo = LoginDialog()
    dialogo._intentar()
    assert dialogo.aviso.text() == "Ingresa usuario y contraseña."

    dialogo.username.setText(cuenta)
    dialogo.password.setText("otra-clave")
    dialogo._intentar()
    assert dialogo.aviso.text() == "Usuario o contraseña incorrectos."
    assert dialogo.password.text() == "" and not Sesion.activa()

    with SessionLocal() as db:
        db.scalar(select(Usuario).where(Usuario.username == cuenta)).activo = False
        db.commit()
    dialogo.password.setText("aceite2026")
    dialogo._intentar()
    assert "desactivada" in dialogo.aviso.text() and not Sesion.activa()

    with SessionLocal() as db:
        db.scalar(select(Usuario).where(Usuario.username == cuenta)).activo = True
        db.commit()
    dialogo.password.setText("aceite2026")
    dialogo._intentar()
    assert Sesion.activa() and (Sesion.nombre, Sesion.rol) == ("Cajera QA", "SUPERVISOR")
    assert dialogo.result() == QDialog.Accepted
