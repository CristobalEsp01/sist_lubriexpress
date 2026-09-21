"""Dónde están los archivos que la aplicación lee y escribe.

PyInstaller descomprime el bundle en una carpeta temporal, así que
`Path(__file__).parent` apunta a un directorio que el sistema borra al cerrar.
Lo que el taller tiene que poder ver y conservar —el `.env` y los respaldos—
va junto al ejecutable, no ahí dentro.
"""
import sys
from pathlib import Path


def carpeta_app() -> Path:
    """Junto al ejecutable si va empaquetada; la raíz del repositorio si no."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
