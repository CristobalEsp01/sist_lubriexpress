"""Sacar la ubicación de bodega de la descripción del producto.

El sistema antiguo no tenía campo de ubicación, así que el mostrador la escribió
en la descripción de mil maneras. Los casos de acá son cadenas reales de la
planilla: son la especificación.
"""
import pytest

from src.ubicaciones import detectar


@pytest.mark.parametrize("descripcion, ubicacion", [
    # El prefijo explícito y el código pelado son la misma repisa.
    ("Ubicación: M4-C", "M4-C"),
    ("UBICACIÓN: M4-C", "M4-C"),
    ("M-4C", "M4-C"),
    ("M4-c", "M4-C"),
    ("M2 - C (derecha)", "M2-C"),
    ("M-1 IZQ", "M1-IZQ"),
    ("M1-IZQUIERDA", "M1-IZQ"),
    ("Ubicación: M1-DERECHA/CENTRO", "M1-DER"),
    ("M-01 (al medio)", "M1"),
    ("M-8", "M8"),
    # Bandejas y cajas, con sus erratas y sus ceros a la izquierda.
    ("BANDEJA 02", "BANDEJA 2"),
    ('BANDEJA "18"', "BANDEJA 18"),
    ("bandeja 7", "BANDEJA 7"),
    ("CAJA - K", "CAJA K"),
    ("CAJA MSIVO3", "CAJA MASIVO 3"),
    ("CAJA MASIVO 2", "CAJA MASIVO 2"),
    ("Caja Wuth", "CAJA WURTH"),
    # Muebles y referencias físicas.
    ("Mini Mueble-B", "MINI MUEBLE B"),
    ("MINI MUEBLE - B", "MINI MUEBLE B"),
    ("Repisa YOF", "REPISA YPF"),
    ("Ubicación: Sobre refri", "SOBRE REFRI"),
    ("Bajo TV", "BAJO TV"),
    ("Ubicación: Colgador Amarillo", "COLGADOR AMARILLO"),
    ("COLGADDDO VITRINA", "COLGADOR VITRINA"),
    ("(9 tras oficina)", "TRAS OFICINA"),
    ("M SALIDA-B", "M SALIDA B"),
])
def test_la_misma_repisa_escrita_distinto_queda_en_una_sola(descripcion, ubicacion):
    assert detectar(descripcion)[0] == ubicacion


@pytest.mark.parametrize("descripcion", [
    # Medidas de rosca, no un estante: el M14 del medio no es el módulo 14.
    "Tapón de drenaje de aceite magnético M12x1.5,M14,M16,M18 (Cabeza 3/4)",
    "Toyota Hilux 2.4-2.8 16/20-Fortuner 2.4 15/19 ELMT",
    "MAXUS T60 2.8",
    "Mitsubishi",
    "CON Y SIN AZUCAR",
    "",
    None,
])
def test_una_descripcion_de_verdad_no_se_confunde_con_una_ubicacion(descripcion):
    assert detectar(descripcion)[0] is None


def test_la_descripcion_solo_se_vacia_cuando_no_era_mas_que_la_ubicacion():
    """Nunca se pierde texto: si además de la ubicación hay algo escrito, la
    descripción queda intacta y la ubicación se copia a su columna."""
    assert detectar("M4-C") == ("M4-C", None)
    assert detectar("Ubicación: Bandeja 5") == ("BANDEJA 5", None)
    assert detectar("Mitsubishi Mirage M7-C") == ("M7-C", "Mitsubishi Mirage M7-C")
    assert detectar("M4-C Filtros originales") == ("M4-C", "M4-C Filtros originales")
    assert detectar("Bajo el mostrador") == (None, "Bajo el mostrador")
