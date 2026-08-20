"""Chequeo sin base de datos: los modelos ORM calzan con el esquema SQL."""
import re
from pathlib import Path

from sqlalchemy.orm import configure_mappers

from conftest import RAIZ
from src import models  # noqa: F401
from src.database import Base

SQL = (Path(RAIZ) / "database" / "schema_lubriexpress.sql").read_text(encoding="utf-8")


def columnas_del_esquema():
    return {
        tabla: set(re.findall(r'^\s+"(\w+)"', cuerpo, re.M))
        for tabla, cuerpo in re.findall(r'CREATE TABLE "(\w+)" \((.*?)\n\);', SQL, re.S)
    }


def test_los_mappers_configuran():
    configure_mappers()


def test_toda_tabla_del_esquema_tiene_modelo():
    assert set(Base.metadata.tables) == set(columnas_del_esquema())


def test_las_columnas_existen_en_el_esquema():
    esquema = columnas_del_esquema()
    for tabla, obj in Base.metadata.tables.items():
        faltantes = {c.name for c in obj.columns} - esquema[tabla]
        assert not faltantes, f"{tabla}: columnas que no existen en el esquema -> {faltantes}"
