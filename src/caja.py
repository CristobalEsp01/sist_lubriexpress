"""La caja chica del día: cuánta plata debería haber en el cajón de la oficina.

El día de una caja es su fecha. No hay tabla de cajas ni estado abierta/cerrada,
así que la caja abre y cierra sola y nadie puede dejarla abierta un viernes.

Acá solo viven las dos cosas que no están registradas en ninguna otra parte: el
efectivo que se deja en la mañana para dar vuelto y los gastos del día. Lo que
entra por una venta o por el abono de una orden **no se copia**: se suma de
`ventas` y `pagos_orden`, que ya lo tienen. Dos registros del mismo dinero es la
forma más segura de terminar con dos cifras que no cuadran.

Sin Qt a propósito: las cifras se prueban sin abrir una ventana.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import and_, func, select

from .models import MovimientoCaja, PagoOrden, Usuario, Venta


@dataclass(frozen=True)
class Fila:
    """Una línea del libro del día, como la muestra la pantalla."""

    id: int
    hora: datetime
    tipo: str
    motivo: str
    monto: int
    usuario: str
    anulado: bool


def _anulados():
    return select(MovimientoCaja.anula_id).where(MovimientoCaja.anula_id.isnot(None))


def _vigente():
    """Ni una anulación ni el movimiento que anula cuentan para las cifras. El
    par sigue en la tabla —nada se borra— pero deja de mover el balance, y
    tampoco se ve como plata que entró y salió el mismo día."""
    return and_(MovimientoCaja.anula_id.is_(None), MovimientoCaja.id.not_in(_anulados()))


def _suma(db, consulta) -> int:
    return int(db.scalar(consulta) or 0)


def _del_dia(columna, dia: date):
    return func.date(columna) == dia


def resumen(db, dia: date) -> dict[str, int]:
    """agregado + ingresos − egresos = balance, la aritmética del mesón."""
    def a_mano(tipo: str) -> int:
        return _suma(db, select(func.sum(MovimientoCaja.monto)).where(
            _del_dia(MovimientoCaja.fecha, dia), MovimientoCaja.tipo == tipo, _vigente()))

    agregado, egresos = a_mano("INGRESO"), a_mano("EGRESO")
    ingresos = (
        _suma(db, select(func.sum(Venta.total_final))
              .where(_del_dia(Venta.fecha_venta, dia)))
        + _suma(db, select(func.sum(PagoOrden.monto))
                .where(_del_dia(PagoOrden.fecha_pago, dia)))
    )
    return {"agregado": agregado, "ingresos": ingresos, "egresos": egresos,
            "balance": agregado + ingresos - egresos}


def balance_del_dia_anterior(db, dia: date, dias_atras: int = 7) -> int:
    """Con cuánto cerró el último día con movimiento antes de `dia`.

    Es lo que se propone al agregar dinero: la plata que quedó ayer en el cajón
    suele ser la que se deja hoy, y retipearla de memoria es la forma más fácil
    de descuadrar. Un lunes hay que mirar el viernes, así que no basta con el
    día anterior.

    ponytail: mira día por día hacia atrás hasta encontrar uno con saldo. Con
    una semana alcanza para fines de semana y feriados; si algún día hiciera
    falta más, la salida es una consulta sola por la última fecha con filas.
    """
    for atras in range(1, dias_atras + 1):
        anterior = dia - timedelta(days=atras)
        balance = resumen(db, anterior)["balance"]
        if balance:
            return balance
    return 0


def movimientos(db, dia: date) -> list[Fila]:
    """Lo que se movió a mano ese día, en orden. Las ventas no salen acá: se
    consultan en su propia pantalla y llenarían la lista todos los días."""
    anulados = {fila for fila in db.scalars(_anulados())}
    filas = db.execute(
        select(MovimientoCaja, Usuario.nombre)
        .join(Usuario, Usuario.id == MovimientoCaja.usuario_id)
        .where(_del_dia(MovimientoCaja.fecha, dia))
        .order_by(MovimientoCaja.fecha, MovimientoCaja.id)
    ).all()
    return [
        Fila(m.id, m.fecha, m.tipo, m.motivo, int(m.monto), usuario,
             m.id in anulados or m.anula_id is not None)
        for m, usuario in filas
    ]


def anular(db, movimiento_id: int, usuario_id: int) -> MovimientoCaja:
    """Corregir es insertar la inversa, no borrar: la caja es de solo agregado,
    igual que el Kardex y los abonos de una orden."""
    original = db.get(MovimientoCaja, movimiento_id)
    inversa = MovimientoCaja(
        usuario_id=usuario_id,
        tipo="EGRESO" if original.tipo == "INGRESO" else "INGRESO",
        monto=original.monto,
        motivo=f"Anula: {original.motivo}",
        fecha=original.fecha,
        anula_id=original.id,
    )
    db.add(inversa)
    return inversa
