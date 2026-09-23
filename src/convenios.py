"""Descuentos por convenio: flyer foliado (10 %) y gremios y sindicatos (15 %).

Se aplican solo a productos de ciertas categorías, nunca al servicio: la mano de
obra va incluida en el precio del bidón. `recategorizar` le da tipo a los
productos de categoría genérica ("FILTRO", "ACEITES") del sistema antiguo.
"""
import re

from .texto import sin_tildes

GREMIO = {"ACEITE MOTOR", "FILTRO ACEITE", "FILTRO AIRE", "FILTRO POLEN"}
# Todos los filtros, genéricos incluidos.
FLYER = GREMIO | {"FILTRO PETROLEO", "FILTRO BENCINA", "FILTRO COMBUSTIBLE", "FILTRO"}

CONVENIOS = {"FLYER": (10, FLYER), "GREMIO": (15, GREMIO)}
FOLIOS_FLYER = range(1, 1001)   # los flyers se imprimieron del 0001 al 1000


def descuento(convenio: str, lineas) -> int:
    """El porcentaje del convenio sobre el neto de las líneas (categoría,
    subtotal) que entran. Los servicios van sin categoría: no entran."""
    porcentaje, categorias = CONVENIOS[convenio]
    base = sum(subtotal for categoria, subtotal in lineas
               if sin_tildes(categoria).strip() in categorias)
    return int(round(base * porcentaje / 100))


# El tipo sale de la palabra del nombre. Si dice dos (un pack), no se adivina.
TIPOS_DE_FILTRO = (("POLEN", "Filtro Polen"), ("AIRE", "Filtro aire"),
                   ("ACEITE", "Filtro aceite"), ("PETROLEO", "Filtro Petroleo"),
                   ("BENCINA", "Filtro bencina"))
# Viscosidad (5W30) o monogrado (SAE 40). 75W90 y 80W90 son de caja aunque
# tengan la misma forma: DE_TRANSMISION las descarta.
DE_MOTOR = re.compile(r"\b\d{1,2}\s?W\s?-?\s?\d{2}\b|\bSAE\s?\d{2}\b")
DE_TRANSMISION = re.compile(r"\bATF\b|\bGL-?\d|GEAR|CAJA|TRANSMISION|DIFERENCIAL|"
                            r"HIDRAULIC|\b(75|80|85)\s?W")


def recategorizar(categoria: str | None, nombre: str) -> str | None:
    """La categoría para un producto de categoría genérica, o None si el nombre
    no la dice o la categoría ya es específica."""
    generica, nombre = sin_tildes(categoria).strip(), sin_tildes(nombre)
    if generica == "FILTRO" and not re.search(r"\b(PACK|KIT)\b", nombre):
        tipos = {tipo for palabra, tipo in TIPOS_DE_FILTRO if re.search(rf"\b{palabra}\b", nombre)}
        return tipos.pop() if len(tipos) == 1 else None
    if generica == "ACEITES" and DE_MOTOR.search(nombre) and not DE_TRANSMISION.search(nombre):
        return "Aceite motor"
    return None


def rotulo(convenio: str | None, folio: int | None) -> str:
    """'Flyer N° 0042 (10 %)', para el detalle y el PDF de la orden."""
    if convenio is None:
        return ""
    nombre = f"Flyer N° {folio:04d}" if convenio == "FLYER" else "Gremio/Sindicato"
    return f"{nombre} ({CONVENIOS[convenio][0]} %)"
