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


def clp(valor) -> str:
    """20000.00 -> '$20.000'. En Chile no se usan decimales en caja."""
    return f"${int(valor):,}".replace(",", ".")


def redondear_decena(monto) -> int:
    """Ley de redondeo: terminaciones de 1 a 5 bajan a la decena, de 6 a 9 suben."""
    monto_entero = int(monto)
    unidad = monto_entero % 10
    if unidad == 0:
        return monto_entero
    elif unidad <= 5:
        return monto_entero - unidad
    else:
        return monto_entero + (10 - unidad)
