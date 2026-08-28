"""Contraste de la paleta: cada par texto/fondo contra WCAG 2.1 AA.

No es un gusto: con el ámbar 600 original, la pestaña activa daba 3.02 y el
botón primario con texto blanco 3.19, los dos bajo el 4.5 que exige el texto.
Esta prueba existe para que un retoque de color no vuelva a bajar de ahí sin
que nadie se entere.
"""
import pytest

from src.ui import tema as T

TEXTO, CONTROL = 4.5, 3.0  # mínimos AA para texto y para bordes de control

PARES = [
    ("Texto sobre el fondo",        T.TINTA,         T.FONDO,         TEXTO),
    ("Celda de tabla",              T.TINTA,         T.SUPERFICIE,    TEXTO),
    ("Celda de fila alterna",       T.TINTA,         T.ALTERNA,       TEXTO),
    ("Celda seleccionada",          T.TINTA,         T.ACENTO_FONDO,  TEXTO),
    ("Encabezado, pestaña, resumen", T.TINTA_SUAVE,  T.FONDO,         TEXTO),
    ("Pestaña activa",              T.ACENTO_OSCURO, T.FONDO,         TEXTO),
    ("Botón en hover",              T.ACENTO_OSCURO, T.SUPERFICIE,    TEXTO),
    ("Botón primario",              T.SUPERFICIE,    T.ACENTO_OSCURO, TEXTO),
    ("Botón primario en hover",     T.SUPERFICIE,    T.ACENTO_PROFUNDO, TEXTO),
    ("Aviso de tabla vacía",        T.TINTA_SUAVE,   T.SUPERFICIE,    TEXTO),
    ("Fila de producto inactivo",   T.TINTA_SUAVE,   T.ALTERNA,       TEXTO),
    ("Stock bajo el mínimo",        T.ALERTA,        T.SUPERFICIE,    TEXTO),
    ("Insignia alerta",             T.ALERTA,        T.ALERTA_FONDO,  TEXTO),
    ("Insignia éxito",              T.EXITO,         T.EXITO_FONDO,   TEXTO),
    ("Insignia info",               T.INFO,          T.INFO_FONDO,    TEXTO),
    ("Insignia neutral",            T.NEUTRAL_TEXTO, T.NEUTRAL_FONDO, TEXTO),
    ("Insignia acento",             T.ACENTO_OSCURO, T.ACENTO_FONDO,  TEXTO),
    ("Tooltip",                     T.SUPERFICIE,    T.TINTA,         TEXTO),
    ("Borde de campo",              T.BORDE_CAMPO,   T.SUPERFICIE,    CONTROL),
    ("Borde de campo en diálogo",   T.BORDE_CAMPO,   T.FONDO,         CONTROL),
    ("Campo con foco",              T.ACENTO,        T.SUPERFICIE,    CONTROL),
    ("Subrayado de pestaña activa", T.ACENTO,        T.FONDO,         CONTROL),
]


def luminancia(hexa: str) -> float:
    canales = (int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lineal = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canales]
    return 0.2126 * lineal[0] + 0.7152 * lineal[1] + 0.0722 * lineal[2]


def contraste(uno: str, otro: str) -> float:
    a, b = luminancia(uno), luminancia(otro)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


@pytest.mark.parametrize("descripcion, frente, fondo, minimo", PARES)
def test_la_paleta_cumple_el_contraste_minimo(descripcion, frente, fondo, minimo):
    medido = contraste(frente, fondo)
    assert medido >= minimo, (
        f"{descripcion}: {frente} sobre {fondo} da {medido:.2f}, "
        f"por debajo del mínimo {minimo}"
    )
