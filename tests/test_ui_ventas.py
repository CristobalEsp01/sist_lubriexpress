"""Interfaz del módulo de Ventas de Mostrador, sin pantalla.

VentasWidget escribe con su propia SessionLocal() en cada operación (no con
el fixture `db`, que revierte todo al terminar), así que los datos de apoyo
se crean con commits reales y se limpian explícitamente al final — igual que
en test_ui_inventario.py.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from conftest import rut_de_prueba
from src.auth import Sesion
from src.database import SessionLocal
from src.models import DetalleVenta, KardexMovimiento, Producto, Usuario, Venta

NOMBRE_PRODUCTO = "QA Filtro de aceite"


@pytest.fixture
def limpiar():
    yield
    with SessionLocal() as db:
        producto = db.scalar(select(Producto).where(Producto.nombre == NOMBRE_PRODUCTO))
        if producto:
            db.query(KardexMovimiento).filter(KardexMovimiento.producto_id == producto.id).delete()
            db.query(DetalleVenta).filter(DetalleVenta.producto_id == producto.id).delete()
        for venta in db.scalars(select(Venta).where(Venta.numero_boleta.like("QA-%"))):
            db.query(DetalleVenta).filter(DetalleVenta.venta_id == venta.id).delete()
            db.query(KardexMovimiento).filter(KardexMovimiento.venta_id == venta.id).delete()
            db.delete(venta)
        if producto:
            db.delete(producto)
        for usuario in db.scalars(select(Usuario).where(Usuario.username.like("qa_cajera_%"))):
            db.delete(usuario)
        db.commit()


@pytest.fixture
def usuario_qa(limpiar):
    """Deja una sesión iniciada con un usuario real y comiteado, como la
    dejaría LoginDialog. Se cierra sola al terminar la prueba."""
    with SessionLocal() as db:
        usuario = Usuario(
            nombre="Cajera QA", username=f"qa_cajera_{rut_de_prueba()}",
            password_hash="hash-de-prueba", rol="USUARIO_NORMAL",
        )
        db.add(usuario)
        db.commit()
        usuario_id, nombre, rol = usuario.id, usuario.nombre, usuario.rol

    Sesion.iniciar(SimpleNamespace(id=usuario_id, nombre=nombre, rol=rol))
    yield usuario_id
    Sesion.cerrar()


@pytest.fixture
def producto_qa(limpiar):
    with SessionLocal() as db:
        producto = Producto(
            nombre=NOMBRE_PRODUCTO, precio_costo=3000, precio_venta=6000,
            stock_actual=10, stock_minimo=2,
        )
        db.add(producto)
        db.commit()
        producto_id = producto.id
    yield producto_id


def test_agregar_producto_respeta_el_stock_disponible(app, producto_qa, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from src.ui.ventas import VentasWidget

    # Intentar pasarse del stock dispara un aviso real (QMessageBox.warning);
    # sin silenciarlo, .exec() abre un diálogo modal que nunca se cierra solo.
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)

    widget = VentasWidget()
    widget.agregar_producto(producto_qa, cantidad=10)
    widget.agregar_producto(producto_qa, cantidad=5)  # se pasa del stock (10)

    assert len(widget.carrito) == 1
    assert widget.carrito[0]["cantidad"] == 10  # se topa en el máximo disponible


def test_agregar_producto_sin_stock_no_lo_agrega(app, producto_qa, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from src.ui.ventas import VentasWidget

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)

    with SessionLocal() as db:
        db.get(Producto, producto_qa).stock_actual = 0
        db.commit()

    widget = VentasWidget()
    widget.agregar_producto(producto_qa)
    assert widget.carrito == []


def test_generar_venta_crea_la_venta_descuenta_stock_y_registra_kardex(
    app, usuario_qa, producto_qa, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox
    from src.ui.ventas import VentasWidget

    # La venta exitosa también muestra un aviso (QMessageBox.information);
    # sin silenciarlo, el diálogo modal cuelga la prueba esperando un clic.
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)

    widget = VentasWidget()
    widget.agregar_producto(producto_qa, cantidad=3)
    widget.boleta.setText("QA-0001")
    widget.generar_venta()

    with SessionLocal() as db:
        venta = db.scalar(select(Venta).where(Venta.numero_boleta == "QA-0001"))
        assert venta is not None
        assert venta.usuario_id == usuario_qa
        assert int(venta.total_final) == 3 * 6000

        detalle = db.scalars(select(DetalleVenta).where(DetalleVenta.venta_id == venta.id)).all()
        assert len(detalle) == 1
        assert detalle[0].cantidad == 3

        producto = db.get(Producto, producto_qa)
        assert producto.stock_actual == 7  # 10 - 3

        mov = db.scalar(select(KardexMovimiento).where(KardexMovimiento.venta_id == venta.id))
        assert mov.tipo_movimiento == "SALIDA_VENTA"
        assert mov.cantidad_movida == -3
        assert mov.stock_resultante == 7
        assert mov.usuario_id == usuario_qa

    # El carrito y el formulario quedan listos para la siguiente venta.
    assert widget.carrito == []
    assert widget.boleta.text() == ""


def test_generar_venta_exige_numero_de_boleta(app, usuario_qa, producto_qa, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from src.ui.ventas import VentasWidget

    avisos = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *args, **kwargs: avisos.append(args) or QMessageBox.Ok,
    )

    widget = VentasWidget()
    widget.agregar_producto(producto_qa, cantidad=1)
    widget.generar_venta()  # sin boleta

    assert avisos
    with SessionLocal() as db:
        assert db.scalar(select(Venta).where(Venta.numero_boleta == "")) is None


def test_boleta_repetida_no_duplica_la_venta(app, usuario_qa, producto_qa, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from src.ui.ventas import VentasWidget

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)

    primera = VentasWidget()
    primera.agregar_producto(producto_qa, cantidad=1)
    primera.boleta.setText("QA-DUP")
    primera.generar_venta()

    segunda = VentasWidget()
    segunda.agregar_producto(producto_qa, cantidad=1)
    segunda.boleta.setText("QA-DUP")
    segunda.generar_venta()

    with SessionLocal() as db:
        ventas = db.scalars(select(Venta).where(Venta.numero_boleta == "QA-DUP")).all()
        assert len(ventas) == 1
