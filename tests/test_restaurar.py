"""La restauración de un respaldo, contra PostgreSQL de verdad.

Lo que duele si falla: un respaldo de una versión anterior no se podía
restaurar sobre el esquema actual (las tablas nuevas apuntan a las viejas y el
DROP del volcado choca con sus FK), y al fallar dejaba la base sin la mitad de
sus restricciones porque psql no corría en una transacción. Se prueba en una
base desechable del mismo servidor, nunca en la de desarrollo.
"""
import gzip
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conftest import exigir_base_de_datos  # noqa: E402
from scripts.respaldar import contenedor, datos_de_conexion  # noqa: E402
from scripts.restaurar import (  # noqa: E402
    comando_de_restauracion, pasos_pendientes, restaurar, sql_con_esquema_limpio,
)
from test_models import SQL  # noqa: E402

BASE = "lubriexpress_prueba_restaurar"
VIEJO = (b'DROP TABLE IF EXISTS public.productos;\n'
         b'CREATE TABLE public.productos (id int PRIMARY KEY, nombre text);\n'
         b"INSERT INTO public.productos VALUES (1, 'viejo');\n")
FKS = ("SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace"
       " WHERE n.nspname = 'public' AND c.contype = 'f'")


def _hay_psql() -> bool:
    if shutil.which("psql"):
        return True
    return subprocess.run(["docker", "inspect", contenedor()],
                          capture_output=True).returncode == 0


@pytest.fixture
def base_de_prueba(monkeypatch):
    exigir_base_de_datos()
    if not _hay_psql():
        pytest.skip("No hay psql ni contenedor para restaurar")
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    from src.database import DATABASE_URL

    url = make_url(DATABASE_URL).set(database=BASE)
    servidor = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")
    with servidor.connect() as conexion:
        conexion.exec_driver_sql(f'DROP DATABASE IF EXISTS "{BASE}" WITH (FORCE)')
        conexion.exec_driver_sql(f'CREATE DATABASE "{BASE}"')
    url_texto = url.render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url_texto)
    datos = datos_de_conexion()
    comando, entorno = comando_de_restauracion(datos)
    instalado = subprocess.run(comando, input=SQL.encode(), capture_output=True, env=entorno)
    assert instalado.returncode == 0, instalado.stderr.decode()
    try:
        yield url_texto, datos
    finally:
        with servidor.connect() as conexion:
            conexion.exec_driver_sql(f'DROP DATABASE IF EXISTS "{BASE}" WITH (FORCE)')
        servidor.dispose()


def filas(url: str, consulta: str) -> list[tuple]:
    from sqlalchemy import create_engine

    motor = create_engine(url)
    try:
        with motor.connect() as conexion:
            return [tuple(fila) for fila in conexion.exec_driver_sql(consulta)]
    finally:
        motor.dispose()


def gz(carpeta: Path, contenido: bytes) -> Path:
    archivo = carpeta / "respaldo.sql.gz"
    with gzip.open(archivo, "wb") as salida:
        salida.write(contenido)
    return archivo


def test_el_volcado_va_precedido_de_limpiar_el_esquema():
    assert sql_con_esquema_limpio(b"X").startswith(b"DROP SCHEMA public CASCADE;")
    assert sql_con_esquema_limpio(b"X").endswith(b"X")
    datos = {"usuario": "u", "password": "p", "host": "h", "puerto": "1", "base": "b"}
    assert "--single-transaction" in comando_de_restauracion(datos)[0]


def test_un_respaldo_de_una_version_anterior_se_restaura_entero(base_de_prueba, tmp_path):
    url, datos = base_de_prueba
    restaurar(gz(tmp_path, VIEJO), datos)
    assert filas(url, "SELECT id, nombre FROM productos") == [(1, "viejo")]
    assert filas(url, "SELECT to_regclass('public.ventas')") == [(None,)]
    assert pasos_pendientes(url)                     # hay que correr actualizar.exe


def test_una_restauracion_que_falla_deja_la_base_como_estaba(base_de_prueba, tmp_path):
    url, datos = base_de_prueba
    antes = filas(url, FKS)
    with pytest.raises(SystemExit, match="no se aplicó nada"):
        restaurar(gz(tmp_path, VIEJO + b"SELECT * FROM no_existe;\n"), datos)
    assert filas(url, FKS) == antes
    assert filas(url, "SELECT to_regclass('public.ventas') IS NOT NULL") == [(True,)]
