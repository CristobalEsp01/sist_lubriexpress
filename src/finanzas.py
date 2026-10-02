"""Cuentas por cobrar y por pagar: lo que no puede vivir en un trigger.

La cuenta la abre la base al guardar una orden con folio de Mercado Público.
Acá está lo que hace una persona después: registrar la factura, que es cuando
el neto, el IVA y el costo se congelan, o ingresar a mano una cuenta anterior
al módulo. Sin Qt: se prueba sin ventana.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .models import (
    CuentaPorCobrar, FacturaProveedor, Orden, PagoCobro, PagoProveedor, Proveedor,
)
from .precios import clp, iva_de
from .rut import es_valido, formatear

# Los organismos públicos pagan a 30 días casi todos; pasado el día 30 desde la
# factura, la cuenta es morosa. Los proveedores, en cambio, dan su propio plazo
# y la mora se mide contra el vencimiento de cada factura.
PLAZO_COBRO_DIAS = 30


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


# --- por cobrar: lo que se muestra y se suma ---------------------------------

@dataclass(frozen=True)
class FilaCobro:
    """Una cuenta por cobrar como la lee la pantalla."""

    id: int
    orden_id: int | None
    cliente: str
    numero_oc: str
    numero_factura: str
    fecha_factura: date | None
    estado: str
    neto: int
    iva: int
    monto: int          # neto + IVA; estimado mientras la cuenta espera factura
    pagado: int
    saldo: int | None   # None mientras no haya factura
    costo: int | None
    margen: int | None
    dias_mora: int
    estimado: bool      # las cifras salen de la orden y aún no están facturadas


def dias_de_mora_cobro(fecha_factura: date | None, hoy: date) -> int:
    """Días pasados del plazo de 30 días desde la factura; 0 si aún está a tiempo."""
    if fecha_factura is None:
        return 0
    return max(0, (hoy - fecha_factura).days - PLAZO_COBRO_DIAS)


def _fila_cobro(cuenta: CuentaPorCobrar, hoy: date) -> FilaCobro:
    orden = cuenta.orden
    if cuenta.estado == "PENDIENTE_FACTURA":
        neto = neto_de_orden(orden)
        costo = costo_de_orden(orden)
        iva = iva_de(neto)
        margen = None if costo is None else neto - int(costo)
        estimado = True
    else:
        neto = int(cuenta.venta_neto or 0)
        iva = int(cuenta.iva or 0)
        costo = cuenta.costo
        margen = cuenta.margen
        estimado = False
    nombre = cuenta.cliente_nombre or (orden.cliente.nombre_completo if orden else "")
    mora = dias_de_mora_cobro(cuenta.fecha_factura, hoy) if cuenta.estado == "POR_COBRAR" else 0
    return FilaCobro(
        id=cuenta.id, orden_id=cuenta.orden_id, cliente=nombre,
        numero_oc=cuenta.numero_oc or "", numero_factura=cuenta.numero_factura or "",
        fecha_factura=cuenta.fecha_factura, estado=cuenta.estado, neto=neto, iva=iva,
        monto=neto + iva, pagado=cuenta.pagado, saldo=cuenta.saldo,
        costo=None if costo is None else int(costo), margen=margen, dias_mora=mora,
        estimado=estimado,
    )


def cuentas_por_cobrar(db, hoy: date | None = None) -> list[FilaCobro]:
    """Todas las cuentas, las más antiguas primero; la pantalla filtra por estado.

    La de una orden que sigue en el taller no aparece: se factura una vez
    entregada, y hasta entonces su monto todavía puede cambiar.
    """
    hoy = hoy or date.today()
    cuentas = db.scalars(
        select(CuentaPorCobrar)
        .options(selectinload(CuentaPorCobrar.pagos),
                 selectinload(CuentaPorCobrar.orden).selectinload(Orden.detalles),
                 selectinload(CuentaPorCobrar.orden).selectinload(Orden.cliente))
        .order_by(CuentaPorCobrar.id)
    ).all()
    return [_fila_cobro(cuenta, hoy) for cuenta in cuentas
            if cuenta.estado != "PENDIENTE_FACTURA" or cuenta.orden.estado == "ENTREGADA"]


def resumen_por_cobrar(filas: list[FilaCobro], hoy: date | None = None) -> dict[str, int]:
    """Las cifras de arriba del listado.

    `margen_mes` suma el margen de lo facturado en el mes de `hoy`; lo facturado
    sin costo conocido no entra y se cuenta aparte, para no pasar por margen lo
    que es un dato faltante.
    """
    hoy = hoy or date.today()
    por_cobrar = [f for f in filas if f.estado == "POR_COBRAR"]
    morosas = [f for f in por_cobrar if f.dias_mora > 0]
    sin_factura = [f for f in filas if f.estado == "PENDIENTE_FACTURA"]
    del_mes = [f for f in filas if f.estado in ("POR_COBRAR", "PAGADA")
               and f.fecha_factura and (f.fecha_factura.year, f.fecha_factura.month) == (hoy.year, hoy.month)]
    return {
        "por_cobrar": sum(f.saldo for f in por_cobrar),
        "moroso": sum(f.saldo for f in morosas),
        "morosas": len(morosas),
        "sin_factura": len(sin_factura),
        "sin_factura_monto": sum(f.monto for f in sin_factura),
        "margen_mes": sum(f.margen for f in del_mes if f.margen is not None),
        "margen_mes_sin_dato": sum(1 for f in del_mes if f.margen is None),
    }


def registrar_pago_cobro(db, cuenta: CuentaPorCobrar, monto: int, fecha_pago: date,
                         usuario_id: int) -> None:
    """Un abono. Nunca más que el saldo: se cobra la factura, no se regala plata."""
    if cuenta.estado != "POR_COBRAR":
        raise ValueError(f"Esta cuenta no admite pagos: está {cuenta.estado}.")
    if monto <= 0:
        raise ValueError("El abono tiene que ser mayor que cero.")
    if monto > cuenta.saldo:
        raise ValueError(f"El abono supera el saldo de {clp(cuenta.saldo)}.")
    db.add(PagoCobro(cuenta_id=cuenta.id, usuario_id=usuario_id, monto=monto,
                     fecha_pago=fecha_pago))
    db.flush()
    db.refresh(cuenta)      # el trigger pudo pasarla a PAGADA


def anular_cuenta_manual(db, cuenta: CuentaPorCobrar) -> None:
    """Deshace una cuenta ingresada a mano por error, mientras nadie haya pagado.

    Las que vienen de una orden no se anulan acá: deshacer una factura ya
    emitida es una nota de crédito, y lo decide una persona.
    """
    if cuenta.orden_id is not None:
        raise ValueError("Esta cuenta viene de una orden: se anula anulando la orden.")
    if cuenta.estado != "POR_COBRAR" or cuenta.pagos:
        raise ValueError("Solo se anula una cuenta sin pagos.")
    cuenta.estado = "ANULADA"
    db.flush()


# --- por pagar ------------------------------------------------------------------

@dataclass(frozen=True)
class FilaPagar:
    id: int
    proveedor_id: int
    proveedor: str
    numero_factura: str
    fecha_compra: date
    fecha_vencimiento: date
    monto: int
    pagado: int
    saldo: int
    estado: str
    dias_mora: int


def crear_proveedor(db, nombre: str, rut: str | None = None,
                    plazo_credito_dias: int = 30) -> Proveedor:
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("Falta el nombre del proveedor.")
    rut = (rut or "").strip()
    if rut and not es_valido(rut):
        raise ValueError("El RUT no es válido: el dígito verificador no corresponde.")
    if plazo_credito_dias < 0:
        raise ValueError("El plazo no puede ser negativo.")
    proveedor = Proveedor(nombre=nombre, rut=formatear(rut) or None,
                          plazo_credito_dias=plazo_credito_dias)
    db.add(proveedor)
    db.flush()
    return proveedor


def registrar_factura_proveedor(db, proveedor: Proveedor, numero_factura: str,
                                fecha_compra: date, monto: int, usuario_id: int,
                                fecha_vencimiento: date | None = None,
                                observaciones: str | None = None) -> FacturaProveedor:
    """Una cuenta por pagar. Sin vencimiento explícito, el plazo del proveedor lo propone."""
    numero = (numero_factura or "").strip()
    if not numero:
        raise ValueError("Falta el número de factura.")
    if monto <= 0:
        raise ValueError("El monto tiene que ser mayor que cero.")
    vence = fecha_vencimiento or fecha_compra + timedelta(days=proveedor.plazo_credito_dias)
    if vence < fecha_compra:
        raise ValueError("El vencimiento no puede ser anterior a la compra.")
    factura = FacturaProveedor(
        proveedor_id=proveedor.id, usuario_id=usuario_id, numero_factura=numero,
        fecha_compra=fecha_compra, fecha_vencimiento=vence, monto=monto,
        observaciones=(observaciones or "").strip() or None,
    )
    db.add(factura)
    db.flush()
    return factura


def _fila_pagar(factura: FacturaProveedor, hoy: date) -> FilaPagar:
    mora = max(0, (hoy - factura.fecha_vencimiento).days) if factura.estado == "PENDIENTE" else 0
    return FilaPagar(
        id=factura.id, proveedor_id=factura.proveedor_id, proveedor=factura.proveedor.nombre,
        numero_factura=factura.numero_factura, fecha_compra=factura.fecha_compra,
        fecha_vencimiento=factura.fecha_vencimiento, monto=int(factura.monto),
        pagado=factura.pagado, saldo=factura.saldo, estado=factura.estado, dias_mora=mora,
    )


def facturas_por_pagar(db, hoy: date | None = None) -> list[FilaPagar]:
    hoy = hoy or date.today()
    facturas = db.scalars(
        select(FacturaProveedor)
        .options(selectinload(FacturaProveedor.pagos), selectinload(FacturaProveedor.proveedor))
        .order_by(FacturaProveedor.fecha_vencimiento, FacturaProveedor.id)
    ).all()
    return [_fila_pagar(f, hoy) for f in facturas]


def resumen_por_pagar(filas: list[FilaPagar]) -> dict[str, int]:
    pendientes = [f for f in filas if f.estado == "PENDIENTE"]
    vencidas = [f for f in pendientes if f.dias_mora > 0]
    return {
        "por_pagar": sum(f.saldo for f in pendientes),
        "vencido": sum(f.saldo for f in vencidas),
        "vencidas": len(vencidas),
    }


def registrar_pago_proveedor(db, factura: FacturaProveedor, monto: int, fecha_pago: date,
                             usuario_id: int) -> None:
    if factura.estado != "PENDIENTE":
        raise ValueError(f"Esta factura no admite pagos: está {factura.estado}.")
    if monto <= 0:
        raise ValueError("El pago tiene que ser mayor que cero.")
    if monto > factura.saldo:
        raise ValueError(f"El pago supera el saldo de {clp(factura.saldo)}.")
    db.add(PagoProveedor(factura_id=factura.id, usuario_id=usuario_id, monto=monto,
                         fecha_pago=fecha_pago))
    db.flush()
    db.refresh(factura)


def anular_factura_proveedor(db, factura: FacturaProveedor) -> None:
    """Para una factura mal ingresada, mientras no se haya pagado nada."""
    if factura.estado != "PENDIENTE" or factura.pagos:
        raise ValueError("Solo se anula una factura pendiente y sin pagos.")
    factura.estado = "ANULADA"
    db.flush()
