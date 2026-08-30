"""Interfaz del módulo de Órdenes de Trabajo, sin pantalla.

OrdenesWidget escribe con su propia SessionLocal() en cada operación (no con el
fixture `db`, que revierte todo al terminar), así que los datos de apoyo se
crean con commits reales y se limpian explícitamente al final — igual que en
test_ui_ventas.py.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from conftest import patente_de_prueba, rut_de_prueba
from src.auth import Sesion
from src.database import SessionLocal
from src.models import (
    Cliente, DetalleOrden, KardexMovimiento, Orden, Producto, Usuario, Vehiculo,
)

NOMBRE_PRODUCTO = "QA Aceite de motor 10W40"
NOMBRE_CLIENTE = "QA Dueño del taller"


@pytest.fixture
def limpiar():
    yield
    with SessionLocal() as db:
        cliente = db.scalar(select(Cliente).where(Cliente.nombre_completo == NOMBRE_CLIENTE))
        if cliente:
            for vehiculo in db.scalars(select(Vehiculo).where(Vehiculo.cliente_id == cliente.id)):
                for orden in db.scalars(select(Orden).where(Orden.vehiculo_id == vehiculo.id)):
                    db.query(KardexMovimiento).filter_by(orden_id=orden.id).delete()
                    db.query(DetalleOrden).filter_by(orden_id=orden.id).delete()
                    db.delete(orden)
                db.delete(vehiculo)
            db.delete(cliente)
        producto = db.scalar(select(Producto).where(Producto.nombre == NOMBRE_PRODUCTO))
        if producto:
            db.query(KardexMovimiento).filter_by(producto_id=producto.id).delete()
            db.delete(producto)
        for usuario in db.scalars(select(Usuario).where(Usuario.username.like("qa_mecanico_%"))):
            db.delete(usuario)
        db.commit()


@pytest.fixture
def taller(limpiar):
    """Mecánico con sesión iniciada, un producto con 10 unidades y un vehículo."""
    with SessionLocal() as db:
        usuario = Usuario(
            nombre="Mecánico QA", username=f"qa_mecanico_{rut_de_prueba()}",
            password_hash="hash-de-prueba", rol="USUARIO_NORMAL",
        )
        producto = Producto(
            nombre=NOMBRE_PRODUCTO, marca="Castrol", precio_costo=6000,
            precio_venta=12900, stock_actual=10, stock_minimo=2,
        )
        cliente = Cliente(rut=rut_de_prueba(), nombre_completo=NOMBRE_CLIENTE)
        vehiculo = Vehiculo(cliente=cliente, patente=patente_de_prueba(),
                            marca="Toyota", modelo="Yaris")
        db.add_all([usuario, producto, vehiculo])
        db.commit()
        datos = SimpleNamespace(
            usuario_id=usuario.id, producto_id=producto.id, vehiculo_id=vehiculo.id,
        )
        Sesion.iniciar(SimpleNamespace(id=usuario.id, nombre=usuario.nombre, rol=usuario.rol))

    yield datos
    Sesion.cerrar()


@pytest.fixture
def sin_modales(monkeypatch):
    """Los avisos son QMessageBox reales: sin silenciarlos el modal nunca se
    cierra solo y la prueba queda colgada. Devuelve los títulos mostrados."""
    from PySide6.QtWidgets import QMessageBox

    titulos = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: titulos.append(a[1]))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: titulos.append(a[1]))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    return titulos


def test_mirar_el_historial_no_descarta_la_orden_en_progreso(app, taller, sin_modales, monkeypatch):
    """Regresión: abrir_detalle_orden limpiaba el formulario de la pestaña 1.

    Estaba copiado de _iniciar_nueva_orden, así que abrir una orden vieja del
    historial para consultarla borraba la que se estaba armando: carrito,
    kilometraje y observaciones. Mirar no puede escribir.
    """
    from src.ui import ordenes

    with SessionLocal() as db:
        db.add(Orden(vehiculo_id=taller.vehiculo_id, usuario_id=taller.usuario_id,
                     kilometraje_ingreso=98000, subtotal=0, total_final=0))
        db.commit()

    monkeypatch.setattr(ordenes.DialogoDetalleOrden, "exec", lambda self: 0)

    widget = ordenes.OrdenesWidget()
    widget._iniciar_nueva_orden(taller.vehiculo_id)
    widget.agregar_al_carrito(taller.producto_id, 2)
    widget.spin_kilometraje.setValue(120000)
    widget.texto_observaciones.setPlainText("Ingresa con raya en la puerta")

    widget.setCurrentIndex(1)               # carga el historial
    widget.tabla_historial.selectRow(0)     # elegir una fila es lo que junta los connect
    widget.abrir_detalle_orden()

    assert widget.tabla_carrito.rowCount() == 1
    assert widget.spin_kilometraje.value() == 120000
    assert widget.texto_observaciones.toPlainText() == "Ingresa con raya en la puerta"


def test_guardar_la_orden_descuenta_el_stock_y_deja_kardex(app, taller, sin_modales):
    """El camino del dinero, de punta a punta y por la pantalla.

    `test_triggers.py` ya prueba que insertar en detalle_ordenes descuenta y
    deja rastro; lo que falta cubrir es que la pantalla llegue hasta ahí: una
    sola transacción, el usuario de la sesión, y ni una escritura a
    `stock_actual` de por medio.
    """
    from src.ui import ordenes

    widget = ordenes.OrdenesWidget()
    widget._iniciar_nueva_orden(taller.vehiculo_id)
    widget.agregar_al_carrito(taller.producto_id, 3)
    widget.spin_kilometraje.setValue(120000)
    widget.guardar_orden()

    with SessionLocal() as db:
        orden = db.scalar(select(Orden).where(Orden.vehiculo_id == taller.vehiculo_id))
        assert orden.usuario_id == taller.usuario_id
        assert orden.kilometraje_ingreso == 120000
        assert int(orden.total_final) == 3 * 12900

        detalles = db.scalars(select(DetalleOrden).where(DetalleOrden.orden_id == orden.id)).all()
        assert len(detalles) == 1
        assert (detalles[0].producto_id, detalles[0].cantidad) == (taller.producto_id, 3)

        assert db.get(Producto, taller.producto_id).stock_actual == 7  # 10 - 3

        mov = db.scalar(select(KardexMovimiento).where(KardexMovimiento.orden_id == orden.id))
        assert (mov.tipo_movimiento, mov.cantidad_movida, mov.stock_resultante) == (
            "SALIDA_ORDEN", -3, 7
        )
        assert mov.usuario_id == taller.usuario_id

    # La pantalla vuelve al reposo: sin esto la orden siguiente arrastraría la anterior.
    assert not widget.panel_trabajo.isEnabled()
    assert widget.boton_nueva_orden.isEnabled()


def test_la_ventana_recorre_sus_cuatro_pestanas_sin_reventar(app, taller, sin_modales):
    """Smoke de arranque: abrir cada pestaña y elegir una fila en cada tabla.

    Qt no propaga lo que revienta dentro de un slot; el hookwrapper de
    `conftest.py` lo convierte en fallo, pero solo si alguien dispara las
    señales. Recorrer las pestañas y seleccionar es lo primero que hace
    cualquiera al abrir la aplicación, y es donde se juntan los `connect`.
    """
    from PySide6.QtWidgets import QTableWidget, QTabWidget

    from src.ui import VentanaPrincipal

    ventana = VentanaPrincipal()
    for pestanas in ventana.findChildren(QTabWidget):
        for indice in range(pestanas.count()):
            pestanas.setCurrentIndex(indice)

    for tabla in ventana.findChildren(QTableWidget):
        if tabla.rowCount():
            tabla.selectRow(0)

    assert ventana.pestanias.count() == 4
