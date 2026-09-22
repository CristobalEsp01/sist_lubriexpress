"""Respaldo de la base de datos (Propuesta 3.6).

Genera un volcado comprimido en `respaldos/`, conserva los últimos 30 y, si
`RESPALDO_ONEDRIVE` apunta a una carpeta, deja ahí una copia: el cliente de
OneDrive sube solo lo que cae en su carpeta, así que copiar el archivo es todo
lo que hace falta para el respaldo en la nube.

Uso, en el PC del taller (junto al ejecutable):

    respaldar.exe             # respalda
    respaldar.exe --listar    # qué hay guardado

Desde el repositorio:

    .venv/bin/python scripts/respaldar.py [--listar]

En Windows conviene dejarlo como tarea programada diaria (ver el manual
técnico). Restaurar: scripts/restaurar.py.
"""
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from src.rutas import carpeta_app  # noqa: E402

CUANTOS_SE_CONSERVAN = 30


def contenedor() -> str:
    """El contenedor de Docker donde corre PostgreSQL; solo se usa si pg_dump
    no está instalado en el PC.

    Se lee acá y no al importar el módulo: al importar, el `.env` todavía no
    está cargado, así que configurarlo ahí no haría nada y `.env.example` lo
    documenta como si funcionara.
    """
    load_dotenv(carpeta_app() / ".env")
    return os.getenv("RESPALDO_CONTENEDOR", "lubriexpress-db")


def carpeta_de_respaldos() -> Path:
    """Junto al ejecutable, no dentro del bundle: ver `src/rutas.py`."""
    return carpeta_app() / "respaldos"


def datos_de_conexion() -> dict:
    """Usuario, contraseña, host, puerto y base, sacados de DATABASE_URL."""
    load_dotenv(carpeta_app() / ".env")
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("No hay DATABASE_URL en el entorno ni en el .env.")
    partes = urlparse(url)
    return {
        "usuario": unquote(partes.username or "postgres"),
        "password": unquote(partes.password or ""),
        "host": partes.hostname or "localhost",
        "puerto": str(partes.port or 5432),
        "base": (partes.path or "/").lstrip("/"),
    }


def mayor(version: str) -> str:
    """'16.13 (Debian…)' -> '16'."""
    return version.strip().split()[-1].split(".")[0] if " " in version else version.split(".")[0]


def version_del_servidor(datos: dict) -> str:
    from sqlalchemy import create_engine, text

    url = (f"postgresql+psycopg2://{datos['usuario']}:{datos['password']}"
           f"@{datos['host']}:{datos['puerto']}/{datos['base']}")
    with create_engine(url).connect() as conexion:
        return mayor(conexion.execute(text("SHOW server_version")).scalar())


def version_de(comando: list[str]) -> str | None:
    """La versión mayor de un pg_dump, o None si ese pg_dump no existe."""
    try:
        salida = subprocess.run(comando + ["--version"], capture_output=True, text=True)
    except OSError:
        return None
    return mayor(salida.stdout) if salida.returncode == 0 else None


def comando_de_volcado(datos: dict) -> tuple[list[str], dict]:
    """El pg_dump que hay que usar es el de la misma versión mayor que el
    servidor, y no cualquiera: uno más nuevo escribe órdenes que el servidor
    viejo no entiende al restaurar (`transaction_timeout`, en PostgreSQL 16),
    y el archivo se descubre inservible recién el día que se necesita.

    Se prueba el del sistema —el caso del PC del taller, instalado junto al
    servidor— y el del contenedor, que es como corre en desarrollo.
    """
    entorno = dict(os.environ, PGPASSWORD=datos["password"])
    nombre = contenedor()
    servidor = version_del_servidor(datos)
    del_sistema = ["pg_dump", "-h", datos["host"], "-p", datos["puerto"],
                   "-U", datos["usuario"], "-d", datos["base"], "--clean", "--if-exists"]
    del_contenedor = ["docker", "exec", "-e", f"PGPASSWORD={datos['password']}", nombre,
                      "pg_dump", "-U", datos["usuario"], "-d", datos["base"],
                      "--clean", "--if-exists"]

    candidatos = [(["pg_dump"], del_sistema), (["docker", "exec", nombre, "pg_dump"], del_contenedor)]
    versiones = []
    for prueba, comando in candidatos:
        version = version_de(prueba)
        versiones.append(version)
        if version == servidor:
            return comando, entorno
    raise SystemExit(
        f"Ningún pg_dump disponible es de PostgreSQL {servidor}: "
        f"el del sistema es {versiones[0] or 'inexistente'} y el del contenedor "
        f"'{nombre}' es {versiones[1] or 'inexistente'}. Un volcado hecho con "
        "otra versión no se puede restaurar en este servidor. Instala las "
        "herramientas cliente que correspondan o ajusta RESPALDO_CONTENEDOR."
    )


def respaldos_guardados(carpeta: Path | None = None) -> list[Path]:
    carpeta = carpeta or carpeta_de_respaldos()
    return sorted(carpeta.glob("lubriexpress-*.sql.gz"))


def rotar(carpeta: Path | None = None, cuantos: int = CUANTOS_SE_CONSERVAN) -> list[Path]:
    """Borra los más viejos y devuelve lo que se borró. El nombre lleva la
    fecha, así que ordenar alfabéticamente es ordenar cronológicamente."""
    carpeta = carpeta or carpeta_de_respaldos()
    sobran = respaldos_guardados(carpeta)[:-cuantos] if cuantos else []
    for viejo in sobran:
        viejo.unlink()
    return sobran


def copiar_a_la_nube(archivo: Path) -> Path | None:
    """Copia a la carpeta de OneDrive si está configurada."""
    destino = os.getenv("RESPALDO_ONEDRIVE", "").strip()
    if not destino:
        return None
    carpeta = Path(destino).expanduser()
    if not carpeta.is_dir():
        print(f"Aviso: RESPALDO_ONEDRIVE apunta a '{carpeta}', que no existe. "
              "El respaldo local sí quedó hecho.")
        return None
    return Path(shutil.copy2(archivo, carpeta / archivo.name))


def respaldar(carpeta: Path | None = None) -> Path:
    """Vuelca la base comprimida y devuelve el archivo. Si pg_dump falla, no
    deja un .gz a medias: se escribe en un temporal y se renombra al final."""
    carpeta = carpeta or carpeta_de_respaldos()
    datos = datos_de_conexion()
    comando, entorno = comando_de_volcado(datos)
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = carpeta / f"lubriexpress-{datetime.now():%Y%m%d-%H%M}.sql.gz"
    parcial = archivo.with_suffix(".gz.parcial")

    volcar(comando, parcial, entorno)
    parcial.replace(archivo)
    return archivo


def volcar(comando: list[str], destino: Path, entorno: dict) -> None:
    """Corre `comando` y comprime su salida en `destino`.

    Va por una tubería y no con `stdout=gzip.open(...)`: ahí subprocess usa el
    descriptor del archivo crudo, pg_dump escribe SQL plano dentro de un `.gz`
    y el archivo solo se descubre inservible el día que hay que restaurarlo.
    Si el volcado falla no queda nada: se escribe en un temporal y quien llama
    lo renombra.
    """
    import gzip

    proceso = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=entorno)
    with gzip.open(destino, "wb") as salida:
        shutil.copyfileobj(proceso.stdout, salida)
    proceso.stdout.close()
    error = proceso.stderr.read()
    proceso.wait()
    if proceso.returncode != 0:
        destino.unlink(missing_ok=True)
        raise SystemExit(f"El volcado falló:\n{error.decode('utf-8', 'replace')}")


def main(argv: list[str]) -> int:
    if "--listar" in argv:
        guardados = respaldos_guardados()
        for archivo in guardados:
            print(f"  {archivo.name}  {archivo.stat().st_size / 1024:.0f} KB")
        print(f"{len(guardados)} respaldo(s) en {carpeta_de_respaldos()}")
        return 0

    archivo = respaldar()
    print(f"Respaldo: {archivo}  ({archivo.stat().st_size / 1024:.0f} KB)")
    borrados = rotar()
    if borrados:
        print(f"Se borraron {len(borrados)} respaldo(s) viejos "
              f"(se conservan los últimos {CUANTOS_SE_CONSERVAN}).")
    copia = copiar_a_la_nube(archivo)
    print(f"Copia en la nube: {copia}" if copia
          else "Sin copia en la nube (RESPALDO_ONEDRIVE no está configurado).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
