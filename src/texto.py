"""Normalización de texto para buscar: sin tildes, sin puntuación, en mayúsculas.

Nadie teclea un RUT con puntos ni un apellido con tilde cuando está buscando.
La misma regla tiene que valer en los dos lados: `normalizar()` para filtrar en
memoria (los combos) y `columna_normalizada()` para el WHERE de los listados.
Si se separan, "perez" encuentra al cliente en una pantalla y no en la otra;
hay una prueba que las corre lado a lado.

Vive fuera de la UI a propósito, igual que rut.py: la carga masiva desde Excel
va a necesitar la misma regla para cruzar nombres.
"""
import re
import unicodedata

from sqlalchemy import func, or_

PUNTUACION = re.compile(r"[.\-\s]")

# ponytail: Postgres no trae unaccent instalado, así que el lado SQL traduce a
# mano el set que aparece en nombres chilenos. Python usa unicodedata, que cubre
# más: divergen recién en caracteres tipo "ç" o "ã". Si alguna vez importan,
# la salida es CREATE EXTENSION unaccent y borrar estas dos constantes.
ACENTUADAS = "áéíóúüñÁÉÍÓÚÜÑ"
LLANAS = "aeiouunAEIOUUN"


def sin_tildes(texto: str | None) -> str:
    """'Pérez' -> 'PEREZ'. Respeta los espacios."""
    descompuesto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in descompuesto if not unicodedata.combining(c)).upper()


def normalizar(texto: str | None) -> str:
    """'12.345.678-5' -> '123456785'. Además de las tildes, se come la
    puntuación con la que se escriben RUT y patentes."""
    return PUNTUACION.sub("", sin_tildes(texto))


def columna_sin_tildes(columna):
    """El equivalente SQL de `sin_tildes()`."""
    return func.upper(func.translate(columna, ACENTUADAS, LLANAS))


def columna_normalizada(columna):
    """El equivalente SQL de `normalizar()`, para usar en un WHERE.

    Se aplica a la columna, así que anula cualquier índice sobre ella. Con los
    volúmenes de un lubricentro el seq scan es irrelevante; con decenas de miles
    de filas correspondería una columna generada e indexada.
    """
    return func.translate(columna_sin_tildes(columna), ".- ", "")


def filtro_busqueda(consulta, texto: str, *columnas, tambien=None):
    """Agrega a `consulta` el filtro de una caja de búsqueda.

    Cada palabra tecleada tiene que aparecer en alguna de las columnas. Partir
    por palabras es lo que permite normalizar sin perder nada: aplanada, la
    consulta "aceite castrol" no calzaría contra "Aceite 10W40 Castrol 4L",
    porque el 10W40 queda en medio.

    `tambien` es un criterio extra que recibe la aguja ya normalizada, para lo
    que no es una columna de la tabla: un cliente también se busca por la
    patente de sus vehículos.
    """
    for palabra in texto.split():
        aguja = f"%{normalizar(palabra)}%"
        criterios = [columna_normalizada(c).like(aguja) for c in columnas]
        if tambien is not None:
            criterios.append(tambien(aguja))
        consulta = consulta.where(or_(*criterios))
    return consulta
