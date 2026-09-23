"""Catálogo con buscador de Órdenes y Ventas: marca, stock, ubicación y precio.

Se arma una vez y al teclear solo oculta filas (~10 ms por tecla; consultar y
rearmar la tabla costaba ~180). El stock mostrado puede quedar viejo: quien
agrega lo relee de la base.

Entrega las piezas sueltas para que cada pantalla las ubique con sus márgenes.
"""
from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QComboBox, QLabel, QLineEdit, QPushButton, QTabBar, QTableWidgetItem,
)
from sqlalchemy import select

from ..database import SessionLocal
from ..models import Producto, Servicio, Ubicacion
from ..texto import normalizar
from .comunes import (
    BADGE_ALERTA, ROL_INSIGNIA, ItemNumerico, clp, con_aviso_vacio, crear_tabla, reordenar,
)
from .tema import ALERTA, fuente_tabular

COLUMNAS = ["Nombre", "Marca", "Stock", "Ubicación", "Precio neto"]
# Texto de búsqueda, normalizado una vez al cargar.
ROL_CLAVE = Qt.UserRole + 1
ROL_CATEGORIA = Qt.UserRole + 2
TODAS = "Todas las categorías"
PESTANAS = ["Todo", "Productos", "Servicios"]
FLECHAS = (Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown)
# Tope de ancho de Marca y Ubicación: ajustadas a su texto más largo dejaban
# el nombre en tres letras.
TOPES = {1: 130, 3: 90}


class Catalogo(QObject):
    """`elegido` lleva {"producto_id": n} o {"servicio_id": n}, que es
    exactamente lo que se guarda en una línea de orden."""

    elegido = Signal(dict)

    def __init__(self, parent=None, servicios: bool = False, boton: str = "Agregar"):
        super().__init__(parent)
        self.servicios = servicios

        self.busqueda = QLineEdit()
        self.busqueda.setPlaceholderText(
            ("Buscar producto o servicio" if servicios else "Buscar producto")
            + ": nombre, marca, categoría o repisa…"
        )
        self.busqueda.setClearButtonEnabled(True)
        self.busqueda.textChanged.connect(self.filtrar)
        self.busqueda.returnPressed.connect(self.elegir)
        self.busqueda.installEventFilter(self)

        self.categoria = QComboBox()
        # Cerrado no pide el ancho de la categoría más larga.
        self.categoria.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.categoria.setMinimumContentsLength(16)
        self.categoria.currentIndexChanged.connect(self.filtrar)
        # Solo donde hay servicios: en Ventas todo es producto.
        self.pestanas = None
        if servicios:
            self.pestanas = QTabBar()
            for nombre in PESTANAS:
                self.pestanas.addTab(nombre)
            self.pestanas.setExpanding(False)
            self.pestanas.setDrawBase(False)
            # Sin flechas: con ellas Qt le da menos ancho y corta "Servicios".
            self.pestanas.setUsesScrollButtons(False)
            self.pestanas.currentChanged.connect(self._al_cambiar_pestana)

        self.tabla = con_aviso_vacio(crear_tabla(COLUMNAS, ancha=0, orden=0, numericas=(2, 4)), "")
        self.tabla.itemSelectionChanged.connect(self._actualizar_boton)
        self.tabla.doubleClicked.connect(self.elegir)

        self.boton = QPushButton(boton)
        self.boton.setAutoDefault(False)
        self.boton.setEnabled(False)
        self.boton.clicked.connect(self.elegir)

        self.resumen = QLabel()
        self.resumen.setProperty("clase", "resumen")

    def cargar(self) -> None:
        """Relee el catálogo: al abrir la pantalla o tras mover stock."""
        with SessionLocal() as db:
            productos = db.execute(
                select(Producto.id, Producto.nombre, Producto.marca, Producto.categoria,
                       Producto.stock_actual, Producto.stock_minimo, Ubicacion.descripcion,
                       Producto.precio_venta)
                .outerjoin(Ubicacion, Producto.ubicacion_id == Ubicacion.id)
                .where(Producto.activo.is_(True))
            ).all()
            servicios = db.execute(
                select(Servicio.id, Servicio.nombre, Servicio.categoria, Servicio.precio_venta)
                .where(Servicio.activo.is_(True))
            ).all() if self.servicios else []

        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(productos) + len(servicios))
        for fila, producto in enumerate(productos):
            pid, nombre, marca, categoria, stock, minimo, repisa, precio = producto
            self._fila(fila, {"producto_id": pid}, nombre, marca or "", repisa or "", int(precio),
                       f"{nombre} {marca or ''} {categoria or ''} {repisa or ''}", categoria)
            celda = ItemNumerico(str(stock), stock)
            # Bajo el mínimo, marcado como en Inventario.
            if stock <= minimo:
                celda.setData(ROL_INSIGNIA, BADGE_ALERTA)
                celda.setForeground(QColor(ALERTA))
                celda.setFont(fuente_tabular(negrita=True))
            self.tabla.setItem(fila, 2, celda)
        for fila, (sid, nombre, categoria, precio) in enumerate(servicios, len(productos)):
            self._fila(fila, {"servicio_id": sid}, nombre, "Servicio", "", int(precio),
                       f"{nombre} servicio {categoria or ''}", categoria)
            self.tabla.setItem(fila, 2, ItemNumerico("", -1))   # la mano de obra no tiene stock
        reordenar(self.tabla)
        for columna, tope in TOPES.items():
            self.tabla.setColumnWidth(columna, min(self.tabla.columnWidth(columna), tope))
        self._llenar_categorias()
        self.filtrar()

    def _fila(self, fila: int, item: dict, nombre: str, marca: str, repisa: str, precio: int,
              clave: str, categoria: str | None) -> None:
        celda = QTableWidgetItem(nombre)
        celda.setData(Qt.UserRole, item)
        celda.setData(ROL_CLAVE, normalizar(clave))
        celda.setData(ROL_CATEGORIA, categoria or "")
        self.tabla.setItem(fila, 0, celda)
        self.tabla.setItem(fila, 1, QTableWidgetItem(marca))
        self.tabla.setItem(fila, 3, QTableWidgetItem(repisa))
        self.tabla.setItem(fila, 4, ItemNumerico(clp(precio), precio))

    def _pestana(self) -> int:
        """0 todo, 1 productos, 2 servicios."""
        return self.pestanas.currentIndex() if self.pestanas else 0

    @staticmethod
    def _de_la_pestana(item: dict, pestana: int) -> bool:
        return pestana == 0 or ("producto_id" in item) == (pestana == 1)

    def _llenar_categorias(self) -> None:
        """Las categorías de la pestaña actual; si la elegida ya no está, se suelta."""
        elegida, pestana = self.categoria.currentText(), self._pestana()
        categorias = sorted({
            celda.data(ROL_CATEGORIA)
            for celda in (self.tabla.item(f, 0) for f in range(self.tabla.rowCount()))
            if celda.data(ROL_CATEGORIA) and self._de_la_pestana(celda.data(Qt.UserRole), pestana)
        }, key=str.casefold)
        self.categoria.blockSignals(True)
        self.categoria.clear()
        self.categoria.addItems([TODAS] + categorias)
        self.categoria.setCurrentText(elegida if elegida in categorias else TODAS)
        self.categoria.blockSignals(False)

    def _al_cambiar_pestana(self, *_) -> None:
        self._llenar_categorias()
        self.filtrar()

    def filtrar(self, *_) -> None:
        """Cada palabra debe estar en nombre, marca, categoría o repisa, en
        cualquier orden. La pestaña y la categoría acotan encima."""
        agujas = [normalizar(palabra) for palabra in self.busqueda.text().split()]
        categoria = self.categoria.currentText() if self.categoria.currentIndex() > 0 else None
        pestana, visibles = self._pestana(), 0
        self.tabla.setUpdatesEnabled(False)
        for fila in range(self.tabla.rowCount()):
            celda = self.tabla.item(fila, 0)
            clave = celda.data(ROL_CLAVE)
            oculta = (not all(aguja in clave for aguja in agujas)
                      or not self._de_la_pestana(celda.data(Qt.UserRole), pestana)
                      or (categoria is not None and celda.data(ROL_CATEGORIA) != categoria))
            self.tabla.setRowHidden(fila, oculta)
            visibles += not oculta
        self.tabla.setUpdatesEnabled(True)
        # Lo elegido que quedó oculto no se agrega con Enter.
        if self.tabla.currentRow() >= 0 and self.tabla.isRowHidden(self.tabla.currentRow()):
            self.tabla.clearSelection()
        self.resumen.setText(f"{visibles} de {self.tabla.rowCount()}")
        self.tabla.aviso.setText("Nada coincide con la búsqueda."
                                 if agujas or categoria or pestana
                                 else "No hay nada activo en el catálogo.")
        self.tabla.aviso.setVisible(visibles == 0)
        self._actualizar_boton()

    def visibles(self) -> list[int]:
        return [f for f in range(self.tabla.rowCount()) if not self.tabla.isRowHidden(f)]

    def seleccionado(self) -> dict | None:
        fila = self.tabla.currentRow()
        if (fila < 0 or self.tabla.isRowHidden(fila)
                or not self.tabla.selectionModel().hasSelection()):
            return None
        return self.tabla.item(fila, 0).data(Qt.UserRole)

    def _a_agregar(self) -> dict | None:
        """Lo seleccionado o, si la búsqueda dejó uno solo, ese."""
        elegido = self.seleccionado()
        if elegido is None:
            visibles = self.visibles()
            if len(visibles) == 1:
                elegido = self.tabla.item(visibles[0], 0).data(Qt.UserRole)
        return elegido

    def _actualizar_boton(self) -> None:
        self.boton.setEnabled(self._a_agregar() is not None)

    def elegir(self, *_) -> None:
        elegido = self._a_agregar()
        if elegido is None:
            return
        self.elegido.emit(elegido)
        # Lo tecleado queda seleccionado: el siguiente ítem se escribe encima.
        self.busqueda.setFocus()
        self.busqueda.selectAll()

    def eventFilter(self, objeto, evento) -> bool:
        # Las flechas mueven la fila elegida sin salir del campo.
        if evento.type() == QEvent.KeyPress and evento.key() in FLECHAS:
            QApplication.sendEvent(self.tabla, evento)
            return True
        return False
