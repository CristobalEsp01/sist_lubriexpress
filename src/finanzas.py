"""Cuentas por cobrar: lo que no puede vivir en un trigger.

La cuenta la abre la base al guardar una orden con folio de Mercado Público.
Acá está lo que hace una persona después: registrar la factura, que es cuando
el neto, el IVA y el costo se congelan, o ingresar a mano una cuenta anterior
al módulo. Sin Qt: se prueba sin ventana.
"""
from datetime import date
from decimal import Decimal

from .models import CuentaPorCobrar, Orden
from .precios import iva_de


def neto_de_orden(orden: Orden) -> int:
    """Lo que la orden vendió sin IVA y con el descuento ya aplicado.

    Se obtiene restando lo cobrado de más, igual que el esquema lo dice para
    las ventas: total_final = neto + impuesto + ajuste. Así coincide con lo que
    la orden realmente calculó, sin volver a aplicar el descuento acá.
    """
    return int(orden.total_final - orden.impuesto - orden.ajuste_redondeo)


def costo_de_orden(orden: Orden) -> Decimal | None:
    """La suma de lo que costaron sus productos cuando se vendieron.

    Los servicios no cuestan bodega y no suman. Si a alguna línea de producto
    le falta el costo (lo guardado antes de que existiera), el costo total es
    desconocido y devuelve None: un margen "sin dato" es más honesto que uno
    inflado por un costo que faltó.
    """
    total = Decimal(0)
    for linea in orden.detalles:
        if linea.producto_id is None:
            continue
        if linea.costo_unitario is None:
            return None
        total += linea.cantidad * linea.costo_unitario
    return total


def registrar_factura(db, cuenta: CuentaPorCobrar, numero_factura: str,
                      fecha_factura: date, usuario_id: int) -> None:
    """Anota la factura de una cuenta que espera una y congela sus cifras.

    Desde acá la cuenta ya no lee la orden: si se edita después, lo facturado
    no se mueve. No confirma la transacción; eso lo decide quien llama.
    """
    numero = (numero_factura or "").strip()
    if not numero:
        raise ValueError("Falta el número de factura.")
    if cuenta.estado != "PENDIENTE_FACTURA":
        raise ValueError(f"Esta cuenta ya no espera factura: está {cuenta.estado}.")
    orden = cuenta.orden
    if orden.estado != "ENTREGADA":
        raise ValueError("La orden sigue abierta: se factura una vez entregada.")

    neto = neto_de_orden(orden)
    cuenta.numero_factura = numero
    cuenta.fecha_factura = fecha_factura
    cuenta.venta_neto = neto
    cuenta.iva = iva_de(neto)
    cuenta.costo = costo_de_orden(orden)
    cuenta.usuario_id = usuario_id
    cuenta.estado = "POR_COBRAR"
    db.flush()


def crear_cuenta_manual(db, *, cliente_nombre: str, numero_factura: str,
                        fecha_factura: date, venta_neto: int, usuario_id: int,
                        numero_oc: str | None = None, costo: int | None = None,
                        observaciones: str | None = None) -> CuentaPorCobrar:
    """Una cuenta sin orden detrás: las deudas anteriores al módulo.

    Nace facturada, porque para ingresarla ya hay factura. El costo es opcional;
    sin él, el margen queda "sin dato".
    """
    cliente = (cliente_nombre or "").strip()
    numero = (numero_factura or "").strip()
    if not cliente:
        raise ValueError("Falta el cliente.")
    if not numero:
        raise ValueError("Falta el número de factura.")
    if venta_neto < 0 or (costo is not None and costo < 0):
        raise ValueError("Los montos no pueden ser negativos.")

    cuenta = CuentaPorCobrar(
        cliente_nombre=cliente, numero_oc=(numero_oc or "").strip() or None,
        numero_factura=numero, fecha_factura=fecha_factura,
        venta_neto=venta_neto, iva=iva_de(venta_neto), costo=costo,
        observaciones=(observaciones or "").strip() or None,
        usuario_id=usuario_id, estado="POR_COBRAR",
    )
    db.add(cuenta)
    db.flush()
    return cuenta
