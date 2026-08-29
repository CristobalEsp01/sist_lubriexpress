"""Configuración común de las pruebas.

Se ejecuta antes que cualquier módulo de prueba, así que acá se resuelven las
dos cosas que deben pasar primero: apuntar a la base correcta y evitar que Qt
abra ventanas reales.
"""
import os
import random

# Sin esto, las pruebas de interfaz abren ventanas de verdad en tu escritorio.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dotenv import load_dotenv  # noqa: E402

# load_dotenv() no pisa lo que ya está en el entorno, así que va antes del
# setdefault: si hay .env manda el .env, y si no, una URL cualquiera que sirva
# para las pruebas que nunca se conectan.
load_dotenv()
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from src.rut import digito_verificador, formatear  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def rut_de_prueba() -> str:
    """RUT válido y distinto en cada corrida.

    La base de desarrollo tiene datos commiteados y va a tener más. Con RUT
    fijos es cuestión de tiempo que una fixture choque contra el UNIQUE de una
    fila real: ya pasó con 11.111.111-1.
    """
    cuerpo = str(random.randint(10_000_000, 99_999_999))
    return formatear(cuerpo + digito_verificador(cuerpo))


def patente_de_prueba() -> str:
    return f"QA{random.randint(1000, 9999)}"


def exigir_base_de_datos():
    """Salta la prueba en vez de fallar si PostgreSQL no está levantado."""
    from src.database import engine

    try:
        engine.connect().close()
    except OperationalError as e:
        pytest.skip(f"PostgreSQL no disponible: {e}")


@pytest.fixture
def db():
    """Sesión que revierte todo al terminar: las pruebas no dejan residuos."""
    exigir_base_de_datos()
    from src.database import SessionLocal

    sesion = SessionLocal()
    try:
        yield sesion
    finally:
        sesion.rollback()
        sesion.close()


@pytest.fixture(scope="session")
def app():
    """QApplication única para todas las pruebas de interfaz."""
    exigir_base_de_datos()
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    """Hace fallar la prueba si un slot de Qt lanzó una excepción.

    Qt no propaga lo que revienta dentro de un slot: imprime el traceback por
    sys.excepthook y sigue corriendo. Sin esto la batería pasa en verde mientras
    la aplicación escupe errores en cada recarga de tabla, y el único que se
    entera es quien la abre a mano. Ya pasó: un `connect` quedó copiado dentro
    de InventarioWidget.recargar() y las 102 pruebas siguieron en verde.

    Va como hookwrapper de la llamada y no como fixture porque una fixture solo
    puede reclamar en el teardown, y ahí pytest ya cuenta la prueba como pasada:
    el resumen diría "102 passed, 1 error", que es el mismo verde engañoso.
    """
    import sys

    capturadas = []
    anterior = sys.excepthook
    sys.excepthook = lambda *info: capturadas.append(info) or anterior(*info)
    try:
        yield
    finally:
        sys.excepthook = anterior
    if capturadas:
        tipo, valor, _ = capturadas[0]
        pytest.fail(f"un slot de Qt lanzó {tipo.__name__}: {valor}", pytrace=False)
