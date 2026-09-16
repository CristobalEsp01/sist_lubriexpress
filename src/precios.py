"""IVA. Los precios del catálogo (productos y servicios) son netos; el
impuesto se calcula al cobrar y queda guardado en el documento, para que el
historial no dependa de la tasa vigente.

Sin dependencias de UI ni de base de datos, como rut.py: lo usan las dos
pantallas de cobro y cualquier reporte.
"""
from decimal import ROUND_HALF_UP, Decimal

IVA = Decimal("0.19")


def iva_de(neto) -> int:
    """IVA en pesos enteros, redondeado como en la boleta."""
    return int((Decimal(neto) * IVA).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def con_iva(neto) -> int:
    return int(neto) + iva_de(neto)
