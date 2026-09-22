"""El actualizador de esquema: lo que se corre en el PC del taller para llevar
una base con datos reales a la versión nueva sin recrearla.

Se prueba lo que duele si falla: que una base actualizada quede igual que una
recién instalada desde el `.sql`, que correrlo dos veces no rompa nada, y que
el respaldo ocurra antes de tocar el esquema.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conftest import exigir_base_de_datos  # noqa: E402
from scripts import actualizar as A  # noqa: E402
from test_models import SQL, columnas_del_esquema  # noqa: E402


def normalizado(sql: str) -> str:
    """Sin comentarios y con los espacios colapsados: lo que queda es el SQL."""
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", " ", sql)).strip()


def test_lo_que_agrega_el_actualizador_es_texto_del_esquema():
    """Una base actualizada y una recién instalada tienen que quedar idénticas.

    Cada paso declara qué trozos de `schema_lubriexpress.sql` reproduce, y acá
    se verifica que estén palabra por palabra en el esquema **y** en el SQL que
    el paso ejecuta. Si el `.sql` cambia una columna, una restricción o un
    trigger y el actualizador no, el PC del taller termina con un esquema que
    ninguna otra prueba mira.
    """
    esquema = normalizado(SQL)
    columnas = columnas_del_esquema()

    for paso in A.PASOS:
        tabla = paso.nombre.partition(".")[0]
        assert tabla in columnas, f"{paso.nombre}: esa tabla no está en el esquema"
        for trozo in paso.declara or (paso.sql,):
            assert normalizado(trozo) in esquema, f"{paso.nombre}: no está en el .sql"
            assert normalizado(trozo) in normalizado(paso.sql), (
                f"{paso.nombre}: declara algo que su propio SQL no hace"
            )


def test_correrlo_dos_veces_no_deja_nada_pendiente():
    """Idempotencia contra PostgreSQL de verdad: es lo único que prueba que la
    comprobación de cada paso mira lo que ese paso realmente crea. De paso deja
    la base de desarrollo actualizada, que es donde tiene que estar."""
    exigir_base_de_datos()
    from src.database import engine

    with engine.begin() as conexion:
        for paso in A.pendientes(conexion):
            A.aplicar(conexion, paso)

    with engine.connect() as conexion:
        assert A.pendientes(conexion) == []


def test_si_el_respaldo_falla_no_se_toca_el_esquema(monkeypatch):
    """El respaldo va primero y su fallo aborta todo. Sin eso, un paso que
    reviente a mitad deja la base del taller a medio camino y sin nada de dónde
    volver."""
    exigir_base_de_datos()
    aplicados = []

    def respaldo_que_falla():
        raise SystemExit("pg_dump no está instalado")

    monkeypatch.setattr(A, "pendientes", lambda conexion: [A.PASOS[0]])
    monkeypatch.setattr(A, "respaldar", respaldo_que_falla)
    monkeypatch.setattr(A, "aplicar", lambda *args: aplicados.append(args))

    with pytest.raises(SystemExit):
        A.main([])

    assert aplicados == []


def test_la_ubicacion_escrita_en_la_descripcion_pasa_a_su_columna(db):
    """Los datos ya están migrados en producción, así que esto no puede vivir
    solo en el script de migración: el relleno lee las descripciones de la base
    que ya está en uso."""
    from src.models import Producto

    solo_ubicacion = Producto(nombre="QA ubicacion", descripcion="Ubicación: M-4C",
                              precio_costo=1, precio_venta=2)
    mezclada = Producto(nombre="QA mezclada", descripcion="Mann M7-B original",
                        precio_costo=1, precio_venta=2)
    sin_nada = Producto(nombre="QA sin nada", descripcion="Toyota Hilux 2.8",
                        precio_costo=1, precio_venta=2)
    db.add_all([solo_ubicacion, mezclada, sin_nada])
    db.flush()

    A.rellenar_ubicaciones(db, aplicar=True)
    db.flush()

    assert (solo_ubicacion.ubicacion.descripcion, solo_ubicacion.descripcion) == ("M4-C", None)
    assert (mezclada.ubicacion.descripcion, mezclada.descripcion) == ("M7-B", "Mann M7-B original")
    assert sin_nada.ubicacion_id is None

    # Correrlo de nuevo no toca lo que ya tiene ubicación.
    tocados, _ = A.rellenar_ubicaciones(db, aplicar=True)
    assert solo_ubicacion.ubicacion.descripcion == "M4-C"
