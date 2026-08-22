"""RUT chileno: normalización, dígito verificador (módulo 11) y formato."""
import re

_LIMPIO = re.compile(r"^\d{7,8}[0-9K]$")


def normalizar(rut: str) -> str:
    """'12.345.678-5' -> '123456785'"""
    return re.sub(r"[.\-\s]", "", rut or "").upper()


def digito_verificador(cuerpo: str) -> str:
    """Módulo 11: se pondera de derecha a izquierda con la serie 2,3,4,5,6,7 cíclica."""
    suma = 0
    factor = 2
    for digito in reversed(cuerpo):
        suma += int(digito) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - (suma % 11)
    return {11: "0", 10: "K"}.get(resto, str(resto))


def es_valido(rut: str) -> bool:
    limpio = normalizar(rut)
    if not _LIMPIO.match(limpio):
        return False
    return digito_verificador(limpio[:-1]) == limpio[-1]


def formatear(rut: str) -> str:
    """'123456785' -> '12.345.678-5'. Guardar siempre así mantiene útil el UNIQUE del RUT."""
    limpio = normalizar(rut)
    if len(limpio) < 2:
        # El campo es opcional, así que llega vacío; y con un solo carácter no
        # hay cuerpo que formatear (int("") revienta). Validar es de es_valido().
        return ""
    cuerpo, dv = limpio[:-1], limpio[-1]
    return f"{int(cuerpo):,}".replace(",", ".") + f"-{dv}"
