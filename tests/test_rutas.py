"""Dónde busca sus archivos la aplicación cuando va empaquetada.

Regresión: `respaldar.py` resolvía el `.env` y la carpeta de respaldos desde
`__file__`. Dentro de un bundle de PyInstaller eso es el directorio temporal
que el sistema borra al cerrar, así que un respaldo lanzado desde el ejecutable
se escribía donde nadie lo iba a encontrar, y eso solo se descubre el día que
hace falta restaurarlo.
"""
import sys
from pathlib import Path

from conftest import RAIZ
from src.rutas import carpeta_app


def test_empaquetada_los_archivos_van_junto_al_ejecutable(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "lubriexpress.exe"))

    assert carpeta_app() == tmp_path


def test_desde_el_repositorio_la_carpeta_es_la_raiz(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    assert carpeta_app() == Path(RAIZ)
