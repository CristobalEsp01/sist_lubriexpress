"""Servicio Público: el ítem de precio libre de las órdenes de Mercado Público.

Las reglas viven en la base (folio obligatorio, una vez por orden, cantidad 1),
así que se prueban contra PostgreSQL real, en una transacción que se revierte.
La aritmética que cuadra la orden con el presupuesto es pura y se prueba sola.
"""
from datetime import date

import pytest
from conftest import patente_de_prueba, rut_de_prueba
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from src import finanzas
from src.models import Cliente, CuentaPorCobrar, DetalleOrden, Orden, Producto, Servicio, Usuario, Vehiculo
from src.precios import con_iva, iva_de, neto_para_total


def test_neto_para_total_da_el_neto_exacto_o_queda_a_un_peso():
    for total in range(0, 60000):
        neto, exacto = neto_para_total(total)
        assert neto >= 0
        assert exacto == (con_iva(neto) == total)
        assert abs(con_iva(neto) - total) <= 1


def test_neto_para_total_conocidos():
    assert neto_para_total(119000) == (100000, True)
    assert neto_para_total(1190000) == (1000000, True)
    # Con 19 % el total salta de a 1 o de a 2 pesos: los que se saltan quedan a $1.
    inexactos = [t for t in range(1, 200) if not neto_para_total(t)[1]]
    assert inexactos, "con IVA de 19 % hay totales que no se pueden lograr exacto"


@pytest.fixture
def datos(db):
    usuario = Usuario(nombre="QA", username=f"qa_{rut_de_prueba()}",
                      password_hash="x", rol="SUPERVISOR")
    producto = Producto(nombre="Aceite QA", precio_costo=20000, precio_venta=35000,
                        stock_actual=50, stock_minimo=1)
    vehiculo = Vehiculo(cliente=Cliente(rut=rut_de_prueba(), nombre_completo="SEREMI QA"),
                        patente=patente_de_prueba())
    db.add_all([usuario, producto, vehiculo])
    db.flush()
    return usuario, producto, vehiculo


def orden_de(db, usuario, vehiculo, **campos):
    orden = Orden(vehiculo=vehiculo, usuario=usuario, kilometraje_ingreso=1, **campos)
    db.add(orden)
    db.flush()
    return orden


def servicio_publico(db) -> Servicio:
    return db.scalars(select(Servicio).where(Servicio.precio_variable.is_(True))).one()


def rechazada(db, accion):
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            accion()
            db.flush()


def test_el_servicio_publico_existe_una_sola_vez_y_no_se_ofrece_como_normal(db):
    servicio = servicio_publico(db)
    assert (servicio.nombre, servicio.activo) == ("Servicio Público", True)
    rechazada(db, lambda: db.add(Servicio(nombre="Otro", precio_venta=0, precio_variable=True)))


def test_solo_entra_en_ordenes_con_folio_de_mercado_publico(db, datos):
    usuario, _, vehiculo = datos
    servicio = servicio_publico(db)
    sin_folio = orden_de(db, usuario, vehiculo)
    vacio = orden_de(db, usuario, vehiculo, folio_mercado_publico="")
    con_folio = orden_de(db, usuario, vehiculo, folio_mercado_publico="1-1-AG26")

    for orden in (sin_folio, vacio):
        rechazada(db, lambda o=orden: db.add(DetalleOrden(
            orden=o, servicio=servicio, cantidad=1, precio_unitario_cobrado=1000)))

    db.add(DetalleOrden(orden=con_folio, servicio=servicio, cantidad=1,
                        precio_unitario_cobrado=1000, descripcion="Orlando 230.000 km"))
    db.flush()
    assert con_folio.detalles[0].nombre == "Servicio Público – Orlando 230.000 km"


def test_va_una_vez_por_orden_y_de_cantidad_uno(db, datos):
    usuario, _, vehiculo = datos
    servicio = servicio_publico(db)
    orden = orden_de(db, usuario, vehiculo, folio_mercado_publico="2-1-AG26")

    rechazada(db, lambda: db.add(DetalleOrden(
        orden=orden, servicio=servicio, cantidad=2, precio_unitario_cobrado=1000)))
    db.add(DetalleOrden(orden=orden, servicio=servicio, cantidad=1, precio_unitario_cobrado=0))
    db.flush()                                    # precio cero es válido
    rechazada(db, lambda: db.add(DetalleOrden(
        orden=orden, servicio=servicio, cantidad=1, precio_unitario_cobrado=500)))

    otra = orden_de(db, usuario, vehiculo, folio_mercado_publico="2-2-AG26")
    db.add(DetalleOrden(orden=otra, servicio=servicio, cantidad=1, precio_unitario_cobrado=1))
    db.flush()                                    # en otra orden sí


def test_un_servicio_normal_no_se_ve_afectado(db, datos):
    usuario, _, vehiculo = datos
    normal = Servicio(nombre="QA Mano de obra", precio_venta=1000)
    orden = orden_de(db, usuario, vehiculo)       # sin folio
    db.add(DetalleOrden(orden=orden, servicio=normal, cantidad=3, precio_unitario_cobrado=1000))
    db.flush()


def test_la_descripcion_no_puede_ser_vacia(db, datos):
    usuario, _, vehiculo = datos
    orden = orden_de(db, usuario, vehiculo, folio_mercado_publico="3-1-AG26")
    rechazada(db, lambda: db.add(DetalleOrden(
        orden=orden, servicio=servicio_publico(db), cantidad=1,
        precio_unitario_cobrado=1, descripcion="")))


@pytest.mark.parametrize("folio", [None, ""])
def test_la_orden_con_servicio_publico_no_pierde_su_folio(db, datos, folio):
    usuario, _, vehiculo = datos
    orden = orden_de(db, usuario, vehiculo, folio_mercado_publico="4-1-AG26")
    linea = DetalleOrden(orden=orden, servicio=servicio_publico(db), cantidad=1,
                         precio_unitario_cobrado=1000)
    db.add(linea)
    db.flush()

    def quitar():
        orden.folio_mercado_publico = folio
    rechazada(db, quitar)
    db.expire(orden)

    db.delete(linea)
    db.flush()
    orden.folio_mercado_publico = folio           # sin la línea, sí se puede
    db.flush()


def test_la_cuenta_por_cobrar_sale_por_el_monto_del_presupuesto(db, datos):
    """Una orden de MP con un producto y el Servicio Público que la cuadra a un
    presupuesto de $1.000.000: la factura sale por ese monto exacto."""
    usuario, producto, vehiculo = datos
    presupuesto = 1_000_000
    neto_total, exacto = neto_para_total(presupuesto)
    assert exacto
    en_producto = 2 * 35000
    orden = orden_de(db, usuario, vehiculo, folio_mercado_publico="5-1-AG26",
                     subtotal=neto_total, impuesto=iva_de(neto_total),
                     ajuste_redondeo=0, total_final=presupuesto)
    db.add_all([
        DetalleOrden(orden=orden, producto=producto, cantidad=2, precio_unitario_cobrado=35000),
        DetalleOrden(orden=orden, servicio=servicio_publico(db), cantidad=1,
                     precio_unitario_cobrado=neto_total - en_producto,
                     descripcion="Cambio de motor"),
    ])
    db.flush()
    db.refresh(orden)
    cuenta = db.query(CuentaPorCobrar).filter_by(orden_id=orden.id).one()
    finanzas.registrar_factura(db, cuenta, "900", date(2026, 9, 3), usuario.id)
    db.refresh(cuenta)

    assert cuenta.monto == presupuesto
    # El Servicio Público no tiene costo: solo el producto cuenta.
    assert cuenta.costo == 2 * 20000
    assert cuenta.margen == neto_total - 2 * 20000
