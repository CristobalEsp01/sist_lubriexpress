"""Control de acceso por rol y el mantenedor de usuarios.

Las pantallas escriben con su propia SessionLocal(), así que los usuarios de
apoyo se crean con commit y se limpian al final, como en el resto de la UI.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from conftest import rut_de_prueba
from src.auth import Sesion, verificar_password
from src.database import SessionLocal
from src.models import Usuario

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
    ("USUARIO_NORMAL", False, 4),
    ("SUPERVISOR", True, 4),
    ("ADMINISTRADOR", True, 5),
])
def test_el_rol_manda_en_inventario_y_en_las_pestanas(app, sesion, avisos, rol, supervisa, pestanas):
    """Un botón apagado no basta: el slot vuelve a preguntar, que es lo que
    ataja el doble click y el atajo. Y la pestaña de usuarios existe solo para
    quien puede usarla."""
    from src.ui import InventarioWidget, VentanaPrincipal

    sesion(rol)
    inventario = InventarioWidget()
    assert inventario.boton_ingreso.isEnabled() == supervisa
    assert inventario.tabla.isColumnHidden(6) == (not supervisa)  # el costo
    if inventario.tabla.rowCount():
        inventario.tabla.selectRow(0)
        assert inventario.boton_editar.isEnabled() == supervisa
        assert inventario.boton_ajuste.isEnabled() == supervisa

    inventario.abrir_ingreso_mercaderia() if not supervisa else None
    assert avisos == ([] if supervisa else ["Acción reservada"])

    ventana = VentanaPrincipal()
    assert ventana.pestanias.count() == pestanas
    if pestanas == 5:
        assert ventana.pestanias.tabText(4) == "Usuarios"
        ventana.pestanias.setCurrentIndex(4)
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
