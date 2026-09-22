"""Buscar un producto viendo su stock y dónde está guardado.

En el mesón hay repuestos que se llaman casi igual y solo se distinguen por la
marca, el stock o la repisa. Un combo muestra nada más que el nombre, así que
elegir bien obligaba a abrir Inventario en paralelo y volver. Acá se ve todo
junto y se elige con doble click.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidgetItem,
)
from sqlalchemy import select

from ..database import SessionLocal
from ..models import Producto
from ..texto import filtro_busqueda
from .comunes import (
    BADGE_ALERTA, ROL_INSIGNIA, ItemNumerico, ajustar_columnas, barra, clp,
    con_aviso_vacio, crear_tabla, layout_de_dialogo, reordenar,
)
from .tema import ALERTA, ESPACIO_BARRA, fuente_tabular

COLUMNAS = ["Nombre", "Marca", "Categoría", "Stock", "Ubicación", "Precio neto"]
TODAS = "Todas las categorías"


class SelectorProducto(QDialog):
    """Deja `elegido` con el id del producto si se aceptó; None si se canceló."""

    def __init__(self, parent=None, texto_inicial: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Buscar producto")
        self.resize(820, 480)
        self.setModal(True)
        self.elegido: int | None = None

        self.busqueda = QLineEdit()
        self.busqueda.setPlaceholderText("Nombre, marca o categoría…")
        self.busqueda.setClearButtonEnabled(True)
        self.busqueda.textChanged.connect(self.recargar)

        self.categoria = QComboBox()
        self.categoria.currentIndexChanged.connect(self.recargar)

        self.tabla = con_aviso_vacio(
            crear_tabla(COLUMNAS, ancha=0, orden=0, numericas=(3, 5)),
            "No hay productos activos en el catálogo.",
        )
        self.tabla.itemSelectionChanged.connect(
            lambda: self.boton_elegir.setEnabled(self.tabla.selectionModel().hasSelection())
        )
        self.tabla.itemDoubleClicked.connect(lambda _: self.elegir())

        self.boton_elegir = QPushButton("Elegir")
        self.boton_elegir.setProperty("clase", "primario")
        self.boton_elegir.setEnabled(False)
        self.boton_elegir.setDefault(True)
        self.boton_elegir.clicked.connect(self.elegir)

        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.setAutoDefault(False)
        boton_cancelar.clicked.connect(self.reject)

        pie = QHBoxLayout()
        pie.setSpacing(ESPACIO_BARRA)
        pie.addWidget(QLabel())          # el contador de resultados
        pie.addStretch()
        pie.addWidget(boton_cancelar)
        pie.addWidget(self.boton_elegir)
        self.resumen = pie.itemAt(0).widget()

        layout = layout_de_dialogo(self)
        layout.addLayout(barra(self.busqueda, QLabel("Categoría"), self.categoria, estira=0))
        layout.addWidget(self.tabla, 1)
        layout.addLayout(pie)

        self._cargar_categorias()
        self.busqueda.setText(texto_inicial)
        self.recargar()
        self.busqueda.setFocus()

    def _cargar_categorias(self) -> None:
        with SessionLocal() as db:
            categorias = db.scalars(
                select(Producto.categoria).where(Producto.activo.is_(True))
                .where(Producto.categoria.isnot(None)).distinct().order_by(Producto.categoria)
            ).all()
        self.categoria.addItems([TODAS] + list(categorias))

    def recargar(self) -> None:
        consulta = filtro_busqueda(
            select(Producto).where(Producto.activo.is_(True)).order_by(Producto.nombre),
            self.busqueda.text(),
            Producto.nombre, Producto.marca, Producto.categoria,
        )
        if self.categoria.currentIndex() > 0:
            consulta = consulta.where(Producto.categoria == self.categoria.currentText())

        with SessionLocal() as db:
            filas = [
                (p.id, p.nombre, p.marca or "", p.categoria or "", p.stock_actual,
                 p.ubicacion.descripcion if p.ubicacion else "", p.precio_venta, p.stock_critico)
                for p in db.scalars(consulta)
            ]

        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(filas))
        for fila, (pid, nombre, marca, categoria, stock, ubicacion, precio, critico) in enumerate(filas):
            for columna, texto in enumerate([nombre, marca, categoria]):
                item = QTableWidgetItem(texto)
                if columna == 0:
                    item.setData(Qt.UserRole, pid)
                self.tabla.setItem(fila, columna, item)
            self.tabla.setItem(fila, 3, ItemNumerico(str(stock), stock))
            self.tabla.setItem(fila, 4, QTableWidgetItem(ubicacion))
            self.tabla.setItem(fila, 5, ItemNumerico(clp(precio), precio))

            # El stock bajo el mínimo se marca igual que en Inventario: es la
            # razón por la que alguien abre esta ventana en vez de teclear.
            if critico:
                celda = self.tabla.item(fila, 3)
                celda.setData(ROL_INSIGNIA, BADGE_ALERTA)
                celda.setForeground(QColor(ALERTA))
                celda.setFont(fuente_tabular(negrita=True))
        reordenar(self.tabla)
        ajustar_columnas(self.tabla)

        self.resumen.setText(f"{len(filas)} producto(s)")
        self.tabla.aviso.setText(
            "Ningún producto coincide con la búsqueda."
            if self.busqueda.text().strip() or self.categoria.currentIndex() > 0
            else "No hay productos activos en el catálogo."
        )
        self.boton_elegir.setEnabled(self.tabla.selectionModel().hasSelection())

    def elegir(self) -> None:
        fila = self.tabla.currentRow()
        if fila < 0 or not self.tabla.selectionModel().hasSelection():
            return
        self.elegido = self.tabla.item(fila, 0).data(Qt.UserRole)
        self.accept()
