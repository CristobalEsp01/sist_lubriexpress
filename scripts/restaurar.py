"""Restaura un respaldo hecho con scripts/respaldar.py.

    .venv/bin/python scripts/restaurar.py respaldos/lubriexpress-20260916-2030.sql.gz

**Pisa la base que apunta DATABASE_URL**: el volcado trae DROP de cada tabla.
Por eso pide confirmación escribiendo el nombre de la base.
"""
import gzip
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.respaldar import contenedor, datos_de_conexion  # noqa: E402


def comando_de_restauracion(datos: dict) -> tuple[list[str], dict]:
    import os

    entorno = dict(os.environ, PGPASSWORD=datos["password"])
    if shutil.which("psql"):
        return ["psql", "-h", datos["host"], "-p", datos["puerto"], "-U", datos["usuario"],
                "-d", datos["base"], "-v", "ON_ERROR_STOP=1", "-q"], entorno
    return ["docker", "exec", "-i", "-e", f"PGPASSWORD={datos['password']}", contenedor(),
            "psql", "-U", datos["usuario"], "-d", datos["base"], "-v", "ON_ERROR_STOP=1", "-q"], entorno


def sql_de(archivo: Path) -> bytes:
    """El SQL descomprimido. Va por separado porque pasarle el archivo abierto
    a `subprocess` no sirve: Qt no, Python tampoco — `stdin=` usa el descriptor
    del archivo comprimido y psql recibe los bytes del gzip (`0x8b`), no el
    volcado."""
    with gzip.open(archivo, "rb") as entrada:
        return entrada.read()


def restaurar(archivo: Path, datos: dict) -> None:
    comando, entorno = comando_de_restauracion(datos)
    # stdout a la basura: psql imprime el resultado de cada setval del volcado
    # y son cien líneas que tapan lo único que importa, que es si falló.
    proceso = subprocess.run(comando, input=sql_de(archivo), stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE, env=entorno)
    if proceso.returncode != 0:
        raise SystemExit(f"psql falló:\n{proceso.stderr.decode('utf-8', 'replace')}")


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
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
