# -*- mode: python ; coding: utf-8 -*-
"""Empaquetado con PyInstaller para el PC de recepción (Windows).

    .venv\\Scripts\\pyinstaller.exe --noconfirm lubriexpress.spec

Deja dist/lubriexpress/ con tres ejecutables y todo lo que necesitan:

    lubriexpress.exe   la aplicación
    actualizar.exe     lleva la base a la versión nueva del esquema
    respaldar.exe      el volcado diario, para la tarea programada

Los dos últimos van de consola: son operaciones de mantenimiento y lo que
importa de ellas es el registro que imprimen. Existen porque el PC del taller
no tiene Python; sin ellos, ni el respaldo ni la actualización se pueden
correr ahí.

Al lado de los ejecutables va el .env con DATABASE_URL (ver .env.example); la
base es un PostgreSQL de la misma máquina. Ahí mismo caen los respaldos. Los
.exe se construyen en Windows: PyInstaller no cruza plataformas.

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
# Las herramientas de consola no necesitan Qt: fuera, que son 60 MB por cada una.
SIN_QT = ["PySide6", "shiboken6"]
actualizador = Analysis(["scripts/actualizar.py"], excludes=SIN_QT)
respaldo = Analysis(["scripts/respaldar.py"], excludes=SIN_QT)

exe = EXE(
    PYZ(a.pure), a.scripts, exclude_binaries=True,
    name="lubriexpress", console=False, icon="src/ui/recursos/logo.ico",
)
exe_actualizar = EXE(
    PYZ(actualizador.pure), actualizador.scripts, exclude_binaries=True,
    name="actualizar", console=True, icon="src/ui/recursos/logo.ico",
)
exe_respaldar = EXE(
    PYZ(respaldo.pure), respaldo.scripts, exclude_binaries=True,
    name="respaldar", console=True, icon="src/ui/recursos/logo.ico",
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    exe_actualizar, actualizador.binaries, actualizador.datas,
    exe_respaldar, respaldo.binaries, respaldo.datas,
    name="lubriexpress",
)
