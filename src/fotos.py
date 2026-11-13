"""La foto de cada producto: cómo se achica, se guarda y se lee.

Cada foto termina en todos los respaldos diarios, así que se guarda chica: el
lado mayor a 480 px y en JPEG, unas decenas de KB en vez de los megas que trae
de internet. Lo hace Qt; el proyecto no depende de Pillow.

Sin widgets: lo usan el formulario de producto, el panel de foto y los
catálogos (src/ui/foto.py y src/ui/catalogo.py).
"""
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter
from sqlalchemy import select

from .models import FotoProducto

LADO_MAXIMO = 480
CALIDAD = 80


class FotoInvalida(ValueError):
    """Lo que se intentó usar como foto no es una imagen que Qt pueda leer."""


def preparar(imagen: QImage) -> bytes:
    """La imagen lista para guardar: sobre blanco, achicada y en JPEG."""
    if imagen.isNull():
        raise FotoInvalida("No es una imagen que se pueda usar como foto.")
    # Una PNG sin fondo pierde la transparencia al pasar a JPEG y el fondo
    # queda negro: se pinta antes sobre blanco, como se ve en la tienda.
    lienzo = QImage(imagen.size(), QImage.Format_RGB32)
    lienzo.fill(Qt.white)
    pintor = QPainter(lienzo)
    pintor.drawImage(0, 0, imagen)
    pintor.end()
    if max(lienzo.width(), lienzo.height()) > LADO_MAXIMO:
        lienzo = lienzo.scaled(LADO_MAXIMO, LADO_MAXIMO, Qt.KeepAspectRatio,
                               Qt.SmoothTransformation)
    datos = QByteArray()
    salida = QBuffer(datos)
    salida.open(QIODevice.WriteOnly)
    escrito = lienzo.save(salida, "JPG", CALIDAD)
    salida.close()
    # Sin el plugin de JPEG (un empaquetado incompleto) Qt no escribe nada, y
    # guardar esos 0 bytes pisaría la foto que había.
    if not escrito or datos.isEmpty():
        raise FotoInvalida("No se pudo convertir la imagen a JPEG. Avisa a quien mantiene "
                           "el sistema: falta un componente del programa.")
    return bytes(datos.data())


def desde_archivo(ruta: Path) -> bytes:
    imagen = QImage(str(ruta))
    if imagen.isNull():
        raise FotoInvalida(f"No se pudo leer «{ruta.name}». Guárdala como JPG o PNG e "
                           "inténtalo de nuevo.")
    return preparar(imagen)


def a_imagen(datos: bytes) -> QImage:
    """Nula si los bytes no se pueden leer: quien muestra decide qué decir."""
    return QImage.fromData(datos)


def leer(db, producto_id: int) -> bytes | None:
    return db.scalar(select(FotoProducto.imagen).where(FotoProducto.producto_id == producto_id))


def guardar(db, producto_id: int, datos: bytes | None) -> None:
    """Pone, reemplaza o (con None) quita la foto. No confirma: va en la
    transacción de quien guarda el producto."""
    foto = db.get(FotoProducto, producto_id)
    if datos is None:
        if foto is not None:
            db.delete(foto)
        return
    if foto is None:
        db.add(FotoProducto(producto_id=producto_id, imagen=datos))
    else:
        foto.imagen = datos


def con_foto(db) -> set[int]:
    """Los productos que tienen foto, sin leer ninguna imagen."""
    return set(db.scalars(select(FotoProducto.producto_id)))
