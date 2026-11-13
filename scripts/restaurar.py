"""Restaura un respaldo hecho con respaldar.

En el PC del taller, junto al ejecutable:

    restaurar.exe respaldos\\lubriexpress-20260916-2030.sql.gz

Desde el repositorio:

    .venv/bin/python scripts/restaurar.py respaldos/lubriexpress-20260916-2030.sql.gz

**Pisa la base que apunta DATABASE_URL**: borra el esquema entero y carga el
volcado encima. Por eso pide confirmación escribiendo el nombre de la base.

El esquema se borra antes y no se confía en los DROP del volcado: uno de una
versión anterior no conoce las tablas que se agregaron después, y sus FK le
impiden borrar las viejas. Todo corre en una sola transacción, así que si algo
falla la base queda exactamente como estaba. Un respaldo de una versión
anterior queda con su esquema viejo: el programa avisa que falta correr
`actualizar.exe`.
"""
import gzip
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.respaldar import contenedor, datos_de_conexion  # noqa: E402


def comando_de_restauracion(datos: dict) -> tuple[list[str], dict]:
    entorno = dict(os.environ, PGPASSWORD=datos["password"])
    if shutil.which("psql"):
        return ["psql", "-h", datos["host"], "-p", datos["puerto"], "-U", datos["usuario"],
                "-d", datos["base"], "-v", "ON_ERROR_STOP=1", "-q", "--single-transaction"], entorno
    return ["docker", "exec", "-i", "-e", f"PGPASSWORD={datos['password']}", contenedor(),
            "psql", "-U", datos["usuario"], "-d", datos["base"], "-v", "ON_ERROR_STOP=1", "-q",
            "--single-transaction"], entorno


def sql_de(archivo: Path) -> bytes:
    """El SQL descomprimido. Va por separado porque pasarle el archivo abierto
    a `subprocess` no sirve: Qt no, Python tampoco — `stdin=` usa el descriptor
    del archivo comprimido y psql recibe los bytes del gzip (`0x8b`), no el
    volcado."""
    with gzip.open(archivo, "rb") as entrada:
        return entrada.read()


def sql_con_esquema_limpio(volcado: bytes) -> bytes:
    """El volcado precedido de borrar y recrear el esquema `public`."""
    return b"DROP SCHEMA public CASCADE;\nCREATE SCHEMA public;\n" + volcado


def restaurar(archivo: Path, datos: dict) -> None:
    comando, entorno = comando_de_restauracion(datos)
    # stdout a la basura: psql imprime el resultado de cada setval del volcado
    # y son cien líneas que tapan lo único que importa, que es si falló.
    proceso = subprocess.run(comando, input=sql_con_esquema_limpio(sql_de(archivo)),
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=entorno)
    if proceso.returncode != 0:
        raise SystemExit("psql falló y la base quedó como estaba: no se aplicó nada.\n\n"
                         + proceso.stderr.decode("utf-8", "replace"))


def pasos_pendientes(url: str) -> list[str]:
    """Los pasos de `actualizar.py` que le faltan a la base restaurada.

    Los imports van acá: `restaurar.py` sin argumentos solo imprime la ayuda
    y no tiene por qué exigir una conexión.
    """
    from sqlalchemy import create_engine

    from scripts.actualizar import pendientes

    motor = create_engine(url)
    try:
        with motor.connect() as conexion:
            return [paso.nombre for paso in pendientes(conexion)]
    finally:
        motor.dispose()


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    archivo = Path(argv[0])
    if not archivo.is_file():
        raise SystemExit(f"No existe el archivo {archivo}")
    datos = datos_de_conexion()
    print(f"Se va a RESTAURAR '{archivo.name}' sobre la base '{datos['base']}' "
          f"en {datos['host']}:{datos['puerto']}.")
    print("Todo lo que haya ahí ahora se pierde.")
    if "--si" not in argv and input(f"Escribe el nombre de la base para confirmar: ").strip() != datos["base"]:
        print("Cancelado. Nada se tocó.")
        return 1
    restaurar(archivo, datos)
    print("Restaurado.")
    if pasos_pendientes(os.getenv("DATABASE_URL")):
        print("Este respaldo es de una versión anterior. Corre actualizar.exe antes de "
              "abrir el programa.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
