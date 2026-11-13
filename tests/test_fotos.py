"""Las fotos de producto: cómo se achican y guardan.

Las imágenes llegan de internet con cualquier tamaño y formato, y cada una
termina en todos los respaldos diarios: tienen que quedar chicas, en JPEG y
sin el fondo negro que deja una PNG transparente al perder el canal alfa.
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QImageReader

from src.fotos import FotoInvalida, a_imagen, con_foto, desde_archivo, guardar, leer, preparar
from src.models import Producto


def test_una_foto_grande_queda_en_480_y_en_jpeg(app):
    datos = preparar(QImage(2000, 1000, QImage.Format_RGB32))
    assert datos[:2] == b"\xff\xd8"
    imagen = a_imagen(datos)
    assert (imagen.width(), imagen.height()) == (480, 240)


def test_un_png_transparente_queda_sobre_blanco(app):
    imagen = QImage(10, 10, QImage.Format_ARGB32)
    imagen.fill(Qt.transparent)
    assert QColor(a_imagen(preparar(imagen)).pixel(5, 5)).lightness() > 245


def test_una_foto_chica_no_se_agranda(app):
    imagen = a_imagen(preparar(QImage(100, 80, QImage.Format_RGB32)))
    assert (imagen.width(), imagen.height()) == (100, 80)


def test_un_archivo_que_no_es_imagen_se_rechaza_con_su_nombre(tmp_path, app):
    (tmp_path / "foto.avif").write_bytes(b"no es imagen")
    with pytest.raises(FotoInvalida, match="foto.avif"):
        desde_archivo(tmp_path / "foto.avif")
    with pytest.raises(FotoInvalida):
        preparar(QImage())
    assert a_imagen(b"bytes corruptos").isNull()


def test_qt_lee_webp(app):
    """Muchas descargas de imágenes de productos vienen en .webp."""
    assert b"webp" in QImageReader.supportedImageFormats()


def test_guardar_reemplaza_y_none_borra(db, app):
    producto = Producto(nombre="QA foto", precio_costo=1, precio_venta=2)
    db.add(producto)
    db.flush()
    assert leer(db, producto.id) is None

    primera = preparar(QImage(50, 50, QImage.Format_RGB32))
    guardar(db, producto.id, primera)
    db.flush()
    assert leer(db, producto.id) == primera
    assert producto.id in con_foto(db)

    segunda = preparar(QImage(60, 40, QImage.Format_RGB32))
    guardar(db, producto.id, segunda)
    db.flush()
    assert leer(db, producto.id) == segunda

    guardar(db, producto.id, None)
    db.flush()
    assert leer(db, producto.id) is None
    assert producto.id not in con_foto(db)


def test_si_qt_no_puede_escribir_el_jpeg_no_se_guarda_una_foto_vacia(app, monkeypatch):
    """Sin el plugin de JPEG (un empaquetado incompleto), save() devuelve False
    y deja 0 bytes: esos 0 bytes pisaban la foto que había."""
    monkeypatch.setattr(QImage, "save", lambda *a, **k: False)
    with pytest.raises(FotoInvalida):
        preparar(QImage(50, 50, QImage.Format_RGB32))
