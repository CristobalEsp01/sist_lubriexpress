"""La caja chica del día, sin interfaz.

Las cifras se suman sobre el día entero, así que las pruebas usan una fecha
antigua y vacía: sobre "hoy" estarían contando las ventas reales de la base de
desarrollo y el resultado cambiaría según quién vendió algo esa mañana.
"""
from datetime import date, datetime

from sqlalchemy import select

from src import caja
from src.models import MovimientoCaja, Orden, PagoOrden, Usuario, Venta

DIA = date(2001, 2, 3)
AYER = date(2001, 2, 2)


def _usuario(db):
    return db.scalars(select(Usuario)).first()


def test_el_balance_del_dia_es_apertura_mas_entradas_menos_salidas(db):
    """La cuenta de Fabián: parten con 40, entran 20 en efectivo, sale un flete
    de 10, deberían tener 50. Las ventas y los abonos no se copian a la caja: se
    suman de donde ya están guardados, para que no haya dos verdades."""
    usuario = _usuario(db)
    db.add_all([
        MovimientoCaja(usuario_id=usuario.id, tipo="APERTURA", monto=40000,
                       motivo="Apertura de caja", fecha=datetime(2001, 2, 3, 8, 30)),
        Venta(usuario_id=usuario.id, total_final=18000, impuesto=2874,
              fecha_venta=datetime(2001, 2, 3, 10, 0)),
        MovimientoCaja(usuario_id=usuario.id, tipo="INGRESO", monto=2000,
                       motivo="Sencillo", fecha=datetime(2001, 2, 3, 11, 0)),
        MovimientoCaja(usuario_id=usuario.id, tipo="EGRESO", monto=10000,
                       motivo="Flete", fecha=datetime(2001, 2, 3, 12, 0)),
    ])
    db.flush()

    assert caja.resumen(db, DIA) == {
        "apertura": 40000, "entradas": 20000, "salidas": 10000, "balance": 50000,
        "otros_medios": 0,
    }
    assert caja.tiene_apertura(db, DIA)
    # Un día sin nada no es un error: es una caja que todavía no abre.
    assert caja.resumen(db, AYER)["balance"] == 0
    assert not caja.tiene_apertura(db, AYER)


def test_anular_deja_las_cifras_como_si_el_movimiento_no_existiera(db):
    """Corregir no borra: se inserta la inversa. Pero el par anulado no puede
    seguir moviendo el balance, ni aparecer como plata que entró y salió."""
    usuario = _usuario(db)
    gasto = MovimientoCaja(usuario_id=usuario.id, tipo="EGRESO", monto=9000,
                           motivo="Tecleado de más", fecha=datetime(2001, 2, 3, 9, 0))
    db.add(gasto)
    db.flush()
    assert caja.resumen(db, DIA)["salidas"] == 9000

    caja.anular(db, gasto.id, usuario.id)
    db.flush()

    assert caja.resumen(db, DIA) == {
        "apertura": 0, "entradas": 0, "salidas": 0, "balance": 0, "otros_medios": 0,
    }
    # La fila sigue ahí, marcada: la caja es de solo agregado.
    filas = caja.movimientos(db, DIA)
    assert [(f.motivo, f.anulado) for f in filas] == [
        ("Tecleado de más", True), ("Anula: Tecleado de más", True),
    ]


def test_el_abono_de_una_orden_entra_el_dia_en_que_se_cobro(db):
    """Una orden dejada el lunes y pagada el miércoles es plata del miércoles."""
    usuario = _usuario(db)
    orden = db.scalars(select(Orden).limit(1)).first()
    if orden is None:
        import pytest
        pytest.skip("la base no tiene órdenes sobre las que abonar")

    db.add(PagoOrden(orden_id=orden.id, usuario_id=usuario.id, monto=12500,
                     fecha_pago=datetime(2001, 2, 3, 16, 0)))
    db.flush()

    assert caja.resumen(db, DIA)["entradas"] == 12500
    assert caja.resumen(db, AYER)["entradas"] == 0


def test_lo_pagado_con_tarjeta_o_transferencia_no_pasa_por_el_cajon(db):
    """La caja dice cuánta plata debería haber en el cajón: una venta con
    tarjeta se cobró, pero su plata está en el banco. Se muestra aparte para
    que el día cuadre entero sin inflar lo que se cuenta a mano."""
    usuario = _usuario(db)
    orden = db.scalars(select(Orden).limit(1)).first()
    if orden is None:
        import pytest
        pytest.skip("la base no tiene órdenes sobre las que abonar")

    db.add_all([
        Venta(usuario_id=usuario.id, total_final=10000, impuesto=1597, medio_pago="EFECTIVO",
              numero_boleta="QA-C1", fecha_venta=datetime(2001, 2, 3, 10, 0)),
        Venta(usuario_id=usuario.id, total_final=8000, impuesto=1277, medio_pago="TARJETA",
              numero_boleta="QA-C2", fecha_venta=datetime(2001, 2, 3, 11, 0)),
        PagoOrden(orden_id=orden.id, usuario_id=usuario.id, monto=5000,
                  medio_pago="TRANSFERENCIA", fecha_pago=datetime(2001, 2, 3, 16, 0)),
    ])
    db.flush()

    cifras = caja.resumen(db, DIA)
    assert (cifras["entradas"], cifras["otros_medios"], cifras["balance"]) == (10000, 13000, 10000)

    # La lista del día las muestra todas, cada una con su documento: si el
    # cajón no cuadra, ahí se busca por qué. Solo lo anotado a mano se anula
    # desde la caja; una venta se corrige en su pantalla.
    assert [(f.id, f.tipo, f.motivo, f.monto, f.en_cajon) for f in caja.movimientos(db, DIA)] == [
        (None, "VENTA", "Boleta QA-C1", 10000, True),
        (None, "VENTA", "Boleta QA-C2 · Tarjeta", 8000, False),
        (None, "ORDEN", f"OT #{orden.id} · Transferencia", 5000, False),
    ]


def test_la_base_fecha_las_cosas_en_la_hora_del_taller(db):
    """Regresión: el servidor pone la hora con CURRENT_TIMESTAMP, y corriendo en
    UTC fechaba una venta de las nueve de la noche al día siguiente. Esa venta
    se caía del cierre de caja y del reporte de hoy, y el cajón no cuadraba sin
    que nada en pantalla lo explicara."""
    from sqlalchemy import text

    assert db.scalar(text("SELECT CURRENT_TIMESTAMP")).date() == date.today()
