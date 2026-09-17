"""El respaldo de la base: que el archivo esté comprimido de verdad, que se
pueda leer de vuelta, que se conserven los últimos N y que el volcado lo haga
un pg_dump de la misma versión del servidor.

No corre pg_dump: el volcado se simula con un comando que escribe SQL. Lo que
se prueba es la plomería, que es donde estuvo el error — un `.sql.gz` con SQL
plano adentro solo se descubre el día que hay que restaurarlo.
"""
import gzip
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import respaldar as R  # noqa: E402
from scripts.restaurar import sql_de  # noqa: E402

SQL = "-- volcado de prueba\nCREATE TABLE productos ();\n"


def test_el_respaldo_queda_comprimido_y_se_lee_de_vuelta(tmp_path):
    """Regresión: `stdout=gzip.open(...)` le pasa a subprocess el descriptor
    del archivo crudo, así que el volcado salía sin comprimir; y del otro lado,
    `stdin=gzip.open(...)` le entregaba a psql los bytes del gzip."""
    destino = tmp_path / "respaldo.sql.gz"
    R.volcar([sys.executable, "-c", f"print({SQL!r}, end='')"], destino, {})

    assert destino.read_bytes()[:2] == b"\x1f\x8b"      # gzip de verdad
    assert gzip.open(destino, "rt").read() == SQL
    assert sql_de(destino).decode() == SQL              # lo que recibiría psql


def test_un_volcado_que_falla_no_deja_archivo(tmp_path):
    destino = tmp_path / "respaldo.sql.gz"
    with pytest.raises(SystemExit):
        R.volcar([sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(1)"],
                 destino, {})
    assert not destino.exists()


def test_se_conservan_los_ultimos_y_se_copia_a_la_nube(tmp_path, monkeypatch):
    carpeta, nube = tmp_path / "respaldos", tmp_path / "onedrive"
    carpeta.mkdir()
    nube.mkdir()
    for dia in range(1, 6):
        (carpeta / f"lubriexpress-2026090{dia}-1200.sql.gz").write_bytes(b"x")

    borrados = R.rotar(carpeta, cuantos=3)
    assert [b.name for b in borrados] == [
        "lubriexpress-20260901-1200.sql.gz", "lubriexpress-20260902-1200.sql.gz",
    ]
    assert len(R.respaldos_guardados(carpeta)) == 3

    ultimo = R.respaldos_guardados(carpeta)[-1]
    monkeypatch.delenv("RESPALDO_ONEDRIVE", raising=False)
    assert R.copiar_a_la_nube(ultimo) is None           # sin configurar, no falla
    monkeypatch.setenv("RESPALDO_ONEDRIVE", str(nube))
    assert R.copiar_a_la_nube(ultimo) == nube / ultimo.name
    monkeypatch.setenv("RESPALDO_ONEDRIVE", str(tmp_path / "no-existe"))
    assert R.copiar_a_la_nube(ultimo) is None           # carpeta ausente: avisa y sigue


def test_el_volcado_exige_un_pg_dump_de_la_version_del_servidor(monkeypatch):
    """Un pg_dump más nuevo que el servidor escribe órdenes que este no entiende
    al restaurar (`transaction_timeout` en PostgreSQL 16): el archivo queda
    inservible sin que nadie se entere."""
    datos = {"usuario": "postgres", "password": "x", "host": "localhost",
             "puerto": "55432", "base": "lubriexpress"}
    monkeypatch.setattr(R, "version_del_servidor", lambda _: "16")

    # El del sistema es 18 y el del contenedor 16: gana el del contenedor.
    monkeypatch.setattr(R, "version_de", lambda comando: "18" if comando[0] == "pg_dump" else "16")
    comando, _ = R.comando_de_volcado(datos)
    assert comando[0] == "docker"

    monkeypatch.setattr(R, "version_de", lambda comando: "16" if comando[0] == "pg_dump" else None)
    comando, _ = R.comando_de_volcado(datos)
    assert comando[0] == "pg_dump"

    # Ninguno calza: se niega a escribir un respaldo que no se podría restaurar.
    monkeypatch.setattr(R, "version_de", lambda comando: "18")
    with pytest.raises(SystemExit, match="PostgreSQL 16"):
        R.comando_de_volcado(datos)


@pytest.mark.parametrize("texto, esperado", [
    ("16.13 (Debian 16.13-1.pgdg13+1)", "16"),
    ("pg_dump (PostgreSQL) 18.6", "18"),
    ("16.13", "16"),
])
def test_la_version_mayor_se_lee_de_cualquiera_de_los_dos_formatos(texto, esperado):
    assert R.mayor(texto) == esperado
