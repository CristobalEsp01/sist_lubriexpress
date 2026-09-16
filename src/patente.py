"""Patente chilena. Sin dependencias de UI ni de base de datos, igual que
rut.py: la usan el formulario de vehículo y la migración desde Excel."""
import re

# Autos: AA1234 (hasta 2007) y BBBB12 (desde 2007). Las motos (AA123, AAA12)
# no se atienden en un lubricentro.
PATENTE = re.compile(r"^([A-Z]{2}\d{4}|[A-Z]{4}\d{2})$")


def normalizar_patente(texto: str | None) -> str:
    """'jf-fg.56' -> 'JFFG56'. No valida: para eso está PATENTE.match()."""
    return re.sub(r"[.\-\s]", "", texto or "").upper()
