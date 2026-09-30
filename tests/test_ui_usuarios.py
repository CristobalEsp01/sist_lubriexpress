"""Control de acceso por rol y el mantenedor de usuarios y mecánicos.

Las pantallas escriben con su propia SessionLocal(), así que los usuarios de
apoyo se crean con commit y se limpian al final, como en el resto de la UI.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from conftest import rut_de_prueba
from src.auth import Sesion, verificar_password
from src.database import SessionLocal
from src.models import Mecanico, Usuario

PREFIJO = "qa_roles_"


@pytest.fixture
def avisos(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    titulos = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: titulos.append(a[1]))
    return titulos


@pytest.fixture
def sesion():
    """Inicia sesión con el rol pedido, con un usuario real en la base."""
    creados = []

    def iniciar(rol: str) -> int:
        with SessionLocal() as db:
            usuario = Usuario(nombre=f"QA {rol}", username=f"{PREFIJO}{rut_de_prueba()}",
                              password_hash="x", rol=rol)
            db.add(usuario)
            db.commit()
            creados.append(usuario.id)
            Sesion.iniciar(SimpleNamespace(id=usuario.id, nombre=usuario.nombre, rol=rol))
            return usuario.id

    yield iniciar
    Sesion.cerrar()
    with SessionLocal() as db:
        for u in db.scalars(select(Usuario).where(Usuario.username.like(f"{PREFIJO}%"))):
            db.delete(u)
        db.commit()


@pytest.mark.parametrize("rol, supervisa, pestanas", [
    ("USUARIO_NORMAL", False, 6),
    ("SUPERVISOR", True, 7),
    ("ADMINISTRADOR", True, 8),
])
def test_el_rol_manda_en_inventario_y_en_las_pestanas(app, sesion, avisos, rol, supervisa, pestanas):
    """Un botón apagado no basta: el slot vuelve a preguntar, que es lo que
    ataja el doble click y el atajo. Y la pestaña de usuarios existe solo para
    quien puede usarla.

    El costo, el inventario valorizado y los reportes de plata son del dueño:
    el supervisor maneja la bodega sin verlos en los listados."""
    from src.ui import InventarioWidget, VentanaPrincipal

    sesion(rol)
    administra = rol == "ADMINISTRADOR"
    inventario = InventarioWidget()
    assert inventario.boton_ingreso.isEnabled() == supervisa
    assert inventario.tabla.isColumnHidden(6) == (not administra)       # el costo
    assert inventario.tabla_kardex.isColumnHidden(4) == (not administra)
    assert ("a precio costo" in inventario.resumen.text()) == administra
    if inventario.tabla.rowCount():
        inventario.tabla.selectRow(0)
        assert inventario.boton_editar.isEnabled() == supervisa
        assert inventario.boton_ajuste.isEnabled() == supervisa

    inventario.abrir_ingreso_mercaderia() if not supervisa else None
    assert avisos == ([] if supervisa else ["Acción reservada"])

    ventana = VentanaPrincipal()
    assert ventana.pestanias.count() == pestanas
    # Finanzas, como Usuarios, existe solo para quien puede usarla.
    nombres = [ventana.pestanias.tabText(i) for i in range(ventana.pestanias.count())]
    assert ("Finanzas" in nombres) == supervisa
    assert ventana.reportes.lista.count() == (7 if administra else 2)   # Ingresos y Reabastecimiento
    if administra:
        assert ventana.pestanias.tabText(7) == "Usuarios"
        ventana.pestanias.setCurrentIndex(7)
        ventana.usuarios.tabla.selectRow(0)  # elegir una fila es lo que junta los connect
        assert ventana.usuarios.boton_editar.isEnabled()


def test_el_administrador_da_de_alta_y_edita_sin_poder_desactivarse(app, sesion, avisos):
    from src.ui import FormularioUsuario, UsuariosWidget

    admin_id = sesion("ADMINISTRADOR")
    username = f"{PREFIJO}nuevo_{rut_de_prueba()}"

    alta = FormularioUsuario()
    alta.nombre.setText("Paloma QA")
    alta.username.setText(username)
    alta.rol.setCurrentIndex(alta.rol.findData("SUPERVISOR"))
    alta.password.setText("aceite2026")
    alta.confirmacion.setText("otra-cosa")
    alta.accept()
    assert avisos == ["Las contraseñas no coinciden"]
    alta.confirmacion.setText("aceite2026")
    alta.accept()

    with SessionLocal() as db:
        nuevo = db.scalar(select(Usuario).where(Usuario.username == username))
        assert (nuevo.nombre, nuevo.rol, nuevo.activo) == ("Paloma QA", "SUPERVISOR", True)
        assert verificar_password("aceite2026", nuevo.password_hash)  # hasheada, no en claro
        hash_original = nuevo.password_hash

    # Editar sin tocar la contraseña la conserva; el rol sí cambia.
    edicion = FormularioUsuario(usuario_id=nuevo.id)
    assert edicion.rol.currentData() == "SUPERVISOR"
    edicion.rol.setCurrentIndex(edicion.rol.findData("USUARIO_NORMAL"))
    edicion.accept()
    with SessionLocal() as db:
        editado = db.get(Usuario, nuevo.id)
        assert (editado.rol, editado.password_hash) == ("USUARIO_NORMAL", hash_original)

    # Un usuario repetido lo ataja el UNIQUE, y se dice.
    repetido = FormularioUsuario()
    repetido.nombre.setText("Otra")
    repetido.username.setText(username)
    repetido.password.setText("aceite2026")
    repetido.confirmacion.setText("aceite2026")
    repetido.accept()
    assert avisos[-1] == "Usuario repetido"

    # Desactivarse a uno mismo dejaría el sistema sin quien lo deshaga.
    propio = FormularioUsuario(usuario_id=admin_id)
    propio.activo.setChecked(False)
    propio.accept()
    assert avisos[-1] == "No puedes desactivarte"
    with SessionLocal() as db:
        assert db.get(Usuario, admin_id).activo

    widget = UsuariosWidget()
    filas = {widget.tabla.item(f, 1).text(): f for f in range(widget.tabla.rowCount())}
    assert username in filas
    widget.tabla.selectRow(filas[username])
    assert widget.boton_editar.isEnabled()
    assert widget.tabla.item(filas[username], 2).text() == "Usuario normal"


def test_el_administrador_da_de_alta_mecanicos_sin_cuenta(app, sesion, avisos):
    """Hay mecánicos que no usan el computador: se registran solo con el nombre
    que sale en la orden, y se desactivan en vez de borrarse."""
    from src.ui.usuarios import FormularioMecanico, UsuariosWidget

    sesion("ADMINISTRADOR")
    nombre = f"QA Francisco {rut_de_prueba()}"
    try:
        vacio = FormularioMecanico()
        vacio.nombre.setText("   ")
        vacio.accept()
        assert avisos == ["Falta el nombre"]

        alta = FormularioMecanico()
        alta.nombre.setText(f"  {nombre}  ")
        alta.accept()
        with SessionLocal() as db:
            mecanico = db.scalar(select(Mecanico).where(Mecanico.nombre == nombre))
            assert mecanico.activo

        repetido = FormularioMecanico()
        repetido.nombre.setText(nombre)
        repetido.accept()
        assert avisos[-1] == "Mecánico repetido"

        edicion = FormularioMecanico(mecanico_id=mecanico.id)
        assert edicion.nombre.text() == nombre
        edicion.activo.setChecked(False)
        edicion.accept()
        with SessionLocal() as db:
            assert not db.get(Mecanico, mecanico.id).activo

        widget = UsuariosWidget()
        filas = {widget.tabla_mecanicos.item(f, 0).text(): f
                 for f in range(widget.tabla_mecanicos.rowCount())}
        assert widget.tabla_mecanicos.item(filas[nombre], 1).text() == "Inactivo"
        widget.tabla_mecanicos.selectRow(filas[nombre])
        assert widget.boton_editar_mecanico.isEnabled()
    finally:
        with SessionLocal() as db:
            db.query(Mecanico).filter(Mecanico.nombre == nombre).delete()
            db.commit()


def test_cerrar_sesion_pregunta_cierra_y_vuelve_al_login(app, sesion, monkeypatch):
    """El botón pide confirmación; con "No" no pasa nada, con "Sí" la sesión
    queda cerrada y la ventana avisa a main.py para que muestre el login."""
    from PySide6.QtWidgets import QMessageBox

    from src.auth import Sesion
    from src.ui import VentanaPrincipal

    sesion("ADMINISTRADOR")
    ventana = VentanaPrincipal()
    assert ventana.pestanias.cornerWidget() is ventana.boton_cerrar_sesion

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    assert ventana.cerrar_sesion() is False
    assert Sesion.activa() and not ventana.sesion_cerrada

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    ventana.boton_cerrar_sesion.click()
    assert not Sesion.activa() and ventana.sesion_cerrada
    assert not ventana.isVisible()


def test_main_vuelve_al_login_tras_cerrar_sesion_y_termina_con_la_x(app, monkeypatch):
    """Dos vueltas: la primera cierra sesión y vuelve al login; en la segunda se
    cierra la ventana sin cerrar sesión y la aplicación termina."""
    import main
    import src.ui as ui

    logins, ventanas = [], []

    class LoginFalso:
        def exec(self):
            logins.append(1)
            return True

    class VentanaFalsa:
        def __init__(self):
            self.sesion_cerrada = len(ventanas) == 0
            ventanas.append(self)

        def showMaximized(self): pass
        def deleteLater(self): pass

    class AppFalsa:
        def exec(self):
            return 7

    monkeypatch.setattr(ui, "LoginDialog", LoginFalso)
    monkeypatch.setattr(ui, "VentanaPrincipal", VentanaFalsa)
    assert main.ejecutar_sesiones(AppFalsa()) == 7
    assert len(logins) == 2 and len(ventanas) == 2

    class LoginCancelado:
        def exec(self):
            return False

    monkeypatch.setattr(ui, "LoginDialog", LoginCancelado)
    assert main.ejecutar_sesiones(AppFalsa()) == 0


def test_la_version_se_ve_en_el_login_y_en_la_ventana(app, sesion):
    import re

    from PySide6.QtWidgets import QLabel

    from src.ui import LoginDialog, VentanaPrincipal
    from src.version import VERSION

    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)
    sesion("ADMINISTRADOR")
    ventana = VentanaPrincipal()
    assert f"v{VERSION}" in ventana.statusBar().currentMessage()
    assert f"v{VERSION}" in ventana.windowTitle()
    login = LoginDialog()
    textos = [e.text() for e in login.findChildren(QLabel)]
    assert any(f"v{VERSION}" in t for t in textos)
