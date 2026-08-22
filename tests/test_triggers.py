"""Pruebas contra PostgreSQL real: los triggers de stock y kardex.

Es lo que promete la propuesta —descuento exacto y trazabilidad auditable—
y vive en la base de datos, no en Python. Cada prueba corre dentro de una
transacción que se revierte al terminar, así que no deja residuos.
"""
import pytest
from conftest import patente_de_prueba, rut_de_prueba
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.models import (
    Cliente, DetalleOrden, DetalleVenta, KardexMovimiento, Orden, Producto,
    Ubicacion, Usuario, Vehiculo, Venta,
)


@pytest.fixture
def datos(db):
    """Usuario, producto con 10 unidades y un vehículo listo para una orden."""
    usuario = Usuario(nombre="QA", username=f"qa_{rut_de_prueba()}", password_hash="x", rol="ADMINISTRADOR")
    ubicacion = Ubicacion(descripcion="Mueble 2 - Repisa B")
    producto = Producto(
        nombre="Aceite 5W30 Mobil 4L", marca="Mobil", categoria="Aceite Motor",
        ubicacion=ubicacion, precio_costo=20000, precio_venta=35000,
        stock_actual=10, stock_minimo=5,
    )
    cliente = Cliente(rut=rut_de_prueba(), nombre_completo="Cliente QA")
    vehiculo = Vehiculo(cliente=cliente, patente=patente_de_prueba(), marca="Toyota", modelo="Hilux")
    db.add_all([usuario, ubicacion, producto, cliente, vehiculo])
    db.flush()
    return usuario, producto, cliente, vehiculo


def test_venta_descuenta_stock_y_registra_kardex(db, datos):
    usuario, producto, cliente, _ = datos

    venta = Venta(usuario=usuario, cliente=cliente, numero_boleta="QA-001", total_final=105000)
    db.add(venta)
    db.flush()
    db.add(DetalleVenta(venta=venta, producto=producto, cantidad=3, precio_unitario_cobrado=35000))
    db.flush()

    db.refresh(producto)  # el trigger tocó la fila por fuera de la sesión
    assert producto.stock_actual == 7

    mov = db.query(KardexMovimiento).filter_by(producto_id=producto.id).one()
    assert (mov.tipo_movimiento, mov.cantidad_movida, mov.stock_resultante) == ("SALIDA_VENTA", -3, 7)
    assert mov.venta_id == venta.id and mov.orden_id is None
    assert mov.usuario_id == usuario.id


def test_orden_descuenta_stock_y_registra_kardex(db, datos):
    usuario, producto, _, vehiculo = datos

    orden = Orden(vehiculo=vehiculo, usuario=usuario, kilometraje_ingreso=120000, subtotal=70000, total_final=70000)
    db.add(orden)
    db.flush()
    db.add(DetalleOrden(orden=orden, producto=producto, cantidad=2, precio_unitario_cobrado=35000))
    db.flush()

    db.refresh(producto)
    assert producto.stock_actual == 8

    mov = db.query(KardexMovimiento).filter_by(producto_id=producto.id).one()
    assert (mov.tipo_movimiento, mov.cantidad_movida, mov.stock_resultante) == ("SALIDA_ORDEN", -2, 8)
    assert mov.orden_id == orden.id and mov.venta_id is None


def test_vender_mas_de_lo_que_hay_no_deja_rastro(db, datos):
    usuario, producto, cliente, _ = datos

    venta = Venta(usuario=usuario, cliente=cliente, numero_boleta="QA-002", total_final=1)
    db.add(venta)
    db.flush()

    # SAVEPOINT: el intento fallido se revierte solo, sin arrastrar el resto.
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(DetalleVenta(venta=venta, producto=producto, cantidad=11, precio_unitario_cobrado=35000))
            db.flush()

    db.refresh(producto)
    assert producto.stock_actual == 10  # intacto
    assert db.query(KardexMovimiento).filter_by(producto_id=producto.id).count() == 0
    assert db.query(DetalleVenta).filter_by(producto_id=producto.id).count() == 0


def test_descuento_porcentaje_y_monto_son_excluyentes(db, datos):
    usuario, _, _, vehiculo = datos

    db.add(Orden(
        vehiculo=vehiculo, usuario=usuario, kilometraje_ingreso=1,
        descuento_porcentaje=10, descuento_monto=5000,
    ))
    with pytest.raises(IntegrityError):
        db.flush()


def test_la_vista_de_stock_critico_detecta_el_umbral(db, datos):
    _, producto, _, _ = datos

    def en_vista():
        filas = db.execute(text("SELECT id FROM vw_stock_critico")).scalars().all()
        return producto.id in filas

    assert not en_vista()  # 10 > mínimo 5
    producto.stock_actual = 5
    db.flush()
    assert en_vista()


def test_entrada_de_mercaderia_suma_stock(db, datos):
    usuario, producto, _, _ = datos

    db.add(KardexMovimiento(
        producto=producto, usuario=usuario, tipo_movimiento="ENTRADA", cantidad_movida=6,
    ))
    db.flush()

    db.refresh(producto)
    assert producto.stock_actual == 16

    mov = db.query(KardexMovimiento).filter_by(producto_id=producto.id).one()
    assert mov.stock_resultante == 16  # lo calcula el trigger, no la aplicación


def test_ajuste_manual_negativo_descuenta_stock(db, datos):
    usuario, producto, _, _ = datos

    db.add(KardexMovimiento(
        producto=producto, usuario=usuario, tipo_movimiento="AJUSTE_MANUAL", cantidad_movida=-4,
    ))
    db.flush()

    db.refresh(producto)
    assert producto.stock_actual == 6
    mov = db.query(KardexMovimiento).filter_by(producto_id=producto.id).one()
    assert mov.stock_resultante == 6


def test_ajuste_manual_no_puede_dejar_stock_negativo(db, datos):
    usuario, producto, _, _ = datos

    db.add(KardexMovimiento(
        producto=producto, usuario=usuario, tipo_movimiento="AJUSTE_MANUAL", cantidad_movida=-11,
    ))
    with pytest.raises(IntegrityError):
        db.flush()


def test_un_movimiento_de_cero_no_se_acepta(db, datos):
    usuario, producto, _, _ = datos

    db.add(KardexMovimiento(
        producto=producto, usuario=usuario, tipo_movimiento="AJUSTE_MANUAL", cantidad_movida=0,
    ))
    with pytest.raises(IntegrityError):
        db.flush()
