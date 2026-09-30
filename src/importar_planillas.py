"""Importar las planillas de Excel del taller a Finanzas (PRUEBA).

Dos planillas, una hoja por año: *Facturas por cobrar Mercado Público* y
*Proveedores por pagar*. Estaban armadas a mano, así que acá se lee lo que se
puede y lo que no se descarta **con su motivo**: nada desaparece en silencio.

Tres pasos separados, para poder mirar antes de escribir:

1. `leer_*` convierte la hoja en filas limpias y anota lo omitido y los avisos.
2. `planificar_*` mira la base y separa lo nuevo de lo que ya está.
3. `aplicar_*` escribe con las mismas funciones de `finanzas.py` que usa la
   pantalla, así que valen las mismas reglas (y los triggers).

Todo lo importado lleva `MARCA` en observaciones; con eso `deshacer` lo puede
sacar. Sin Qt ni consola: se prueba sin ventana.
"""
import re
import secrets
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select

from . import finanzas
from .auth import hash_password
from .models import (
    CuentaPorCobrar, FacturaProveedor, PagoCobro, PagoProveedor, Proveedor, Usuario,
)
from .precios import iva_de
from .xlsx import leer_hojas

MARCA = "Importada de planilla"
USUARIO_IMPORTACION = "importacion_planillas"
PLAZO_POR_DEFECTO = 30
MAX_FILAS_SIN_FACTURA = 5


@dataclass(frozen=True)
class Omitida:
    hoja: str
    fila: int
    motivo: str
    detalle: str = ""


@dataclass
class Lectura:
    """Lo que salió de una planilla: filas útiles, lo descartado y los avisos."""

    items: list = field(default_factory=list)
    omitidas: list[Omitida] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    duplicadas: int = 0


@dataclass(frozen=True)
class CuentaLeida:
    hoja: str
    fila: int
    oc: str | None
    cliente: str
    factura: str
    fecha_factura: date
    costo: int | None
    neto: int
    fecha_pago: date | None
    monto_planilla: float | None

    @property
    def total(self) -> int:
        return self.neto + iva_de(self.neto)


@dataclass(frozen=True)
class FacturaLeida:
    hoja: str
    fila: int
    proveedor_planilla: str
    proveedor: str          # el nombre unificado
    numero: str
    compra: date
    vence: date
    monto: int
    pagos: tuple[tuple[int, date], ...]
    observaciones: str | None


# --- celdas -------------------------------------------------------------------

def texto(valor) -> str | None:
    limpio = re.sub(r"\s+", " ", valor or "").strip()
    return limpio or None


def numero(valor) -> float | None:
    """'8319.2999999999993' -> 8319.3; el texto, los errores de Excel ('#DIV/0!') y
    lo vacío no son números."""
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def entero(valor) -> int | None:
    n = numero(valor)
    return None if n is None else int(round(n))


def fecha(valor) -> date | None:
    """Excel cuenta días desde el 30-12-1899."""
    n = numero(valor)
    if n is None or n < 1:
        return None
    return (datetime(1899, 12, 30) + timedelta(days=n)).date()


def numero_de_factura(valor) -> str | None:
    """'167' o '167.0' -> '167'; un texto como '232 (218)' se deja como está."""
    n = numero(valor)
    if n is not None:
        return str(int(n)) if n == int(n) else str(n)
    return texto(valor)


def _encabezados(filas, buscada: str) -> tuple[int, dict[str, int]] | None:
    """La fila de títulos (la que trae `buscada`) y la columna de cada uno."""
    for numero_fila, celdas in filas[:12]:
        nombres = {c: texto(v).upper() for c, v in celdas.items() if texto(v)}
        if buscada in nombres.values():
            columnas: dict[str, int] = {}
            for c in sorted(nombres):
                nombre = nombres[c]
                if nombre == "FECHA":
                    # La segunda FECHA (o la que sigue a FACTURA) es la de la factura.
                    nombre = "FECHA_FACTURA" if "FACTURA" in columnas else "FECHA_OC"
                columnas.setdefault(nombre, c)
            return numero_fila, columnas
    return None


# --- por cobrar ---------------------------------------------------------------

def leer_por_cobrar(ruta) -> Lectura:
    """Una cuenta por cada fila con cliente, factura, neto y fecha de factura.

    Las órdenes que aún no tienen factura no se importan: una cuenta sin orden
    en el sistema exige factura (así lo protege la base), y su fila sigue en la
    planilla para cuando se emita.
    """
    lectura = Lectura()
    for hoja, filas in leer_hojas(ruta).items():
        cabecera = _encabezados(filas, "CLIENTE")
        if cabecera is None:
            lectura.avisos.append(f"Hoja {hoja}: no se encontró la fila de títulos con CLIENTE.")
            continue
        primera, col = cabecera
        faltan = [n for n in ("FACTURA", "FECHA_FACTURA", "VENTA NETO") if n not in col]
        if faltan:
            lectura.avisos.append(f"Hoja {hoja}: faltan las columnas {', '.join(faltan)}.")
            continue
        for fila, celdas in filas:
            if fila <= primera:
                continue
            def dato(nombre):
                return celdas.get(col[nombre]) if nombre in col else None
            cliente = texto(dato("CLIENTE"))
            if cliente is None:
                continue        # totales y filas sueltas de más abajo
            neto = entero(dato("VENTA NETO"))
            factura = numero_de_factura(dato("FACTURA"))
            emitida = fecha(dato("FECHA_FACTURA"))
            if factura is None:
                lectura.omitidas.append(Omitida(
                    hoja, fila, "sin factura" if neto else "sin datos", cliente))
                continue
            if not neto or neto <= 0:
                lectura.omitidas.append(Omitida(hoja, fila, "sin neto", f"{cliente} · factura {factura}"))
                continue
            if emitida is None:
                lectura.omitidas.append(Omitida(
                    hoja, fila, "sin fecha de factura", f"{cliente} · factura {factura}"))
                continue
            monto = numero(dato("MONTO"))
            leida = CuentaLeida(
                hoja=hoja, fila=fila, oc=texto(dato("OC")), cliente=cliente, factura=factura,
                fecha_factura=emitida, costo=entero(dato("COSTO")), neto=neto,
                fecha_pago=fecha(dato("FECHA PAGO")), monto_planilla=monto,
            )
            if monto is not None and abs(monto - leida.total) > 2:
                lectura.avisos.append(
                    f"{hoja} fila {fila}: el MONTO de la planilla ({monto:,.0f}) no calza con "
                    f"neto + IVA ({leida.total:,}). Se usa el calculado.".replace(",", "."))
            if leida.fecha_pago and leida.fecha_pago < emitida:
                lectura.avisos.append(
                    f"{hoja} fila {fila}: factura {factura} figura pagada antes de emitirse.")
            lectura.items.append(leida)

    repetidas = Counter(c.factura for c in lectura.items)
    vistas: set[str] = set()
    unicas = []
    for cuenta in lectura.items:
        if repetidas[cuenta.factura] > 1 and cuenta.factura in vistas:
            lectura.duplicadas += 1
            lectura.omitidas.append(Omitida(
                cuenta.hoja, cuenta.fila, "factura repetida", f"{cuenta.cliente} · factura {cuenta.factura}"))
            continue
        vistas.add(cuenta.factura)
        unicas.append(cuenta)
    lectura.items = unicas
    return lectura


# --- por pagar ----------------------------------------------------------------

# Palabras que no distinguen a un proveedor de otro: formas legales y de escritura.
_RUIDO = {"spa", "ltda", "limitada", "sa", "s", "a", "e", "y", "de", "del", "la", "chile", "com",
          "comercial", "dist", "distribuidora", "representaciones", "reprentaciones", "rep",
          "empresa", "nacional", "energia", "soc", "servicio"}
# Lo que la regla no junta sola (marcas escritas como nombre, faltas de ortografía).
ALIAS = {
    "comecial wepro": "wepro",
    "gallardo": "gallardo higueras",
    "lub": "lubchile",
    "lubrisur": "lubricantes sur",
    "ricardo ovalle": "neumaticos ricardo ovalle",
}


def clave_de_proveedor(nombre: str) -> str:
    """'Enex S.A. (Shell)' y 'Empresa Nacional de Energía Enex S.A.' -> 'enex'."""
    sin_marca = re.sub(r"\([^)]*\)", " ", nombre)
    sin_tildes = "".join(c for c in unicodedata.normalize("NFKD", sin_marca)
                         if not unicodedata.combining(c)).lower()
    palabras = [p for p in re.sub(r"[^a-z0-9 ]", " ", sin_tildes).split() if p not in _RUIDO]
    clave = " ".join(palabras)
    return ALIAS.get(clave, clave)


def _sin_marca(nombre: str) -> str:
    return texto(re.sub(r"\([^)]*\)", " ", nombre)) or nombre


def unificar_proveedores(nombres: list[str]) -> dict[str, str]:
    """{nombre en la planilla: nombre único}, con el nombre más usado de cada grupo."""
    grupos: dict[str, Counter] = defaultdict(Counter)
    for nombre in nombres:
        grupos[clave_de_proveedor(nombre)][_sin_marca(nombre)] += 1
    elegido = {clave: max(variantes.items(), key=lambda kv: (kv[1], len(kv[0])))[0]
               for clave, variantes in grupos.items()}
    return {nombre: elegido[clave_de_proveedor(nombre)] for nombre in nombres}


def _pagos_de(estado: str | None, monto: int, abono: int | None, pago: date | None,
              aviso) -> tuple[tuple[int, date], ...]:
    """Qué se pagó, según el ESTADO que la planilla escribió a mano."""
    if estado == "pagado":
        if pago is None:
            aviso("figura pagada sin fecha de pago: queda pendiente")
            return ()
        if abono and abono < monto:
            aviso(f"figura pagada pero con abono menor ({abono:,} de {monto:,}): se toma como "
                  "pagada completa".replace(",", "."))
        return ((monto, pago),)
    if estado == "abono":
        if not abono or pago is None:
            aviso("figura con abono sin monto o sin fecha: queda pendiente")
            return ()
        return ((min(abono, monto), pago),)
    if estado is None:
        if pago is not None:
            aviso("tiene fecha de pago pero ningún estado: queda pendiente")
        return ()
    aviso(f"estado «{estado}» desconocido: queda pendiente")
    return ()


def leer_por_pagar(ruta) -> Lectura:
    """Una factura por cada (proveedor, número), con sus pagos."""
    lectura = Lectura()
    crudas = []
    for hoja, filas in leer_hojas(ruta).items():
        cabecera = _encabezados(filas, "PROVEEDOR")
        if cabecera is None:
            lectura.avisos.append(f"Hoja {hoja}: no se encontró la fila de títulos con PROVEEDOR.")
            continue
        primera, col = cabecera
        faltan = [n for n in ("FACTURA", "MONTO", "FECHA COMPRA") if n not in col]
        if faltan:
            lectura.avisos.append(f"Hoja {hoja}: faltan las columnas {', '.join(faltan)}.")
            continue
        for fila, celdas in filas:
            if fila <= primera:
                continue
            def dato(nombre):
                return celdas.get(col[nombre]) if nombre in col else None
            proveedor, factura = texto(dato("PROVEEDOR")), numero_de_factura(dato("FACTURA"))
            monto = entero(dato("MONTO"))
            if proveedor is None and factura is None:
                if monto:
                    lectura.omitidas.append(Omitida(
                        hoja, fila, "sin proveedor ni factura",
                        f"monto {monto:,} · probablemente la cuota de otra factura".replace(",", ".")))
                continue
            estado = (texto(dato("ESTADO")) or "").lower() or None
            detalle = f"{proveedor or '?'} · factura {factura or '?'}"
            if estado and estado.startswith("nota de cr"):
                lectura.omitidas.append(Omitida(hoja, fila, "nota de crédito", detalle))
                continue
            if proveedor is None or factura is None:
                lectura.omitidas.append(Omitida(hoja, fila, "sin proveedor o sin número de factura", detalle))
                continue
            compra = fecha(dato("FECHA COMPRA"))
            if not monto or monto <= 0 or compra is None:
                lectura.omitidas.append(Omitida(hoja, fila, "sin monto o sin fecha de compra", detalle))
                continue
            crudas.append((hoja, fila, proveedor, factura, compra, fecha(dato("FECHA CREDITO")),
                           monto, entero(dato("ABONO")), fecha(dato("FECHA PAGO")), estado,
                           texto(dato("OBSERVACIONES"))))

    nombres = unificar_proveedores([c[2] for c in crudas])
    vistas: dict[tuple[str, str], FacturaLeida] = {}
    for hoja, fila, proveedor, factura, compra, vence, monto, abono, pago, estado, obs in crudas:
        unico = nombres[proveedor]
        clave = (clave_de_proveedor(proveedor), factura)
        detalle = f"{unico} · factura {factura}"
        if clave in vistas:
            previa = vistas[clave]
            if previa.monto == monto:
                lectura.duplicadas += 1
            else:
                lectura.omitidas.append(Omitida(
                    hoja, fila, "misma factura con otro monto",
                    f"{detalle}: {previa.monto:,} en {previa.hoja} fila {previa.fila}, "
                    f"{monto:,} acá. Se dejó la primera.".replace(",", ".")))
            continue

        def aviso(mensaje, hoja=hoja, fila=fila, detalle=detalle):
            lectura.avisos.append(f"{hoja} fila {fila} ({detalle}): {mensaje}")

        if vence is None:
            vence = compra + timedelta(days=PLAZO_POR_DEFECTO)
            aviso(f"sin fecha de crédito: se calculó a {PLAZO_POR_DEFECTO} días")
        elif vence < compra:
            aviso("el crédito vence antes de la compra: se dejó igual a la compra")
            vence = compra
        pagos = _pagos_de(estado, monto, abono, pago, aviso)
        if pagos and pagos[0][1] < compra:
            aviso("pagada antes de la fecha de compra (¿año mal escrito?): se importó igual")
        notas = [obs] if obs else []
        if proveedor != unico:
            notas.append(f"Nombre en la planilla: {proveedor}")
        leida = FacturaLeida(
            hoja=hoja, fila=fila, proveedor_planilla=proveedor, proveedor=unico, numero=factura,
            compra=compra, vence=vence, monto=monto, pagos=pagos,
            observaciones=" · ".join(notas) or None,
        )
        vistas[clave] = leida
        lectura.items.append(leida)
    return lectura


# --- contra la base -----------------------------------------------------------

@dataclass
class Plan:
    nuevas: list = field(default_factory=list)
    existentes: list = field(default_factory=list)


def planificar_por_cobrar(db, lectura: Lectura) -> Plan:
    """Lo que ya está en la base (mismo número de factura) no se vuelve a crear."""
    hay = set(db.scalars(select(CuentaPorCobrar.numero_factura)
                         .where(CuentaPorCobrar.numero_factura.is_not(None),
                                CuentaPorCobrar.estado != "ANULADA")))
    plan = Plan()
    for cuenta in lectura.items:
        (plan.existentes if cuenta.factura in hay else plan.nuevas).append(cuenta)
    return plan


def planificar_por_pagar(db, lectura: Lectura) -> Plan:
    proveedores = {p.nombre.lower(): p.id for p in db.scalars(select(Proveedor))}
    hay = {(pid, numero) for pid, numero in db.execute(
        select(FacturaProveedor.proveedor_id, FacturaProveedor.numero_factura))}
    plan = Plan()
    for factura in lectura.items:
        pid = proveedores.get(factura.proveedor.lower())
        (plan.existentes if (pid, factura.numero) in hay else plan.nuevas).append(factura)
    return plan


def usuario_de_importacion(db) -> Usuario:
    """Quien figura como autor de lo importado: un usuario inactivo, como el de la
    migración del sistema antiguo, que no puede iniciar sesión."""
    usuario = db.scalar(select(Usuario).where(Usuario.username == USUARIO_IMPORTACION))
    if usuario is None:
        usuario = Usuario(nombre="Importación de planillas", username=USUARIO_IMPORTACION,
                          password_hash=hash_password(secrets.token_hex(16)),
                          rol="USUARIO_NORMAL", activo=False)
        db.add(usuario)
        db.flush()
    return usuario


def aplicar_por_cobrar(db, plan: Plan) -> int:
    """Crea las cuentas (ya facturadas) y, si la planilla trae fecha de pago, las
    deja pagadas ese día. No confirma: eso lo decide quien llama."""
    usuario = usuario_de_importacion(db)
    for c in plan.nuevas:
        cuenta = finanzas.crear_cuenta_manual(
            db, cliente_nombre=c.cliente, numero_factura=c.factura,
            fecha_factura=c.fecha_factura, venta_neto=c.neto, usuario_id=usuario.id,
            numero_oc=c.oc, costo=c.costo, observaciones=f"{MARCA} {c.hoja}, fila {c.fila}.")
        if c.fecha_pago:
            finanzas.registrar_pago_cobro(db, cuenta, cuenta.monto, c.fecha_pago, usuario.id)
    return len(plan.nuevas)


def aplicar_por_pagar(db, plan: Plan) -> tuple[int, int]:
    """Crea los proveedores que falten y las facturas con sus pagos. Devuelve
    (facturas, proveedores nuevos)."""
    usuario = usuario_de_importacion(db)
    proveedores = {p.nombre.lower(): p for p in db.scalars(select(Proveedor))}
    nuevos = 0
    for f in plan.nuevas:
        proveedor = proveedores.get(f.proveedor.lower())
        if proveedor is None:
            proveedor = finanzas.crear_proveedor(db, f.proveedor)
            proveedores[f.proveedor.lower()] = proveedor
            nuevos += 1
        factura = finanzas.registrar_factura_proveedor(
            db, proveedor, f.numero, f.compra, f.monto, usuario.id, fecha_vencimiento=f.vence,
            observaciones=f"{MARCA} {f.hoja}, fila {f.fila}." + (f" {f.observaciones}" if f.observaciones else ""))
        for monto, dia in f.pagos:
            finanzas.registrar_pago_proveedor(db, factura, monto, dia, usuario.id)
    return len(plan.nuevas), nuevos


def deshacer(db) -> dict[str, int]:
    """Saca lo importado (lo marcado en observaciones), pagos incluidos. Los
    proveedores creados se dejan: no llevan marca y pueden tener facturas a mano."""
    cuentas = list(db.scalars(select(CuentaPorCobrar).where(
        CuentaPorCobrar.observaciones.like(f"{MARCA}%"))))
    facturas = list(db.scalars(select(FacturaProveedor).where(
        FacturaProveedor.observaciones.like(f"{MARCA}%"))))
    pagos_c = pagos_p = 0
    for cuenta in cuentas:
        pagos_c += db.query(PagoCobro).filter_by(cuenta_id=cuenta.id).delete()
        db.delete(cuenta)
    for factura in facturas:
        pagos_p += db.query(PagoProveedor).filter_by(factura_id=factura.id).delete()
        db.delete(factura)
    db.flush()
    return {"cuentas": len(cuentas), "pagos_cobro": pagos_c,
            "facturas": len(facturas), "pagos_proveedor": pagos_p}


def resumen_por_motivo(omitidas: list[Omitida]) -> Counter:
    return Counter(o.motivo for o in omitidas)
