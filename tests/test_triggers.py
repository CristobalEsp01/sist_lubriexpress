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


def test_vender_y_atender_una_orden_descuentan_stock_con_su_rastro(db, datos):
    """Los dos caminos de salida dejan el mismo tipo de huella, cada uno
    apuntando a su documento de origen."""
    usuario, producto, cliente, vehiculo = datos

    venta = Venta(usuario=usuario, cliente=cliente, numero_boleta="QA-001", total_final=105000)
    db.add(venta)
    db.flush()
    db.add(DetalleVenta(venta=venta, producto=producto, cantidad=3, precio_unitario_cobrado=35000))
    db.flush()
    db.refresh(producto)  # el trigger tocó la fila por fuera de la sesión
    assert producto.stock_actual == 7

    orden = Orden(vehiculo=vehiculo, usuario=usuario, kilometraje_ingreso=120000,
                  subtotal=70000, total_final=70000)
    db.add(orden)
    db.flush()
    db.add(DetalleOrden(orden=orden, producto=producto, cantidad=2, precio_unitario_cobrado=35000))
    db.flush()
    db.refresh(producto)
    assert producto.stock_actual == 5

    por_tipo = {
        m.tipo_movimiento: m
        for m in db.query(KardexMovimiento).filter_by(producto_id=producto.id)
    }
    salida_venta, salida_orden = por_tipo["SALIDA_VENTA"], por_tipo["SALIDA_ORDEN"]
    assert (salida_venta.cantidad_movida, salida_venta.stock_resultante) == (-3, 7)
    assert salida_venta.venta_id == venta.id and salida_venta.orden_id is None
    assert salida_venta.usuario_id == usuario.id
    assert (salida_orden.cantidad_movida, salida_orden.stock_resultante) == (-2, 5)
    assert salida_orden.orden_id == orden.id and salida_orden.venta_id is None


@pytest.mark.parametrize("tipo, cantidad, esperado", [
    ("ENTRADA", 6, 16),          # llegó mercadería
    ("AJUSTE_MANUAL", -4, 6),    # merma o corrección a la baja
])
def test_un_movimiento_manual_mueve_el_stock(db, datos, tipo, cantidad, esperado):
    usuario, producto, _, _ = datos

    db.add(KardexMovimiento(producto=producto, usuario=usuario,
                            tipo_movimiento=tipo, cantidad_movida=cantidad))
    db.flush()

    db.refresh(producto)
    assert producto.stock_actual == esperado
    mov = db.query(KardexMovimiento).filter_by(producto_id=producto.id).one()
    assert mov.stock_resultante == esperado  # lo calcula el trigger, no la aplicación


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


@pytest.mark.parametrize("caso", ["ajuste bajo cero", "movimiento de cero", "descuento doble"])
def test_la_base_rechaza_lo_que_no_cuadra(db, datos, caso):
    usuario, producto, _, vehiculo = datos

    if caso == "ajuste bajo cero":
        db.add(KardexMovimiento(producto=producto, usuario=usuario,
                                tipo_movimiento="AJUSTE_MANUAL", cantidad_movida=-11))
    elif caso == "movimiento de cero":
        db.add(KardexMovimiento(producto=producto, usuario=usuario,
                                tipo_movimiento="AJUSTE_MANUAL", cantidad_movida=0))
    else:  # porcentaje y monto son excluyentes
        db.add(Orden(vehiculo=vehiculo, usuario=usuario, kilometraje_ingreso=1,
                     descuento_porcentaje=10, descuento_monto=5000))

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
