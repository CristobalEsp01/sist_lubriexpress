# -*- mode: python ; coding: utf-8 -*-
"""Empaquetado con PyInstaller para el PC de recepción (Windows).

    .venv\\Scripts\\pyinstaller.exe --noconfirm lubriexpress.spec

Deja dist/lubriexpress/ con el ejecutable y todo lo que necesita. Al lado del
ejecutable va el .env con DATABASE_URL (ver .env.example); la base es un
PostgreSQL de la misma máquina. El .exe se construye en Windows: PyInstaller
no cruza plataformas.

qtbase_es.qm va explícito: sin él los botones estándar de los diálogos
(Guardar, Cancelar, Sí, No) salen en inglés. Se copia a la ruta donde Qt lo
busca dentro del bundle.
"""
from pathlib import Path

from PySide6.QtCore import QLibraryInfo

traducciones = Path(QLibraryInfo.path(QLibraryInfo.TranslationsPath))

a = Analysis(
    ["main.py"],
    datas=[(str(traducciones / "qtbase_es.qm"), "PySide6/Qt/translations"),
           ("src/ui/recursos/logo.jpeg", "src/ui/recursos"),
           ("src/ui/recursos/logo.ico", "src/ui/recursos")],
    # Solo los módulos de Qt que se usan: cada uno que sobra son megas.
    excludes=["PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtWebEngineCore",
              "PySide6.QtMultimedia", "PySide6.QtOpenGL", "PySide6.Qt3DCore"],  # QtCharts sí: Reportes
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, exclude_binaries=True,
    name="lubriexpress", console=False, icon="src/ui/recursos/logo.ico",
)
coll = COLLECT(exe, a.binaries, a.datas, name="lubriexpress")
