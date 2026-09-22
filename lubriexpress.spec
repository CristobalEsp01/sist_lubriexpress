# -*- mode: python ; coding: utf-8 -*-
"""Empaquetado con PyInstaller para el PC de recepción (Windows).

    .venv\\Scripts\\pyinstaller.exe --noconfirm lubriexpress.spec

Deja dist/lubriexpress/ con tres ejecutables y todo lo que necesitan:

    lubriexpress.exe   la aplicación
    actualizar.exe     lleva la base a la versión nueva del esquema
    respaldar.exe      el volcado diario, para la tarea programada
    restaurar.exe      pone de vuelta un respaldo: el camino de regreso
    crear_usuario.exe  el primer administrador de una instalación nueva

Los cuatro últimos van de consola: son operaciones de mantenimiento y lo que
importa de ellas es el registro que imprimen. Existen porque el PC del taller
no tiene Python; sin ellos, ni el respaldo ni la actualización se pueden
correr ahí. La migración del sistema antiguo queda fuera a propósito: se hace
una sola vez, desde el código fuente y con las planillas, que no viven en el
repositorio.

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
restauracion = Analysis(["scripts/restaurar.py"], excludes=SIN_QT)
primer_usuario = Analysis(["scripts/crear_usuario.py"], excludes=SIN_QT)

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
exe_restaurar = EXE(
    PYZ(restauracion.pure), restauracion.scripts, exclude_binaries=True,
    name="restaurar", console=True, icon="src/ui/recursos/logo.ico",
)
exe_crear_usuario = EXE(
    PYZ(primer_usuario.pure), primer_usuario.scripts, exclude_binaries=True,
    name="crear_usuario", console=True, icon="src/ui/recursos/logo.ico",
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    exe_actualizar, actualizador.binaries, actualizador.datas,
    exe_respaldar, respaldo.binaries, respaldo.datas,
    exe_restaurar, restauracion.binaries, restauracion.datas,
    exe_crear_usuario, primer_usuario.binaries, primer_usuario.datas,
    name="lubriexpress",
)
