"""Reportería (Propuesta 3.2, semana 3): ingresos por período, ventas por
producto, actividad por usuario y por mecánico, órdenes con descuento y
reabastecimiento. Sin Qt: cada función
devuelve filas listas para una tabla o para exportar.

Las cifras salen de lo guardado en los documentos (`total_final`,
`impuesto`); el neto es la resta. Las 3.021 órdenes migradas del sistema
antiguo no traen líneas, así que "por producto" empieza con el sistema nuevo.
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select, text

from . import convenios
from .models import (
    Cliente, DetalleOrden, DetalleVenta, Mecanico, Orden, Producto, Usuario, Vehiculo, Venta,
)

# Una orden anulada no se hizo: su stock volvió a la bodega y no puede seguir
# contándose como ingreso ni como producto vendido.
VIGENTE = Orden.estado != "ANULADA"


COLUMNAS_INGRESOS = ["Fecha", "Ventas", "Total ventas", "Órdenes", "Total órdenes", "Neto", "IVA",
                     "Ajuste", "Total"]
COLUMNAS_PRODUCTOS = ["Producto", "Marca", "Cantidad", "Monto neto", "% del total"]
COLUMNAS_USUARIOS = ["Usuario", "Ventas", "Total ventas", "Órdenes", "Total órdenes", "Total"]
COLUMNAS_MECANICOS = ["Mecánico", "Órdenes", "Total órdenes"]
# Las órdenes guardadas antes de que existiera el mecánico.
SIN_MECANICO = "Sin asignar"
COLUMNAS_DESCUENTOS = ["N° OT", "Fecha", "Cliente", "Patente", "Ingresó", "Tipo de descuento",
                       "Descuento", "Total"]
COLUMNAS_REABASTECIMIENTO = ["Producto", "Marca", "Categoría", "Stock", "Mínimo", "Faltante"]


def _rango(desde: date, hasta: date) -> tuple[datetime, datetime]:
    """[desde 00:00, hasta + 1 día) para que `hasta` entre completo."""
    return datetime.combine(desde, time.min), datetime.combine(hasta + timedelta(days=1), time.min)


def ingresos_por_periodo(db, desde: date, hasta: date) -> list[tuple]:
    """Una fila por día con documentos. Por mes si el rango pasa de 62 días."""
    ini, fin = _rango(desde, hasta)
    por_mes = (hasta - desde).days > 62
    clave = (lambda f: f.date().replace(day=1)) if por_mes else (lambda f: f.date())
    # n_ventas, $ventas, n_ordenes, $ordenes, iva, ajuste (el redondeo no es neto).
    dias = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    for fecha, total, impuesto, ajuste in db.execute(
        select(Venta.fecha_venta, Venta.total_final, Venta.impuesto, Venta.ajuste_redondeo)
        .where(Venta.fecha_venta >= ini, Venta.fecha_venta < fin)
    ):
        d = dias[clave(fecha)]
        d[0] += 1; d[1] += int(total); d[4] += int(impuesto); d[5] += int(ajuste)
    for fecha, total, impuesto, ajuste in db.execute(
        select(Orden.fecha_creacion, Orden.total_final, Orden.impuesto, Orden.ajuste_redondeo)
        .where(Orden.fecha_creacion >= ini, Orden.fecha_creacion < fin, VIGENTE)
    ):
        d = dias[clave(fecha)]
        d[2] += 1; d[3] += int(total); d[4] += int(impuesto); d[5] += int(ajuste)
    # La fecha viaja como `date`, no como texto: una columna de fechas ordenada
    # alfabéticamente pone el 01 de octubre antes del 02 de septiembre. Quien
    # muestra o exporta la formatea con `rotulo_de_fecha`.
    return [
        (dia, nv, tv, no, to, tv + to - iva - ajuste, iva, ajuste, tv + to)
        for dia, (nv, tv, no, to, iva, ajuste) in sorted(dias.items())
    ], por_mes


def rotulo_de_fecha(dia: date, por_mes: bool) -> str:
    return dia.strftime("%m-%Y" if por_mes else "%d-%m-%Y")


def ventas_por_producto(db, desde: date, hasta: date) -> list[tuple]:
    ini, fin = _rango(desde, hasta)
    acumulado = defaultdict(lambda: [0, 0])
    lineas = [
        select(Producto.nombre, Producto.marca, DetalleVenta.cantidad, DetalleVenta.precio_unitario_cobrado)
        .join(DetalleVenta.producto).join(DetalleVenta.venta)
        .where(Venta.fecha_venta >= ini, Venta.fecha_venta < fin),
        select(Producto.nombre, Producto.marca, DetalleOrden.cantidad, DetalleOrden.precio_unitario_cobrado)
        .join(DetalleOrden.producto).join(DetalleOrden.orden)
        .where(Orden.fecha_creacion >= ini, Orden.fecha_creacion < fin, VIGENTE),
    ]
    for consulta in lineas:
        for nombre, marca, cantidad, precio in db.execute(consulta):
            a = acumulado[(nombre, marca or "")]
            a[0] += cantidad; a[1] += int(cantidad * precio)
    total = sum(monto for _, monto in acumulado.values()) or 1
    return sorted(
        ((nombre, marca, cantidad, monto, round(100 * monto / total, 1))
         for (nombre, marca), (cantidad, monto) in acumulado.items()),
        key=lambda f: (-f[3], f[0]),
    )


def por_usuario(db, desde: date, hasta: date) -> list[tuple]:
    ini, fin = _rango(desde, hasta)
    acumulado = defaultdict(lambda: [0, 0, 0, 0])
    for nombre, n, total in db.execute(
        select(Usuario.nombre, func.count(Venta.id), func.coalesce(func.sum(Venta.total_final), 0))
        .join(Venta.usuario).where(Venta.fecha_venta >= ini, Venta.fecha_venta < fin).group_by(Usuario.nombre)
    ):
        acumulado[nombre][0] += n; acumulado[nombre][1] += int(total)
    for nombre, n, total in db.execute(
        select(Usuario.nombre, func.count(Orden.id), func.coalesce(func.sum(Orden.total_final), 0))
        .join(Orden.usuario)
        .where(Orden.fecha_creacion >= ini, Orden.fecha_creacion < fin, VIGENTE)
        .group_by(Usuario.nombre)
    ):
        acumulado[nombre][2] += n; acumulado[nombre][3] += int(total)
    return sorted(
        ((nombre, nv, tv, no, to, tv + to) for nombre, (nv, tv, no, to) in acumulado.items()),
        key=lambda f: (-f[5], f[0]),
    )


def por_mecanico(db, desde: date, hasta: date) -> list[tuple]:
    """Quién trabajó los autos: órdenes y su total. Las ventas de mostrador no
    tienen mecánico."""
    ini, fin = _rango(desde, hasta)
    filas = db.execute(
        select(Mecanico.nombre, func.count(Orden.id), func.coalesce(func.sum(Orden.total_final), 0))
        .select_from(Orden).outerjoin(Orden.mecanico)
        .where(Orden.fecha_creacion >= ini, Orden.fecha_creacion < fin, VIGENTE)
        .group_by(Mecanico.nombre)
    )
    return sorted(((nombre or SIN_MECANICO, n, int(total)) for nombre, n, total in filas),
                  key=lambda f: (-f[2], f[0]))


def descuentos(db, desde: date, hasta: date) -> list[tuple]:
    """Las órdenes que llevaron descuento, de cualquier tipo, y quién las
    ingresó. Solo las ventas de mostrador no entran: no tienen descuento."""
    ini, fin = _rango(desde, hasta)
    filas = []
    for orden, cliente, patente, usuario in db.execute(
        select(Orden, Cliente.nombre_completo, Vehiculo.patente, Usuario.nombre)
        .join(Orden.vehiculo).join(Vehiculo.cliente).join(Orden.usuario)
        .where(Orden.fecha_creacion >= ini, Orden.fecha_creacion < fin, VIGENTE,
               (Orden.descuento_monto > 0) | (Orden.descuento_porcentaje > 0))
        .order_by(Orden.id)
    ):
        if orden.convenio:
            tipo = convenios.rotulo(orden.convenio, orden.folio_flyer)
        elif orden.descuento_porcentaje:
            tipo = f"General ({int(orden.descuento_porcentaje)} %)"
        else:
            tipo = "General (monto)"
        filas.append((orden.id, orden.fecha_creacion.date(), cliente, patente, usuario, tipo,
                      orden.descuento_aplicado, int(orden.total_final)))
    return filas


def reabastecimiento(db) -> list[tuple]:
    """La vista `vw_stock_critico`, ordenada por lo que falta para el mínimo.

    Solo lo que tiene mínimo: con el 0 que trae todo lo migrado, cualquier
    producto agotado entraba a la lista sin que faltara nada que comprar.
    """
    return [
        (nombre, marca or "", categoria or "", stock, minimo, minimo - stock)
        for nombre, marca, categoria, stock, minimo in db.execute(text(
            'SELECT "nombre", "marca", "categoria", "stock_actual", "stock_minimo" FROM "vw_stock_critico" '
            'WHERE "stock_minimo" > 0 '
            'ORDER BY ("stock_minimo" - "stock_actual") DESC, "nombre"'
        ))
    ]


def productos_sin_minimo(db) -> int:
    """Los activos que el reabastecimiento no puede vigilar."""
    return db.scalar(select(func.count(Producto.id))
                     .where(Producto.activo, Producto.stock_minimo == 0))
