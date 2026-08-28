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


def obligatorias_del_esquema():
    """Columnas que el `.sql` declara NOT NULL. La PK lo es sin decirlo."""
    return {
        tabla: {
            nombre
            for nombre, resto in re.findall(r'^\s+"(\w+)"(.*)$', cuerpo, re.M)
            if "NOT NULL" in resto or "PRIMARY KEY" in resto
        }
        for tabla, cuerpo in re.findall(r'CREATE TABLE "(\w+)" \((.*?)\n\);', SQL, re.S)
    }


def test_los_modelos_calzan_con_el_esquema():
    configure_mappers()  # revienta acá si una relación quedó mal escrita

    columnas = columnas_del_esquema()
    assert set(Base.metadata.tables) == set(columnas)

    obligatorias = obligatorias_del_esquema()
    for tabla, obj in Base.metadata.tables.items():
        faltantes = {c.name for c in obj.columns} - columnas[tabla]
        assert not faltantes, f"{tabla}: columnas que no existen en el esquema -> {faltantes}"

        # Comparar solo los nombres deja pasar el peor tipo de desfase: el
        # modelo diciendo que una columna es obligatoria cuando la base ya no
        # lo exige.
        for columna in obj.columns:
            obligatoria = columna.name in obligatorias[tabla]
            assert columna.nullable != obligatoria, (
                f"{tabla}.{columna.name}: el esquema dice "
                f"{'NOT NULL' if obligatoria else 'nullable'} y el modelo dice "
                f"{'nullable' if columna.nullable else 'NOT NULL'}"
            )
