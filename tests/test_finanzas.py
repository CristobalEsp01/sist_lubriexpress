"""Cuentas por cobrar y por pagar, contra PostgreSQL real.

Lo que importa vive en la base: el costo que se congela, la cuenta que abre
sola una orden de Mercado Público, y el estado que deciden los abonos. Cada
prueba corre en una transacción que se revierte, como las de los triggers.
"""
from datetime import date

import pytest
from conftest import patente_de_prueba, rut_de_prueba
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src import finanzas
from src.models import (
    Cliente, CuentaPorCobrar, DetalleOrden, DetalleVenta, FacturaProveedor, Orden,
    PagoCobro, PagoProveedor, Producto, Proveedor, Servicio, Usuario, Vehiculo, Venta,
)


@pytest.fixture
def datos(db):
    """Usuario, un producto de costo 20.000 y un vehículo para abrir órdenes."""
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


def cuenta_de(db, orden):
    """La cuenta que abrió el trigger: se lee de la base, no del objeto."""
    return db.query(CuentaPorCobrar).filter_by(orden_id=orden.id).one_or_none()


def rechazada(db, accion):
    """La base tiene que rechazar `accion`, sin arrastrar la transacción."""
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            accion()
            db.flush()


# --- costo congelado -------------------------------------------------------

def test_el_costo_de_una_linea_se_congela_y_no_sigue_al_producto(db, datos):
    usuario, producto, vehiculo = datos
    orden = orden_de(db, usuario, vehiculo)

    primera = DetalleOrden(orden=orden, producto=producto, cantidad=2, precio_unitario_cobrado=35000)
    db.add(primera)
    db.flush()
    db.refresh(primera)   # el trigger escribió la columna por fuera del objeto
    assert primera.costo_unitario == 20000

    # El costo sube: lo ya vendido no se mueve, lo nuevo toma el nuevo.
    producto.precio_costo = 25000
    segunda = DetalleOrden(orden=orden, producto=producto, cantidad=1, precio_unitario_cobrado=35000)
    db.add(segunda)
    db.flush()
    db.refresh(primera)
    db.refresh(segunda)
    assert (primera.costo_unitario, segunda.costo_unitario) == (20000, 25000)


def test_un_servicio_no_tiene_costo_y_las_ventas_tambien_lo_congelan(db, datos):
    usuario, producto, vehiculo = datos
    orden = orden_de(db, usuario, vehiculo)
    servicio = Servicio(nombre="Cambio QA", precio_venta=15000)
    linea_servicio = DetalleOrden(orden=orden, servicio=servicio, cantidad=1, precio_unitario_cobrado=15000)
    venta = Venta(usuario=usuario, numero_boleta="QA-COSTO", total_final=1)
    db.add_all([linea_servicio, venta])
    db.flush()
    linea_venta = DetalleVenta(venta=venta, producto=producto, cantidad=1, precio_unitario_cobrado=35000)
    db.add(linea_venta)
    db.flush()
    db.refresh(linea_servicio)
    db.refresh(linea_venta)

    assert linea_servicio.costo_unitario is None
    assert linea_venta.costo_unitario == 20000


def test_un_costo_explicito_manda_sobre_el_del_producto(db, datos):
    usuario, producto, vehiculo = datos
    orden = orden_de(db, usuario, vehiculo)
    linea = DetalleOrden(orden=orden, producto=producto, cantidad=1,
                         precio_unitario_cobrado=35000, costo_unitario=18000)
    db.add(linea)
    db.flush()
    assert linea.costo_unitario == 18000


# --- alta automática de la cuenta ------------------------------------------

def test_una_orden_con_folio_abre_su_cuenta_y_una_sin_folio_no(db, datos):
    usuario, _, vehiculo = datos
    con_folio = orden_de(db, usuario, vehiculo, folio_mercado_publico="1497-2-AG26")
    sin_folio = orden_de(db, usuario, vehiculo)
    folio_vacio = orden_de(db, usuario, vehiculo, folio_mercado_publico="")

    cuenta = cuenta_de(db, con_folio)
    assert (cuenta.estado, cuenta.numero_oc) == ("PENDIENTE_FACTURA", "1497-2-AG26")
    assert cuenta.numero_factura is None and cuenta.venta_neto is None
    assert cuenta_de(db, sin_folio) is None
    assert cuenta_de(db, folio_vacio) is None


def test_el_folio_puesto_despues_abre_la_cuenta_y_la_sigue_hasta_facturar(db, datos):
    usuario, _, vehiculo = datos
    orden = orden_de(db, usuario, vehiculo)
    assert cuenta_de(db, orden) is None

    orden.folio_mercado_publico = "111-1-AG26"
    db.flush()
    cuenta = cuenta_de(db, orden)
    assert cuenta.numero_oc == "111-1-AG26"

    orden.folio_mercado_publico = "111-2-AG26"    # corrigen el folio antes de facturar
    db.flush()
    db.refresh(cuenta)
    assert cuenta.numero_oc == "111-2-AG26"

    orden.total_final = 119000
    orden.impuesto = 19000
    db.flush()
    finanzas.registrar_factura(db, cuenta, "700", date(2026, 9, 1), usuario.id)
    orden.folio_mercado_publico = "999-9-AG26"    # ya facturada: no se toca
    db.flush()
    db.refresh(cuenta)
    assert cuenta.numero_oc == "111-2-AG26"
    assert db.query(CuentaPorCobrar).filter_by(orden_id=orden.id).count() == 1


def test_anular_la_orden_anula_la_cuenta_solo_si_no_hay_factura(db, datos):
    usuario, _, vehiculo = datos
    sin_factura = orden_de(db, usuario, vehiculo, folio_mercado_publico="A-1")
    facturada = orden_de(db, usuario, vehiculo, folio_mercado_publico="A-2",
                         total_final=119000, impuesto=19000)
    finanzas.registrar_factura(db, cuenta_de(db, facturada), "701", date(2026, 9, 1), usuario.id)

    sin_factura.estado = "ANULADA"
    facturada.estado = "ANULADA"
    db.flush()

    assert cuenta_de(db, sin_factura).estado == "ANULADA"
    assert cuenta_de(db, facturada).estado == "POR_COBRAR"   # una nota de crédito, a mano


def test_las_ordenes_que_ya_existian_no_abren_cuenta(db, datos):
    """El actualizador solo crea el trigger: no recorre lo ya guardado. Lo
    pendiente de antes lo ingresa el taller a mano."""
    usuario, _, vehiculo = datos
    antigua = orden_de(db, usuario, vehiculo)
    db.execute(text("ALTER TABLE ordenes DISABLE TRIGGER trg_ordenes_alta_cuenta_cobrar"))
    db.execute(text("UPDATE ordenes SET folio_mercado_publico = 'VIEJA' WHERE id = :i"),
               {"i": antigua.id})
    db.execute(text("ALTER TABLE ordenes ENABLE TRIGGER trg_ordenes_alta_cuenta_cobrar"))
    assert cuenta_de(db, antigua) is None


# --- registrar la factura ---------------------------------------------------

@pytest.mark.parametrize("ajuste", [0, 4, -3])
def test_facturar_congela_neto_iva_y_costo_sin_el_redondeo(db, datos, ajuste):
    usuario, producto, vehiculo = datos
    orden = orden_de(db, usuario, vehiculo, folio_mercado_publico="B-1", subtotal=100000,
                     descuento_monto=10000, impuesto=17100, ajuste_redondeo=ajuste,
                     total_final=107100 + ajuste)
    db.add_all([
        DetalleOrden(orden=orden, producto=producto, cantidad=2, precio_unitario_cobrado=35000),
        DetalleOrden(orden=orden, servicio=Servicio(nombre="QA", precio_venta=1000),
                     cantidad=1, precio_unitario_cobrado=1000),
    ])
    db.flush()
    db.refresh(orden)
    cuenta = cuenta_de(db, orden)

    finanzas.registrar_factura(db, cuenta, " 653 ", date(2026, 9, 2), usuario.id)
    db.refresh(cuenta)

    assert (cuenta.estado, cuenta.numero_factura, cuenta.fecha_factura) == (
        "POR_COBRAR", "653", date(2026, 9, 2))
    assert (cuenta.venta_neto, cuenta.iva, cuenta.costo) == (90000, 17100, 40000)
    assert cuenta.monto == 107100                  # exacto, sin el ajuste de la caja
    assert (cuenta.margen, round(cuenta.margen_porcentaje, 1)) == (50000, 55.6)
    assert cuenta.usuario_id == usuario.id

    # Ya facturada, editar la orden no mueve lo facturado.
    orden.subtotal = 1
    orden.total_final = 1
    db.flush()
    db.refresh(cuenta)
    assert cuenta.monto == 107100


def test_sin_costo_en_una_linea_el_margen_es_sin_dato_y_no_cero(db, datos):
    usuario, producto, vehiculo = datos
    orden = orden_de(db, usuario, vehiculo, folio_mercado_publico="B-2",
                     total_final=119000, impuesto=19000)
    linea = DetalleOrden(orden=orden, producto=producto, cantidad=1, precio_unitario_cobrado=100000)
    db.add(linea)
    db.flush()
    # Una línea guardada antes de que existiera el costo.
    db.execute(text("UPDATE detalle_ordenes SET costo_unitario = NULL WHERE id = :i"), {"i": linea.id})
    db.refresh(orden)
    db.expire_all()
    cuenta = cuenta_de(db, orden)

    finanzas.registrar_factura(db, cuenta, "654", date(2026, 9, 2), usuario.id)

    assert cuenta.costo is None
    assert (cuenta.margen, cuenta.margen_porcentaje) == (None, None)


def test_un_servicio_gratis_se_factura_sin_dividir_por_cero(db, datos):
    usuario, _, vehiculo = datos
    orden = orden_de(db, usuario, vehiculo, folio_mercado_publico="B-3")   # total 0
    cuenta = cuenta_de(db, orden)
    finanzas.registrar_factura(db, cuenta, "655", date(2026, 9, 2), usuario.id)
    assert (cuenta.monto, cuenta.margen, cuenta.margen_porcentaje) == (0, 0, None)


@pytest.mark.parametrize("caso", ["sin número", "orden abierta", "dos veces"])
def test_registrar_la_factura_pide_lo_que_corresponde(db, datos, caso):
    usuario, _, vehiculo = datos
    orden = orden_de(db, usuario, vehiculo, folio_mercado_publico="B-4",
                     estado="ABIERTA" if caso == "orden abierta" else "ENTREGADA")
    cuenta = cuenta_de(db, orden)
    if caso == "dos veces":
        finanzas.registrar_factura(db, cuenta, "656", date(2026, 9, 2), usuario.id)

    with pytest.raises(ValueError):
        finanzas.registrar_factura(db, cuenta, "  " if caso == "sin número" else "657",
                                   date(2026, 9, 2), usuario.id)


# --- cuentas ingresadas a mano ---------------------------------------------

def test_una_cuenta_anterior_al_modulo_se_ingresa_facturada_con_su_costo(db, datos):
    usuario, _, _ = datos
    cuenta = finanzas.crear_cuenta_manual(
        db, cliente_nombre="  Bienes Nacionales ", numero_factura="587", numero_oc="5650-36-AG25",
        fecha_factura=date(2025, 12, 12), venta_neto=545600, costo=89408, usuario_id=usuario.id)

    assert (cuenta.estado, cuenta.orden_id, cuenta.cliente_nombre) == ("POR_COBRAR", None, "Bienes Nacionales")
    assert (cuenta.iva, cuenta.monto, cuenta.margen) == (103664, 649264, 456192)

    sin_costo = finanzas.crear_cuenta_manual(
        db, cliente_nombre="SENADIS", numero_factura="583", fecha_factura=date(2025, 12, 9),
        venta_neto=429900, usuario_id=usuario.id)
    assert (sin_costo.costo, sin_costo.margen) == (None, None)

    with pytest.raises(ValueError):
        finanzas.crear_cuenta_manual(db, cliente_nombre="", numero_factura="1",
                                     fecha_factura=date(2026, 1, 1), venta_neto=1, usuario_id=usuario.id)


@pytest.mark.parametrize("estado, campos", [
    ("sin origen", dict(estado="POR_COBRAR")),                       # ni orden ni cliente
    ("por cobrar sin factura", dict(cliente_nombre="X", estado="POR_COBRAR")),
    ("pendiente con factura", dict(cliente_nombre="X", numero_factura="1",
                                   fecha_factura=date(2026, 1, 1), venta_neto=1, iva=0)),
    ("estado inventado", dict(cliente_nombre="X", numero_factura="1", estado="QUIEN SABE",
                              fecha_factura=date(2026, 1, 1), venta_neto=1, iva=0)),
    ("costo negativo", dict(cliente_nombre="X", numero_factura="1", estado="POR_COBRAR",
                            fecha_factura=date(2026, 1, 1), venta_neto=1, iva=0, costo=-1)),
])
def test_la_base_rechaza_una_cuenta_que_no_cuadra(db, estado, campos):
    rechazada(db, lambda: db.add(CuentaPorCobrar(**campos)))


# --- abonos de una cuenta por cobrar ----------------------------------------

def cuenta_facturada(db, usuario, neto=100000):
    return finanzas.crear_cuenta_manual(
        db, cliente_nombre="CONADI", numero_factura=f"F{neto}", fecha_factura=date(2026, 8, 1),
        venta_neto=neto, usuario_id=usuario.id)


def test_los_abonos_van_saldando_la_cuenta_y_el_ultimo_la_paga(db, datos):
    usuario, _, _ = datos
    cuenta = cuenta_facturada(db, usuario)                        # 119.000 con IVA

    db.add(PagoCobro(cuenta=cuenta, usuario_id=usuario.id, monto=50000, fecha_pago=date(2026, 8, 20)))
    db.flush()
    db.refresh(cuenta)
    assert (cuenta.estado, cuenta.pagado, cuenta.saldo) == ("POR_COBRAR", 50000, 69000)

    db.add(PagoCobro(cuenta=cuenta, usuario_id=usuario.id, monto=69000, fecha_pago=date(2026, 8, 31)))
    db.flush()
    db.refresh(cuenta)
    assert (cuenta.estado, cuenta.pagado, cuenta.saldo) == ("PAGADA", 119000, 0)

    # Saldada, no admite más.
    rechazada(db, lambda: db.add(PagoCobro(cuenta=cuenta, usuario_id=usuario.id, monto=1)))


def test_un_pago_de_mas_no_se_rechaza_y_salda_la_cuenta(db, datos):
    """Los organismos a veces pagan distinto por retenciones: eso lo resuelve
    una persona, no un CHECK que deje el pago sin registrar."""
    usuario, _, _ = datos
    cuenta = cuenta_facturada(db, usuario)                        # 119.000 con IVA
    db.add(PagoCobro(cuenta=cuenta, usuario_id=usuario.id, monto=120000))
    db.flush()
    db.refresh(cuenta)
    assert (cuenta.estado, cuenta.saldo) == ("PAGADA", 0)


def test_no_se_abona_lo_que_aun_no_tiene_factura(db, datos):
    usuario, _, vehiculo = datos
    pendiente = cuenta_de(db, orden_de(db, usuario, vehiculo, folio_mercado_publico="C-1"))
    rechazada(db, lambda: db.add(PagoCobro(cuenta=pendiente, usuario_id=usuario.id, monto=1)))


def test_un_pago_no_puede_ser_cero_ni_negativo(db, datos):
    usuario, _, _ = datos
    cuenta = cuenta_facturada(db, usuario)
    rechazada(db, lambda: db.add(PagoCobro(cuenta=cuenta, usuario_id=usuario.id, monto=0)))


# --- cuentas por pagar ------------------------------------------------------

@pytest.fixture
def factura(db, datos):
    usuario, _, _ = datos
    proveedor = Proveedor(nombre=f"Würth QA {rut_de_prueba()}")
    db.add(proveedor)
    db.flush()
    nueva = FacturaProveedor(proveedor=proveedor, usuario_id=usuario.id, numero_factura="1583073",
                             fecha_compra=date(2026, 1, 2), fecha_vencimiento=date(2026, 2, 1),
                             monto=421280)
    db.add(nueva)
    db.flush()
    return nueva


def test_las_facturas_de_proveedor_se_pagan_por_partes(db, datos, factura):
    usuario, _, _ = datos
    assert (factura.estado, factura.saldo, factura.proveedor.plazo_credito_dias) == ("PENDIENTE", 421280, 30)

    db.add(PagoProveedor(factura=factura, usuario_id=usuario.id, monto=100000))
    db.flush()
    db.refresh(factura)
    assert (factura.estado, factura.saldo) == ("PENDIENTE", 321280)

    db.add(PagoProveedor(factura=factura, usuario_id=usuario.id, monto=321280))
    db.flush()
    db.refresh(factura)
    assert (factura.estado, factura.saldo) == ("PAGADA", 0)

    rechazada(db, lambda: db.add(PagoProveedor(factura=factura, usuario_id=usuario.id, monto=1)))


def test_una_factura_anulada_no_admite_pagos(db, datos, factura):
    usuario, _, _ = datos
    factura.estado = "ANULADA"
    db.flush()
    rechazada(db, lambda: db.add(PagoProveedor(factura=factura, usuario_id=usuario.id, monto=1)))


@pytest.mark.parametrize("caso", ["misma factura del proveedor", "vence antes de comprar",
                                  "monto en cero", "número vacío"])
def test_la_base_rechaza_una_factura_de_proveedor_que_no_cuadra(db, datos, factura, caso):
    usuario, _, _ = datos
    campos = dict(proveedor=factura.proveedor, usuario_id=usuario.id, numero_factura="OTRA",
                  fecha_compra=date(2026, 3, 1), fecha_vencimiento=date(2026, 3, 31), monto=1000)
    if caso == "misma factura del proveedor":
        campos["numero_factura"] = factura.numero_factura
    elif caso == "vence antes de comprar":
        campos["fecha_vencimiento"] = date(2026, 2, 1)
    elif caso == "monto en cero":
        campos["monto"] = 0
    else:
        campos["numero_factura"] = ""
    rechazada(db, lambda: db.add(FacturaProveedor(**campos)))


def test_el_mismo_numero_de_factura_puede_repetirse_entre_proveedores(db, datos, factura):
    usuario, _, _ = datos
    otro = Proveedor(nombre=f"Servimaq QA {rut_de_prueba()}")
    db.add(otro)
    db.flush()
    db.add(FacturaProveedor(proveedor=otro, usuario_id=usuario.id, numero_factura=factura.numero_factura,
                            fecha_compra=date(2026, 1, 2), fecha_vencimiento=date(2026, 2, 1), monto=1))
    db.flush()   # no revienta
