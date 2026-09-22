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


def test_el_balance_del_dia_junta_lo_cobrado_con_lo_que_se_movio_a_mano(db):
    """AGREGADO + INGRESOS − EGRESOS, que es la aritmética que el taller ya lee
    en el sistema antiguo. Las ventas y los abonos no se copian a la caja: se
    suman de donde ya están guardados, para que no haya dos verdades."""
    usuario = _usuario(db)
    db.add_all([
        Venta(usuario_id=usuario.id, total_final=30000, impuesto=4790,
              fecha_venta=datetime(2001, 2, 3, 10, 0)),
        MovimientoCaja(usuario_id=usuario.id, tipo="INGRESO", monto=20000,
                       motivo="Efectivo para vuelto", fecha=datetime(2001, 2, 3, 8, 30)),
        MovimientoCaja(usuario_id=usuario.id, tipo="EGRESO", monto=5000,
                       motivo="Bencina", fecha=datetime(2001, 2, 3, 12, 0)),
    ])
    db.flush()

    assert caja.resumen(db, DIA) == {
        "agregado": 20000, "ingresos": 30000, "egresos": 5000, "balance": 45000,
    }
    # Un día sin nada no es un error: es una caja que todavía no abre.
    assert caja.resumen(db, AYER)["balance"] == 0


def test_anular_deja_las_cifras_como_si_el_movimiento_no_existiera(db):
    """Corregir no borra: se inserta la inversa. Pero el par anulado no puede
    seguir moviendo el balance, ni aparecer como plata que entró y salió."""
    usuario = _usuario(db)
    gasto = MovimientoCaja(usuario_id=usuario.id, tipo="EGRESO", monto=9000,
                           motivo="Tecleado de más", fecha=datetime(2001, 2, 3, 9, 0))
    db.add(gasto)
    db.flush()
    assert caja.resumen(db, DIA)["egresos"] == 9000

    caja.anular(db, gasto.id, usuario.id)
    db.flush()

    assert caja.resumen(db, DIA) == {
        "agregado": 0, "ingresos": 0, "egresos": 0, "balance": 0,
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

    assert caja.resumen(db, DIA)["ingresos"] == 12500
    assert caja.resumen(db, AYER)["ingresos"] == 0


def test_la_base_fecha_las_cosas_en_la_hora_del_taller(db):
    """Regresión: el servidor pone la hora con CURRENT_TIMESTAMP, y corriendo en
    UTC fechaba una venta de las nueve de la noche al día siguiente. Esa venta
    se caía del cierre de caja y del reporte de hoy, y el cajón no cuadraba sin
    que nada en pantalla lo explicara."""
    from sqlalchemy import text

    assert db.scalar(text("SELECT CURRENT_TIMESTAMP")).date() == date.today()
