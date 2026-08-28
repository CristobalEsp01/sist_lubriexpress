"""Normalización de texto para buscar.

La regla se aplica en dos lugares: en Python, para filtrar los combos sin ir a
la base, y en SQL, para el WHERE de los listados. Si las dos versiones se
separan, buscar "perez" encuentra al cliente en una pantalla y no en la otra,
así que la segunda prueba las corre lado a lado.
"""
import pytest
from sqlalchemy import literal, select

from src.texto import columna_normalizada, columna_sin_tildes, normalizar, sin_tildes

CASOS = [
    # texto,                  sin_tildes,          normalizar
    ("Pérez",                 "PEREZ",             "PEREZ"),
    ("Núñez",                 "NUNEZ",             "NUNEZ"),
    ("María González",        "MARIA GONZALEZ",    "MARIAGONZALEZ"),
    ("12.345.678-5",          "12.345.678-5",      "123456785"),
    ("BB-BB-12",              "BB-BB-12",          "BBBB12"),
    ("Líquido de frenos",     "LIQUIDO DE FRENOS", "LIQUIDODEFRENOS"),
    ("",                      "",                  ""),
    (None,                    "",                  ""),
]


@pytest.mark.parametrize("texto, plano, aplanado", CASOS)
def test_normaliza_tildes_puntuacion_y_mayusculas(texto, plano, aplanado):
    # sin_tildes respeta los espacios (los nombres se buscan por palabras);
    # normalizar además se come la puntuación de RUT y patentes.
    assert sin_tildes(texto) == plano
    assert normalizar(texto) == aplanado


@pytest.mark.parametrize("texto, _plano, _aplanado", CASOS)
def test_python_y_sql_normalizan_igual(db, texto, _plano, _aplanado):
    """El contrato que sostiene todo: las dos implementaciones coinciden."""
    assert db.scalar(select(columna_sin_tildes(literal(texto or "")))) == sin_tildes(texto)
    assert db.scalar(select(columna_normalizada(literal(texto or "")))) == normalizar(texto)
