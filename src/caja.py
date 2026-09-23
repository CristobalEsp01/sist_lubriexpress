"""La caja chica del día: apertura + entradas − salidas = lo que debería haber
en el cajón.

El día de una caja es su fecha: no hay estado abierta/cerrada. Acá solo se
guarda lo que no está en otra tabla (la apertura y lo agregado o sacado a mano);
ventas y pagos de órdenes se suman de sus tablas, sin copiarlos, y de ellos solo
el efectivo entra a la cuenta. Sin Qt: las cifras se prueban sin ventana.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import and_, func, select

from .models import MovimientoCaja, PagoOrden, Usuario, Venta

EFECTIVO = "EFECTIVO"
# Rótulos para pantalla y PDF. VENTA y ORDEN vienen de sus tablas.
NOMBRES = {"APERTURA": "Apertura", "INGRESO": "Ingreso", "EGRESO": "Egreso",
           "VENTA": "Venta", "ORDEN": "Orden"}


@dataclass(frozen=True)
class Fila:
    """Una línea del libro del día, como la muestra la pantalla."""

    id: int | None      # None: una venta o un pago de orden, que no se anulan acá
    hora: datetime
    tipo: str
    motivo: str
    monto: int
    usuario: str
    anulado: bool
    en_cajon: bool = True   # falso para lo pagado con tarjeta o transferencia


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


def _a_mano(db, dia: date, tipo: str) -> int:
    return _suma(db, select(func.sum(MovimientoCaja.monto)).where(
        _del_dia(MovimientoCaja.fecha, dia), MovimientoCaja.tipo == tipo, _vigente()))


def resumen(db, dia: date) -> dict[str, int]:
    """apertura + entradas − salidas = balance. Entradas: ventas y pagos en
    efectivo más lo agregado a mano. `otros_medios` (tarjeta y transferencia)
    se informa aparte."""
    def cobrado(efectivo: bool) -> int:
        def medio(columna):
            return columna == EFECTIVO if efectivo else columna != EFECTIVO
        return (
            _suma(db, select(func.sum(Venta.total_final))
                  .where(_del_dia(Venta.fecha_venta, dia), medio(Venta.medio_pago)))
            + _suma(db, select(func.sum(PagoOrden.monto))
                    .where(_del_dia(PagoOrden.fecha_pago, dia), medio(PagoOrden.medio_pago)))
        )

    apertura, salidas = _a_mano(db, dia, "APERTURA"), _a_mano(db, dia, "EGRESO")
    entradas = cobrado(True) + _a_mano(db, dia, "INGRESO")
    return {"apertura": apertura, "entradas": entradas, "salidas": salidas,
            "balance": apertura + entradas - salidas, "otros_medios": cobrado(False)}


def tiene_apertura(db, dia: date) -> bool:
    """Una apertura anulada no cuenta: se anula para registrarla de nuevo."""
    return bool(db.scalar(select(MovimientoCaja.id).where(
        _del_dia(MovimientoCaja.fecha, dia), MovimientoCaja.tipo == "APERTURA", _vigente(),
    ).limit(1)))


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


def _con_medio(texto: str, medio: str) -> str:
    return texto if medio == EFECTIVO else f"{texto} · {medio.capitalize()}"


def movimientos(db, dia: date) -> list[Fila]:
    """Todo el día en orden: lo anotado a mano, las ventas y los pagos de
    órdenes. Lo cobrado por otro medio va con `en_cajon` en falso."""
    anulados = {fila for fila in db.scalars(_anulados())}
    filas = [
        Fila(m.id, m.fecha, m.tipo, m.motivo, int(m.monto), usuario,
             m.id in anulados or m.anula_id is not None)
        for m, usuario in db.execute(
            select(MovimientoCaja, Usuario.nombre)
            .join(Usuario, Usuario.id == MovimientoCaja.usuario_id)
            .where(_del_dia(MovimientoCaja.fecha, dia))
        )
    ]
    filas += [
        Fila(None, v.fecha_venta, "VENTA",
             _con_medio(f"Boleta {v.numero_boleta}" if v.numero_boleta else f"Venta #{v.id}",
                        v.medio_pago),
             int(v.total_final), usuario, False, v.medio_pago == EFECTIVO)
        for v, usuario in db.execute(
            select(Venta, Usuario.nombre).join(Usuario, Usuario.id == Venta.usuario_id)
            .where(_del_dia(Venta.fecha_venta, dia))
        )
    ]
    filas += [
        Fila(None, p.fecha_pago, "ORDEN", _con_medio(f"OT #{p.orden_id}", p.medio_pago),
             int(p.monto), usuario, False, p.medio_pago == EFECTIVO)
        for p, usuario in db.execute(
            select(PagoOrden, Usuario.nombre).join(Usuario, Usuario.id == PagoOrden.usuario_id)
            .where(_del_dia(PagoOrden.fecha_pago, dia))
        )
    ]
    return sorted(filas, key=lambda f: (f.hora, f.id or 0))


def anular(db, movimiento_id: int, usuario_id: int) -> MovimientoCaja:
    """Corregir es insertar la inversa, no borrar: la caja es de solo agregado,
    igual que el Kardex y los abonos de una orden."""
    original = db.get(MovimientoCaja, movimiento_id)
    inversa = MovimientoCaja(
        usuario_id=usuario_id,
        tipo="INGRESO" if original.tipo == "EGRESO" else "EGRESO",
        monto=original.monto,
        motivo=f"Anula: {original.motivo}",
        fecha=original.fecha,
        anula_id=original.id,
    )
    db.add(inversa)
    return inversa
