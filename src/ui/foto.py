"""La foto de un producto en pantalla: el recuadro donde se carga y el panel
que la muestra al elegir un producto.

El pedido del taller: se equivocaban de producto al editarlo y al ingresar
mercadería porque solo veían un nombre, y hay pares casi idénticos
("F. Petroleo P 927x" de Mann y "Filtro de Petroleo P 927x" de STP). La foto
confirma que es el que se tiene en la mano.

La foto se busca en internet: en Chrome, clic derecho → "Copiar imagen", y
"Pegar imagen" (o Ctrl+V) en el recuadro. También se puede soltar o elegir un
archivo. Arrastrar directo desde el navegador no siempre funciona en Windows,
así que no se promete.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog, QFrame, QLabel, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)
from sqlalchemy.exc import SQLAlchemyError

from ..database import SessionLocal
from ..fotos import FotoInvalida, a_imagen, desde_archivo, leer, preparar
from ..models import Producto
from ..precios import con_iva
from .comunes import barra, clp, layout_de_dialogo

LADO_RECUADRO = 200
FILTRO_ARCHIVOS = "Imágenes (*.jpg *.jpeg *.png *.webp *.bmp *.gif)"
SIN_IMAGEN = ("Lo copiado no es una imagen. En Chrome: clic derecho sobre la foto → "
              "Copiar imagen.")


def _con_pixmap(etiqueta: QLabel, imagen: QImage, lado: int) -> None:
    etiqueta.setPixmap(QPixmap.fromImage(imagen).scaled(
        lado, lado, Qt.KeepAspectRatio, Qt.SmoothTransformation))


class RecuadroFoto(QFrame):
    """La foto en el formulario del producto. Solo cambia `datos` cuando lo
    que llegó es una imagen: un error nunca borra la foto que había."""

    def __init__(self, parent=None, editable: bool = True):
        super().__init__(parent)
        self.editable = editable
        self._datos: bytes | None = None
        self._cambiada = False

        self.imagen = QLabel()
        self.imagen.setProperty("clase", "foto")
        self.imagen.setAlignment(Qt.AlignCenter)
        self.imagen.setWordWrap(True)
        self.imagen.setFixedSize(LADO_RECUADRO, LADO_RECUADRO)

        self.boton_pegar = QPushButton("Pegar imagen")
        self.boton_pegar.setToolTip("Copia la foto en Chrome (clic derecho → Copiar imagen) "
                                    "y pégala acá. Ctrl+V también sirve.")
        self.boton_pegar.clicked.connect(self.pegar)
        self.boton_elegir = QPushButton("Elegir archivo…")
        self.boton_elegir.clicked.connect(self.elegir_archivo)
        self.boton_quitar = QPushButton("Quitar foto")
        self.boton_quitar.clicked.connect(self.quitar)
        for boton in (self.boton_pegar, self.boton_elegir, self.boton_quitar):
            boton.setAutoDefault(False)     # Enter guarda el formulario, no pega
            boton.setVisible(editable)

        self.setAcceptDrops(editable)
        # Para que Ctrl+V llegue acá hay que hacer clic en el recuadro antes:
        # en los campos de texto del formulario, Ctrl+V pega texto.
        self.setFocusPolicy(Qt.ClickFocus if editable else Qt.NoFocus)

        # Una pieza dentro de un formulario, no una pantalla: sin margen propio.
        columna = QVBoxLayout()
        columna.setContentsMargins(0, 0, 0, 0)
        columna.addWidget(self.imagen)
        columna.addLayout(barra(self.boton_pegar, self.boton_elegir))
        columna.addWidget(self.boton_quitar)
        columna.addStretch()
        self.setLayout(columna)
        self._mostrar()

    @property
    def datos(self) -> bytes | None:
        return self._datos

    @property
    def cambiada(self) -> bool:
        """Si hay que escribirla al guardar: se pegó, se eligió o se quitó."""
        return self._cambiada

    def cargar(self, datos: bytes | None) -> None:
        """La foto que ya tiene el producto. No cuenta como cambio."""
        self._datos, self._cambiada = datos, False
        self._mostrar()

    def _usar(self, datos: bytes | None) -> None:
        self._datos, self._cambiada = datos, True
        self._mostrar()

    def _mostrar(self) -> None:
        if self._datos is None:
            self.imagen.setPixmap(QPixmap())
            self.imagen.setText("Sin foto" if not self.editable else
                                "Sin foto\n\nCopia la imagen en Chrome y usa «Pegar imagen».")
            self.boton_quitar.setEnabled(False)
            return
        imagen = a_imagen(self._datos)
        if imagen.isNull():
            self.imagen.setPixmap(QPixmap())
            self.imagen.setText("No se pudo mostrar la foto")
        else:
            _con_pixmap(self.imagen, imagen, LADO_RECUADRO - 14)
        self.boton_quitar.setEnabled(self.editable)

    def _desde_mime(self, mime) -> None:
        """Una imagen copiada, o un archivo copiado o soltado."""
        try:
            if mime.hasImage():
                self._usar(preparar(QImage(mime.imageData())))
                return
            locales = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
            if locales:
                self._usar(desde_archivo(Path(locales[0])))
                return
        except FotoInvalida as error:
            QMessageBox.warning(self, "No es una imagen", str(error))
            return
        QMessageBox.warning(self, "No es una imagen", SIN_IMAGEN)

    def pegar(self) -> None:
        if self.editable:
            self._desde_mime(QApplication.clipboard().mimeData())

    def elegir_archivo(self) -> None:
        if not self.editable:
            return
        ruta, _ = QFileDialog.getOpenFileName(self, "Elegir la foto del producto", "",
                                              FILTRO_ARCHIVOS)
        if not ruta:
            return
        try:
            self._usar(desde_archivo(Path(ruta)))
        except FotoInvalida as error:
            QMessageBox.warning(self, "No es una imagen", str(error))

    def quitar(self) -> None:
        if self.editable and self._datos is not None:
            self._usar(None)

    def keyPressEvent(self, evento) -> None:
        if evento.matches(QKeySequence.Paste):
            self.pegar()
            return
        super().keyPressEvent(evento)

    def dragEnterEvent(self, evento) -> None:
        mime = evento.mimeData()
        if self.editable and (mime.hasImage() or any(u.isLocalFile() for u in mime.urls())):
            evento.acceptProposedAction()

    def dropEvent(self, evento) -> None:
        self._desde_mime(evento.mimeData())
        evento.acceptProposedAction()


class PanelFoto(QWidget):
    """La foto del producto elegido y lo que la confirma: nombre, marca,
    repisa, precio y stock. Solo lectura; nunca revienta por la base."""

    ANCHO = 220

    def __init__(self, parent=None, ancho: int = ANCHO):
        super().__init__(parent)
        self.ancho = ancho
        self.estado = "vacio"
        self.setFixedWidth(ancho)

        self.foto = QLabel()
        self.foto.setProperty("clase", "foto")
        self.foto.setAlignment(Qt.AlignCenter)
        self.foto.setWordWrap(True)
        self.foto.setFixedSize(ancho, ancho)
        self.nombre = QLabel()
        self.nombre.setProperty("clase", "seccion")
        self.nombre.setWordWrap(True)
        self.detalle = QLabel()
        self.detalle.setProperty("clase", "resumen")
        self.detalle.setWordWrap(True)

        columna = QVBoxLayout()
        columna.setContentsMargins(0, 0, 0, 0)
        columna.addWidget(self.foto)
        columna.addWidget(self.nombre)
        columna.addWidget(self.detalle)
        columna.addStretch()
        self.setLayout(columna)
        self.mostrar(None)

    def _texto(self, estado: str, texto: str) -> None:
        self.estado = estado
        self.foto.setPixmap(QPixmap())
        self.foto.setText(texto)

    def mostrar(self, producto_id: int | None) -> None:
        if producto_id is None:
            self.nombre.clear()
            self.detalle.clear()
            self._texto("vacio", "Elige un producto")
            return
        try:
            with SessionLocal() as db:
                producto = db.get(Producto, producto_id)
                if producto is None:
                    self.mostrar(None)
                    return
                repisa = producto.ubicacion.descripcion if producto.ubicacion else ""
                nombre, marca = producto.nombre, producto.marca or ""
                precio, stock = int(producto.precio_venta), producto.stock_actual
                datos = leer(db, producto_id)
        except SQLAlchemyError:
            self._texto("sin_base", "No se pudo leer la foto")
            return

        self.nombre.setText(nombre)
        self.detalle.setText("\n".join(filter(None, [
            " · ".join(filter(None, [marca, repisa])),
            f"{clp(con_iva(precio))} con IVA",
            f"Stock {stock}",
        ])))
        if datos is None:
            self._texto("sin_foto", "Sin foto")
            return
        imagen = a_imagen(datos)
        if imagen.isNull():
            self._texto("ilegible", "No se pudo mostrar la foto")
            return
        self.estado = "con_foto"
        self.foto.setText("")
        _con_pixmap(self.foto, imagen, self.ancho - 14)


def ver_foto(producto_id: int, parent=None) -> None:
    """La foto en grande, desde Ventas u Órdenes."""
    dialogo = QDialog(parent)
    dialogo.setWindowTitle("Foto del producto")
    panel = PanelFoto(dialogo, ancho=420)
    panel.mostrar(producto_id)
    cerrar = QDialogButtonBox(QDialogButtonBox.Close)
    cerrar.rejected.connect(dialogo.reject)
    layout = layout_de_dialogo(dialogo)
    layout.addWidget(panel)
    layout.addWidget(cerrar)
    dialogo.exec()
