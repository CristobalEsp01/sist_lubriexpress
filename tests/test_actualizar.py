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


def test_el_esquema_se_instala_en_una_base_vacia():
    """El `.sql` es lo que corre en un PC nuevo. Llegó a `main` con una coma de
    menos y ninguna prueba lo ejecutaba: la de arriba solo compara texto. Se
    instala en un esquema de paso dentro de una transacción que se revierte."""
    exigir_base_de_datos()
    from src.database import engine

    with engine.connect() as conexion:
        conexion.exec_driver_sql("CREATE SCHEMA instalacion_de_prueba")
        conexion.exec_driver_sql("SET LOCAL search_path TO instalacion_de_prueba")
        # El cursor del driver, sin parámetros: el `19 %` de un comentario del
        # esquema, pasado por SQLAlchemy, se lee como un marcador de psycopg2.
        conexion.connection.cursor().execute(SQL)
        tablas = set(conexion.exec_driver_sql(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = 'instalacion_de_prueba'").scalars())
        conexion.rollback()
    assert set(columnas_del_esquema()) <= tablas


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


def test_los_productos_genericos_toman_su_tipo_del_nombre(db):
    """172 productos del sistema antiguo quedaron en "FILTRO" a secas, y el
    descuento de gremios necesita saber cuáles son de polen, aire o aceite. Ya
    están en producción, así que el arreglo lee la base en uso."""
    from src.models import Producto

    polen = Producto(nombre="QA Filtro Polen MANN CUK 20027", categoria="FILTRO",
                     precio_costo=1, precio_venta=2)
    pack = Producto(nombre="QA Pack Filtros Nissan NP300", categoria="FILTRO",
                    precio_costo=1, precio_venta=2)
    db.add_all([polen, pack])
    db.flush()

    assert A.recategorizar_productos(db, aplicar=False)["Filtro Polen"] >= 1
    assert polen.categoria == "FILTRO"          # contar no escribe
    A.recategorizar_productos(db, aplicar=True)
    assert (polen.categoria, pack.categoria) == ("Filtro Polen", "FILTRO")
    # Una segunda pasada ya no encuentra nada de lo que tocó.
    assert A.recategorizar_productos(db, aplicar=True)["Filtro Polen"] == 0


def test_los_tecnicos_migrados_pasan_a_ser_mecanicos_de_sus_ordenes(db):
    """La base del taller se migró cuando el técnico solo cabía como el usuario
    de la orden. El paso lo copia a `mecanicos` y enlaza sus órdenes migradas;
    el usuario se queda, y las órdenes del sistema nuevo no se tocan."""
    from conftest import patente_de_prueba, rut_de_prueba
    from src.models import Cliente, Mecanico, Orden, Usuario, Vehiculo

    sufijo = rut_de_prueba()
    tecnico = Usuario(nombre=f"QA Técnico {sufijo}", username=f"qa_tecnico_{sufijo}",
                      password_hash="x", rol="USUARIO_NORMAL", activo=False)
    vehiculo = Vehiculo(cliente=Cliente(nombre_completo="QA migrado"), patente=patente_de_prueba())
    migrada = Orden(vehiculo=vehiculo, usuario=tecnico, notas=f"{A.MARCA_NOTAS} (#1).")
    nueva = Orden(vehiculo=vehiculo, usuario=tecnico, notas="Nivel de Combustible: Lleno")
    db.add_all([migrada, nueva])
    db.flush()

    assert A.mecanicos_de_lo_migrado(db, aplicar=False)[tecnico.nombre] == 1
    assert migrada.mecanico_id is None          # contar no escribe
    A.mecanicos_de_lo_migrado(db, aplicar=True)
    assert (migrada.mecanico.nombre, migrada.usuario_id) == (tecnico.nombre, tecnico.id)
    assert nueva.mecanico_id is None
    # Una segunda pasada no encuentra nada ni duplica al mecánico.
    assert A.mecanicos_de_lo_migrado(db, aplicar=True)[tecnico.nombre] == 0
    assert db.query(Mecanico).filter_by(nombre=tecnico.nombre).count() == 1
