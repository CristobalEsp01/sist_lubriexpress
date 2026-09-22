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
    Cliente, DetalleOrden, DetalleVenta, KardexMovimiento, Orden, PagoOrden, Producto,
    Servicio, Ubicacion, Usuario, Vehiculo, Venta,
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

    # La mano de obra se cobra en la misma orden y no toca el inventario.
    servicio = Servicio(nombre="Cambio de aceite QA", precio_venta=15000)
    db.add(DetalleOrden(orden=orden, servicio=servicio, cantidad=1, precio_unitario_cobrado=15000))
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
    assert db.query(KardexMovimiento).filter_by(orden_id=orden.id).count() == 1  # el servicio, no


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


@pytest.mark.parametrize("caso", [
    "ajuste bajo cero", "movimiento de cero", "descuento doble",
    "línea sin ítem", "línea con producto y servicio",
])
def test_la_base_rechaza_lo_que_no_cuadra(db, datos, caso):
    usuario, producto, _, vehiculo = datos

    if caso.startswith("línea"):
        orden = Orden(vehiculo=vehiculo, usuario=usuario, kilometraje_ingreso=1)
        servicio = Servicio(nombre="QA", precio_venta=1) if "servicio" in caso else None
        db.add(DetalleOrden(orden=orden, producto=producto if servicio else None,
                            servicio=servicio, cantidad=1, precio_unitario_cobrado=1))
    elif caso == "ajuste bajo cero":
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


def test_el_estado_de_pago_lo_deciden_los_abonos(db, datos):
    """Una orden se paga por partes y nadie escribe "pagada" a mano.

    Si la pantalla pudiera marcarla, habría dos fuentes para el mismo dato —la
    casilla y la suma de los abonos— y tarde o temprano la insignia del
    historial diría una cosa y la caja otra.
    """
    usuario, _, _, vehiculo = datos
    orden = Orden(vehiculo_id=vehiculo.id, usuario_id=usuario.id,
                  subtotal=10000, impuesto=1900, total_final=11900)
    db.add(orden)
    db.flush()
    assert not orden.estado_pago and orden.saldo == 11900

    db.add(PagoOrden(orden_id=orden.id, usuario_id=usuario.id, monto=5000))
    db.flush()
    # El trigger escribe la orden por fuera de la sesión, como los de stock.
    db.refresh(orden)
    assert not orden.estado_pago
    assert (orden.monto_pagado, orden.saldo) == (5000, 6900)

    db.add(PagoOrden(orden_id=orden.id, usuario_id=usuario.id, monto=6900))
    db.flush()
    db.refresh(orden)
    assert orden.estado_pago
    assert (orden.monto_pagado, orden.saldo) == (11900, 0)


def test_quitar_una_linea_de_una_orden_devuelve_el_stock_con_su_rastro(db, datos):
    """Una orden abierta ya descontó: el mecánico sacó el aceite de la repisa.
    Si después se quita la línea —se cargó de más, o se anula la orden entera—
    el stock tiene que volver solo y dejar dicho por qué, igual que al salir.
    """
    usuario, producto, cliente, vehiculo = datos

    orden = Orden(vehiculo=vehiculo, usuario=usuario, kilometraje_ingreso=90000,
                  estado="ABIERTA", subtotal=105000, total_final=105000)
    db.add(orden)
    db.flush()
    linea = DetalleOrden(orden=orden, producto=producto, cantidad=3,
                         precio_unitario_cobrado=35000)
    db.add(linea)
    db.flush()
    db.refresh(producto)
    assert producto.stock_actual == 7

    db.delete(linea)
    db.flush()
    db.refresh(producto)
    assert producto.stock_actual == 10

    devolucion = db.query(KardexMovimiento).filter_by(
        producto_id=producto.id, tipo_movimiento="DEVOLUCION_ORDEN").one()
    assert (devolucion.cantidad_movida, devolucion.stock_resultante) == (3, 10)
    # Con su orden detrás: un Kardex que no dice de dónde vino el stock no
    # sirve para cuadrar nada.
    assert devolucion.orden_id == orden.id


def test_quitar_una_linea_de_servicio_no_toca_el_kardex(db, datos):
    """Los servicios no tienen stock, así que su línea entra y sale sin dejar
    movimiento. Es el mismo WHEN que ya protege al trigger de descuento."""
    usuario, producto, cliente, vehiculo = datos

    servicio = Servicio(nombre="QA Revisión", precio_venta=12000)
    orden = Orden(vehiculo=vehiculo, usuario=usuario, kilometraje_ingreso=90000,
                  estado="ABIERTA", subtotal=12000, total_final=12000)
    db.add_all([servicio, orden])
    db.flush()
    linea = DetalleOrden(orden=orden, servicio=servicio, cantidad=1,
                         precio_unitario_cobrado=12000)
    db.add(linea)
    db.flush()
    db.delete(linea)
    db.flush()

    assert db.query(KardexMovimiento).filter_by(orden_id=orden.id).count() == 0


def test_agregarle_una_linea_a_una_orden_pagada_la_deja_debiendo(db, datos):
    """Una orden abierta que se pagó al dejar el auto, y a la que después se le
    carga un repuesto más, no puede seguir marcada como pagada. El estado sale
    de los abonos contra el total, y el total acaba de cambiar."""
    usuario, producto, cliente, vehiculo = datos

    orden = Orden(vehiculo=vehiculo, usuario=usuario, kilometraje_ingreso=90000,
                  estado="ABIERTA", subtotal=35000, total_final=41650)
    db.add(orden)
    db.flush()
    db.add_all([
        DetalleOrden(orden=orden, producto=producto, cantidad=1, precio_unitario_cobrado=35000),
        PagoOrden(orden=orden, usuario=usuario, monto=41650),
    ])
    db.flush()
    db.refresh(orden)
    assert orden.estado_pago is True

    orden.total_final = 83300   # se le agregó otra línea antes de entregarla
    db.flush()
    db.refresh(orden)
    assert orden.estado_pago is False
