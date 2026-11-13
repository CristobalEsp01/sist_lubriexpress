"""Los widgets de foto: el recuadro donde se carga y el panel que la muestra.

Lo que no puede pasar: que pegar algo que no es una imagen borre la foto que
había, que alguien sin permiso la cambie, o que el panel quede en blanco sin
decir por qué.
"""
import pytest
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from src.database import SessionLocal
from src.fotos import a_imagen, preparar
from src.models import FotoProducto, Producto, Ubicacion

NOMBRE = "QA Filtro con foto"


@pytest.fixture
def avisos(monkeypatch):
    titulos = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: titulos.append(a[1]))
    return titulos


@pytest.fixture
def productos(app):
    """Uno sin foto y uno con foto, comiteados: el panel lee con su propia sesión."""
    with SessionLocal() as db:
        repisa = Ubicacion(descripcion="QA Bandeja 31")
        sin = Producto(nombre=f"{NOMBRE} (sin)", marca="STP", precio_costo=1,
                       precio_venta=18228, stock_actual=2, ubicacion=repisa)
        con = Producto(nombre=NOMBRE, marca="Mann", precio_costo=1, precio_venta=10000,
                       stock_actual=3, ubicacion=repisa)
        db.add_all([sin, con])
        db.flush()
        imagen = preparar(QImage(300, 200, QImage.Format_RGB32))
        db.add(FotoProducto(producto_id=con.id, imagen=imagen))
        db.commit()
        ids = sin.id, con.id
    yield ids
    with SessionLocal() as db:
        for producto in db.scalars(select(Producto).where(Producto.nombre.like(f"{NOMBRE}%"))):
            db.delete(producto)                       # la foto se va en cascada
        db.flush()
        db.query(Ubicacion).filter_by(descripcion="QA Bandeja 31").delete()
        db.commit()


def test_pegar_texto_avisa_y_no_cambia_la_foto(app, avisos):
    from src.ui.foto import RecuadroFoto

    recuadro = RecuadroFoto()
    previa = preparar(QImage(30, 30, QImage.Format_RGB32))
    recuadro.cargar(previa)
    # La dirección de la imagen, no la imagen: el error más probable al copiar.
    QApplication.clipboard().setText("https://tienda.example/filtro.jpg")
    recuadro.pegar()
    assert avisos == ["No es una imagen"]
    assert recuadro.datos == previa and not recuadro.cambiada


def test_pegar_una_imagen_la_deja_lista_para_guardar(app, avisos, tmp_path):
    from src.ui.foto import RecuadroFoto

    recuadro = RecuadroFoto()
    QApplication.clipboard().setImage(QImage(800, 600, QImage.Format_RGB32))
    recuadro.pegar()
    assert recuadro.cambiada and a_imagen(recuadro.datos).width() == 480

    # Un archivo copiado en el Explorador llega como dirección local.
    QImage(100, 50, QImage.Format_RGB32).save(str(tmp_path / "filtro.png"))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / "filtro.png"))])
    QApplication.clipboard().setMimeData(mime)
    recuadro.pegar()
    assert a_imagen(recuadro.datos).width() == 100
    assert avisos == []


def test_quitar_deja_datos_en_none_y_marca_el_cambio(app):
    from src.ui.foto import RecuadroFoto

    recuadro = RecuadroFoto()
    recuadro.cargar(preparar(QImage(30, 30, QImage.Format_RGB32)))
    recuadro.quitar()
    assert recuadro.datos is None and recuadro.cambiada


def test_sin_permiso_no_se_puede_pegar(app, avisos):
    from src.ui.foto import RecuadroFoto

    recuadro = RecuadroFoto(editable=False)
    QApplication.clipboard().setImage(QImage(80, 80, QImage.Format_RGB32))
    recuadro.pegar()
    recuadro.quitar()
    assert recuadro.datos is None and not recuadro.cambiada
    assert recuadro.boton_elegir.isHidden() and recuadro.boton_quitar.isHidden()
    assert not recuadro.acceptDrops()


def test_el_panel_dice_en_que_estado_esta(app, productos, monkeypatch):
    from src.ui import foto
    from src.ui.foto import PanelFoto

    sin, con = productos
    panel = PanelFoto()
    panel.mostrar(None)
    assert panel.estado == "vacio"

    panel.mostrar(sin)
    assert panel.estado == "sin_foto" and panel.foto.text() == "Sin foto"
    assert "STP · QA Bandeja 31" in panel.detalle.text()
    assert "$21.691 con IVA" in panel.detalle.text()

    panel.mostrar(con)
    assert panel.estado == "con_foto" and not panel.foto.pixmap().isNull()
    assert panel.nombre.text() == NOMBRE

    with SessionLocal() as db:
        db.get(FotoProducto, con).imagen = b"bytes que no son jpeg"
        db.commit()
    panel.mostrar(con)
    assert panel.estado == "ilegible" and panel.foto.text() == "No se pudo mostrar la foto"

    def caida():
        raise OperationalError("SELECT", {}, Exception("servidor detenido"))

    monkeypatch.setattr(foto, "SessionLocal", caida)
    panel.mostrar(con)
    assert panel.estado == "sin_base" and panel.foto.text() == "No se pudo leer la foto"
