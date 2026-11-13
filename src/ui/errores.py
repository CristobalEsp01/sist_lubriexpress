"""El aviso de un error inesperado: `sys.excepthook` de la aplicación.

Qt no propaga lo que revienta en un slot: lo entrega a `sys.excepthook` y sigue
corriendo. El de Python lo imprime en la consola, que el .exe no tiene. Este lo
anota en `errores.log` y muestra un solo aviso: con la base caída, cada recarga
de tabla falla, y una ráfaga de diálogos apilados no dejaría usar la ventana.
"""
import sys

from PySide6.QtWidgets import QMessageBox

from .. import errores

_mostrando = False


def manejar(tipo, valor, rastro) -> None:
    global _mostrando
    if issubclass(tipo, KeyboardInterrupt):
        sys.__excepthook__(tipo, valor, rastro)
        return
    try:
        errores.registrar(tipo, valor, rastro)
    except OSError:
        pass  # sin log igual se avisa: es lo único que el usuario ve
    if _mostrando:
        return
    _mostrando = True
    try:
        QMessageBox.critical(None, "Error", errores.mensaje(valor))
    finally:
        _mostrando = False


def instalar() -> None:
    sys.excepthook = manejar
