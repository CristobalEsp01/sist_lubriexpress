"""Cuentas por cobrar y por pagar, contra PostgreSQL real.

Lo que importa vive en la base: el costo que se congela, la cuenta que abre
sola una orden de Mercado Público, y el estado que deciden los abonos. Cada
prueba corre en una transacción que se revierte, como las de los triggers.
"""
from datetime import date, timedelta

import pytest
from conftest import patente_de_prueba, rut_de_prueba
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src import finanzas
from src.models import (
    Cliente, CuentaPorCobrar, DetalleOrden, DetalleVenta, FacturaProveedor, Orden,
    PagoCobro, PagoOrden, PagoProveedor, Producto, Proveedor, Servicio, Usuario, Vehiculo, Venta,
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


def test_quitar_el_folio_anula_la_cuenta_y_volver_a_ponerlo_la_revive(db, datos):
    """Sin esto la cuenta quedaba "por facturar" para siempre, con una OC que
    la orden ya no tiene."""
    usuario, _, vehiculo = datos
    orden = orden_de(db, usuario, vehiculo, folio_mercado_publico="Q-1")

    orden.folio_mercado_publico = None
    db.flush()
    db.refresh(cuenta := cuenta_de(db, orden))
    assert cuenta.estado == "ANULADA"

    orden.folio_mercado_publico = "Q-2"
    db.flush()
    db.refresh(cuenta)
    assert (cuenta.estado, cuenta.numero_oc) == ("PENDIENTE_FACTURA", "Q-2")


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


def test_pagar_la_cuenta_paga_la_orden_y_editar_el_total_no_lo_deshace(db, datos):
    """El pago de Mercado Público se registra en Finanzas: la orden lo refleja
    sin un abono propio, que la caja contaría como plata del día."""
    usuario, _, vehiculo = datos
    orden = orden_de(db, usuario, vehiculo, folio_mercado_publico="P-1",
                     total_final=119000, impuesto=19000)
    cuenta = cuenta_de(db, orden)
    finanzas.registrar_factura(db, cuenta, "702", date(2026, 9, 1), usuario.id)
    finanzas.registrar_pago_cobro(db, cuenta, 119000, date(2026, 9, 20), usuario.id)
    db.refresh(orden)
    assert orden.estado_pago is True and orden.saldo == 0

    orden.total_final = 120000
    db.flush()
    db.refresh(orden)
    assert orden.estado_pago is True


def test_una_orden_con_cuenta_por_cobrar_no_acepta_pagos_en_ordenes(db, datos):
    usuario, _, vehiculo = datos
    publica = orden_de(db, usuario, vehiculo, folio_mercado_publico="P-2", total_final=1000)
    rechazada(db, lambda: db.add(PagoOrden(orden_id=publica.id, usuario_id=usuario.id,
                                           monto=1000, medio_pago="TRANSFERENCIA")))

    particular = orden_de(db, usuario, vehiculo, total_final=1000)
    db.add(PagoOrden(orden_id=particular.id, usuario_id=usuario.id, monto=1000))
    db.flush()
    db.refresh(particular)
    assert particular.estado_pago is True


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


# --- listados, mora y resúmenes -----------------------------------------------

def suyas(filas, *cuentas):
    """Las filas de estas cuentas: la base de desarrollo puede tener otras."""
    ids = {c.id for c in cuentas}
    return [f for f in filas if f.id in ids]


def test_la_mora_parte_pasado_el_dia_30_desde_la_factura():
    factura = date(2026, 8, 1)
    assert finanzas.dias_de_mora_cobro(factura, date(2026, 8, 31)) == 0     # día 30: aún a tiempo
    assert finanzas.dias_de_mora_cobro(factura, date(2026, 9, 1)) == 1
    assert finanzas.dias_de_mora_cobro(factura, date(2026, 9, 30)) == 30
    assert finanzas.dias_de_mora_cobro(None, date(2026, 9, 30)) == 0


def test_el_listado_muestra_lo_estimado_antes_de_facturar_y_lo_congelado_despues(db, datos):
    usuario, producto, vehiculo = datos
    orden = orden_de(db, usuario, vehiculo, folio_mercado_publico="L-1", subtotal=100000,
                     impuesto=19000, total_final=119000)
    db.add(DetalleOrden(orden=orden, producto=producto, cantidad=1, precio_unitario_cobrado=100000))
    db.flush()
    db.refresh(orden)
    cuenta = cuenta_de(db, orden)

    antes, = suyas(finanzas.cuentas_por_cobrar(db, date(2026, 9, 1)), cuenta)
    assert (antes.estado, antes.estimado, antes.saldo) == ("PENDIENTE_FACTURA", True, None)
    assert (antes.neto, antes.monto, antes.costo, antes.margen) == (100000, 119000, 20000, 80000)
    assert antes.cliente == "SEREMI QA" and antes.numero_oc == "L-1"

    finanzas.registrar_factura(db, cuenta, "10", date(2026, 8, 1), usuario.id)
    despues, = suyas(finanzas.cuentas_por_cobrar(db, date(2026, 9, 11)), cuenta)
    assert (despues.estimado, despues.saldo, despues.dias_mora) == (False, 119000, 11)


def test_una_orden_abierta_aparece_por_facturar_recien_al_entregarla(db, datos):
    usuario, _, vehiculo = datos
    orden = orden_de(db, usuario, vehiculo, folio_mercado_publico="L-2", estado="ABIERTA")
    cuenta = cuenta_de(db, orden)
    assert suyas(finanzas.cuentas_por_cobrar(db), cuenta) == []

    orden.estado = "ENTREGADA"
    db.flush()
    assert [f.estado for f in suyas(finanzas.cuentas_por_cobrar(db), cuenta)] == ["PENDIENTE_FACTURA"]


def test_el_resumen_suma_saldos_morosos_pendientes_y_margen_del_mes(db, datos):
    usuario, _, vehiculo = datos
    hoy = date(2026, 9, 20)
    a_tiempo = finanzas.crear_cuenta_manual(db, cliente_nombre="A", numero_factura="1",
        fecha_factura=date(2026, 9, 10), venta_neto=100000, costo=60000, usuario_id=usuario.id)
    morosa = finanzas.crear_cuenta_manual(db, cliente_nombre="B", numero_factura="2",
        fecha_factura=date(2026, 7, 1), venta_neto=200000, usuario_id=usuario.id)   # sin costo
    finanzas.registrar_pago_cobro(db, morosa, 50000, date(2026, 9, 1), usuario.id)
    orden = orden_de(db, usuario, vehiculo, folio_mercado_publico="R-1", total_final=119000,
                     impuesto=19000)
    db.refresh(orden)

    filas = suyas(finanzas.cuentas_por_cobrar(db, hoy), a_tiempo, morosa, cuenta_de(db, orden))
    resumen = finanzas.resumen_por_cobrar(filas, hoy)
    assert resumen["por_cobrar"] == 119000 + (238000 - 50000)
    assert (resumen["moroso"], resumen["morosas"]) == (238000 - 50000, 1)
    assert (resumen["sin_factura"], resumen["sin_factura_monto"]) == (1, 119000)
    # Del mes solo cuenta la de septiembre; la otra facturó en julio.
    assert (resumen["margen_mes"], resumen["margen_mes_sin_dato"]) == (40000, 0)


def test_un_abono_no_pasa_del_saldo_y_al_completarlo_la_cuenta_queda_pagada(db, datos):
    usuario, _, _ = datos
    cuenta = finanzas.crear_cuenta_manual(db, cliente_nombre="C", numero_factura="3",
        fecha_factura=date(2026, 9, 1), venta_neto=100000, usuario_id=usuario.id)   # 119.000
    hoy = date(2026, 9, 5)

    with pytest.raises(ValueError, match="supera el saldo"):
        finanzas.registrar_pago_cobro(db, cuenta, 119001, hoy, usuario.id)
    with pytest.raises(ValueError, match="mayor que cero"):
        finanzas.registrar_pago_cobro(db, cuenta, 0, hoy, usuario.id)

    finanzas.registrar_pago_cobro(db, cuenta, 19000, hoy, usuario.id)
    assert (cuenta.estado, cuenta.saldo) == ("POR_COBRAR", 100000)
    finanzas.registrar_pago_cobro(db, cuenta, 100000, hoy, usuario.id)
    assert (cuenta.estado, cuenta.saldo) == ("PAGADA", 0)
    with pytest.raises(ValueError, match="no admite pagos"):
        finanzas.registrar_pago_cobro(db, cuenta, 1, hoy, usuario.id)


def test_solo_se_anula_una_cuenta_manual_sin_pagos(db, datos):
    usuario, _, vehiculo = datos
    manual = finanzas.crear_cuenta_manual(db, cliente_nombre="D", numero_factura="4",
        fecha_factura=date(2026, 9, 1), venta_neto=1000, usuario_id=usuario.id)
    con_pago = finanzas.crear_cuenta_manual(db, cliente_nombre="E", numero_factura="5",
        fecha_factura=date(2026, 9, 1), venta_neto=1000, usuario_id=usuario.id)
    finanzas.registrar_pago_cobro(db, con_pago, 100, date(2026, 9, 2), usuario.id)
    de_orden = cuenta_de(db, orden_de(db, usuario, vehiculo, folio_mercado_publico="A-9"))

    finanzas.anular_cuenta_manual(db, manual)
    assert manual.estado == "ANULADA"
    for cuenta in (con_pago, de_orden):
        with pytest.raises(ValueError):
            finanzas.anular_cuenta_manual(db, cuenta)


def test_proveedores_facturas_vencimiento_mora_y_pagos(db, datos):
    usuario, _, _ = datos
    with pytest.raises(ValueError, match="RUT"):
        finanzas.crear_proveedor(db, "Lubricantes QA", "12.345.678-9")
    with pytest.raises(ValueError, match="nombre"):
        finanzas.crear_proveedor(db, "  ")
    rut = rut_de_prueba()
    proveedor = finanzas.crear_proveedor(db, f"Lubricantes QA {rut}", rut.replace(".", "").replace("-", ""), 45)
    assert proveedor.rut == rut

    compra = date(2026, 9, 1)
    con_plazo = finanzas.registrar_factura_proveedor(db, proveedor, " F-1 ", compra, 500000, usuario.id)
    assert (con_plazo.numero_factura, con_plazo.fecha_vencimiento) == ("F-1", compra + timedelta(days=45))
    fijada = finanzas.registrar_factura_proveedor(
        db, proveedor, "F-2", compra, 200000, usuario.id, fecha_vencimiento=date(2026, 9, 10))
    with pytest.raises(ValueError, match="anterior"):
        finanzas.registrar_factura_proveedor(db, proveedor, "F-3", compra, 1, usuario.id,
                                             fecha_vencimiento=date(2026, 8, 31))
    with pytest.raises(ValueError, match="mayor que cero"):
        finanzas.registrar_factura_proveedor(db, proveedor, "F-4", compra, 0, usuario.id)

    hoy = date(2026, 9, 15)
    filas = [f for f in finanzas.facturas_por_pagar(db, hoy) if f.proveedor_id == proveedor.id]
    assert {f.numero_factura: f.dias_mora for f in filas} == {"F-1": 0, "F-2": 5}
    assert finanzas.resumen_por_pagar(filas) == {"por_pagar": 700000, "vencido": 200000, "vencidas": 1}

    with pytest.raises(ValueError, match="supera el saldo"):
        finanzas.registrar_pago_proveedor(db, fijada, 200001, hoy, usuario.id)
    finanzas.registrar_pago_proveedor(db, fijada, 200000, hoy, usuario.id)
    assert (fijada.estado, fijada.saldo) == ("PAGADA", 0)

    finanzas.anular_factura_proveedor(db, con_plazo)
    assert con_plazo.estado == "ANULADA"
    with pytest.raises(ValueError, match="pendiente y sin pagos"):
        finanzas.anular_factura_proveedor(db, fijada)
    filas = [f for f in finanzas.facturas_por_pagar(db, hoy) if f.proveedor_id == proveedor.id]
    assert finanzas.resumen_por_pagar(filas)["por_pagar"] == 0
