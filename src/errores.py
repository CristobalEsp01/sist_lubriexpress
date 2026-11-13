"""El registro de los errores inesperados, sin Qt.

El .exe no tiene consola: lo que revienta dentro de un slot de Qt se imprimía
en ninguna parte. Acá queda escrito en `errores.log`, junto al ejecutable, para
que quien soporte el sistema sepa qué pasó. El aviso en pantalla está en
`src/ui/errores.py`.
"""
import traceback
from datetime import datetime
from pathlib import Path

from sqlalchemy.exc import OperationalError

from .rutas import carpeta_app

ARCHIVO = "errores.log"
# Al pasarlo se conserva la mitad más nueva: el log no puede crecer sin fin
# en un PC que nadie revisa.
TOPE = 512 * 1024
SEPARADOR = "=== "
DETALLE = "\n\nEl detalle quedó en errores.log, junto al programa."


def registrar(tipo, valor, rastro, carpeta: Path | None = None) -> Path:
    """Agrega el error con su fecha y su traceback, y devuelve el archivo."""
    archivo = (carpeta or carpeta_app()) / ARCHIVO
    entrada = (f"{SEPARADOR}{datetime.now():%Y-%m-%d %H:%M:%S} ===\n"
               + "".join(traceback.format_exception(tipo, valor, rastro)) + "\n")
    with archivo.open("a", encoding="utf-8") as salida:
        salida.write(entrada)
    if archivo.stat().st_size > TOPE:
        texto = archivo.read_bytes()[-(TOPE // 2):].decode("utf-8", "ignore")
        inicio = texto.find(SEPARADOR)
        archivo.write_text(texto[inicio:] if inicio >= 0 else "", encoding="utf-8")
    return archivo


def mensaje(valor: BaseException) -> str:
    """Lo que se le dice al usuario: qué pasó y qué hacer, sin el traceback."""
    if isinstance(valor, OperationalError):
        texto = ("Se perdió la conexión con la base de datos. Revisa que PostgreSQL "
                 "esté corriendo y vuelve a intentarlo.")
    else:
        texto = "Ocurrió un error inesperado. Lo que estabas haciendo no se guardó."
    return texto + DETALLE
