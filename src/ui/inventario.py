"""Mantenedor de Inventario: listado de productos, alta y edición."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
    QTableWidgetItem, QVBoxLayout, QWidget,
)
from sqlalchemy import or_, select

from ..database import SessionLocal
from ..models import Producto, Ubicacion
from .comunes import ItemNumerico, clp, crear_tabla, reordenar

COLUMNAS_PRODUCTO = ["Nombre", "Marca", "Categoría", "Ubicación", "Stock", "Mín.", "Costo", "Venta"]
MAX_CLP = 99_999_999


class FormularioProducto(QDialog):
    """Alta y edición de un producto del inventario."""

    def __init__(self, parent=None, producto_id: int | None = None):
        super().__init__(parent)
        self.producto_id = producto_id
        self.setWindowTitle("Nuevo producto" if producto_id is None else "Editar producto")
        self.setMinimumWidth(420)

        self.nombre = QLineEdit()
        self.marca = QLineEdit()
        self.categoria = QLineEdit()
        self.ubicacion = QComboBox()
        self.ubicacion.setEditable(True)
        self.descripcion = QPlainTextEdit()
        self.descripcion.setFixedHeight(60)
        self.precio_costo = self._campo_pesos()
        self.precio_venta = self._campo_pesos()
        self.stock_actual = QSpinBox(maximum=999_999)
        self.stock_minimo = QSpinBox(maximum=999_999)
        self.activo = QCheckBox("Producto activo")
        self.activo.setChecked(True)

        form = QFormLayout()
        form.addRow("Nombre *", self.nombre)
        form.addRow("Marca", self.marca)
        form.addRow("Categoría", self.categoria)
        form.addRow("Ubicación", self.ubicacion)
        form.addRow("Descripción", self.descripcion)
        form.addRow("Precio costo *", self.precio_costo)
        form.addRow("Precio venta *", self.precio_venta)
        form.addRow("Stock inicial", self.stock_actual)
        form.addRow("Stock mínimo", self.stock_minimo)
        form.addRow("", self.activo)

        botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(botones)

        self._cargar_ubicaciones()
        if producto_id is not None:
            self._cargar_producto()
            # El stock solo se mueve por el kardex; editarlo aquí sería un descuadre sin rastro.
            self.stock_actual.setEnabled(False)
            self.stock_actual.setToolTip(
                "El stock se ajusta con un movimiento de kardex (entrada o ajuste), "
                "no editando el producto."
            )

    @staticmethod
    def _campo_pesos() -> QSpinBox:
        campo = QSpinBox(maximum=MAX_CLP)
        campo.setGroupSeparatorShown(True)
        campo.setPrefix("$ ")
        return campo

    def _cargar_ubicaciones(self) -> None:
        with SessionLocal() as db:
            self._ubicaciones = db.scalars(
                select(Ubicacion.descripcion).order_by(Ubicacion.descripcion)
            ).all()
        self.ubicacion.addItems([""] + list(self._ubicaciones))

    def _cargar_producto(self) -> None:
        with SessionLocal() as db:
            p = db.get(Producto, self.producto_id)
            self.nombre.setText(p.nombre)
            self.marca.setText(p.marca or "")
            self.categoria.setText(p.categoria or "")
            self.ubicacion.setCurrentText(p.ubicacion.descripcion if p.ubicacion else "")
            self.descripcion.setPlainText(p.descripcion or "")
            self.precio_costo.setValue(int(p.precio_costo))
            self.precio_venta.setValue(int(p.precio_venta))
            self.stock_actual.setValue(p.stock_actual)
            self.stock_minimo.setValue(p.stock_minimo)
            self.activo.setChecked(p.activo)

    def accept(self) -> None:
        if not self.nombre.text().strip():
            QMessageBox.warning(self, "Falta el nombre", "El producto necesita un nombre.")
            return
        if self.precio_venta.value() < self.precio_costo.value():
            confirmar = QMessageBox.question(
                self, "Precio bajo el costo",
                "El precio de venta es menor que el costo. ¿Guardar de todas formas?",
            )
            if confirmar != QMessageBox.Yes:
                return
        self.guardar()
        super().accept()

    def guardar(self) -> None:
        with SessionLocal() as db:
            producto = db.get(Producto, self.producto_id) if self.producto_id else Producto()
            producto.nombre = self.nombre.text().strip()
            producto.marca = self.marca.text().strip() or None
            producto.categoria = self.categoria.text().strip() or None
            producto.descripcion = self.descripcion.toPlainText().strip() or None
            producto.precio_costo = self.precio_costo.value()
            producto.precio_venta = self.precio_venta.value()
            producto.stock_minimo = self.stock_minimo.value()
            producto.activo = self.activo.isChecked()
            producto.ubicacion = self._ubicacion_o_crear(db, self.ubicacion.currentText().strip())
            if self.producto_id is None:
                producto.stock_actual = self.stock_actual.value()
                db.add(producto)
            db.commit()
            self.producto_id = producto.id

    @staticmethod
    def _ubicacion_o_crear(db, descripcion: str) -> Ubicacion | None:
        if not descripcion:
            return None
        existente = db.scalar(select(Ubicacion).where(Ubicacion.descripcion == descripcion))
        return existente or Ubicacion(descripcion=descripcion)



class InventarioWidget(QWidget):
    """Listado de productos con búsqueda, alta y edición."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.busqueda = QLineEdit(placeholderText="Buscar por nombre, marca o categoría…")
        self.busqueda.setClearButtonEnabled(True)
        self.busqueda.textChanged.connect(self.recargar)

        self.solo_criticos = QCheckBox("Solo stock crítico")
        self.solo_criticos.toggled.connect(self.recargar)

        boton_nuevo = QPushButton("Nuevo producto")
        boton_nuevo.clicked.connect(self.nuevo)
        boton_editar = QPushButton("Editar")
        boton_editar.clicked.connect(self.editar)

        self.tabla = crear_tabla(COLUMNAS_PRODUCTO, ancha=0, orden=0)  # ordena por Nombre
        self.tabla.doubleClicked.connect(self.editar)

        self.resumen = QLabel()

        barra = QHBoxLayout()
        barra.addWidget(self.busqueda, 1)
        barra.addWidget(self.solo_criticos)
        barra.addWidget(boton_nuevo)
        barra.addWidget(boton_editar)

        layout = QVBoxLayout(self)
        layout.addLayout(barra)
        layout.addWidget(self.tabla)
        layout.addWidget(self.resumen)

        self.recargar()

    def recargar(self) -> None:
        # ponytail: carga la tabla completa en memoria. Con miles de SKU conviene
        # pasar a QAbstractTableModel con paginación; para un lubricentro alcanza.
        texto = self.busqueda.text().strip()
        consulta = select(Producto).order_by(Producto.nombre)
        if texto:
            patron = f"%{texto}%"
            consulta = consulta.where(or_(
                Producto.nombre.ilike(patron),
                Producto.marca.ilike(patron),
                Producto.categoria.ilike(patron),
            ))
        if self.solo_criticos.isChecked():
            consulta = consulta.where(
                Producto.activo.is_(True), Producto.stock_actual <= Producto.stock_minimo
            )

        with SessionLocal() as db:
            productos = db.scalars(consulta).all()
            filas = [
                (p.id, p.nombre, p.marca or "", p.categoria or "",
                 p.ubicacion.descripcion if p.ubicacion else "",
                 p.stock_actual, p.stock_minimo, p.precio_costo, p.precio_venta, p.stock_critico)
                for p in productos
            ]

        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(filas))
        criticos = 0
        for fila, (pid, nombre, marca, categoria, ubicacion, stock, minimo, costo, venta, critico) in enumerate(filas):
            for columna, texto in enumerate([nombre, marca, categoria, ubicacion]):
                item = QTableWidgetItem(texto)
                if columna == 0:
                    item.setData(Qt.UserRole, pid)
                self.tabla.setItem(fila, columna, item)
            numeros = [(str(stock), stock), (str(minimo), minimo), (clp(costo), costo), (clp(venta), venta)]
            for desplazamiento, (texto, valor) in enumerate(numeros):
                self.tabla.setItem(fila, 4 + desplazamiento, ItemNumerico(texto, valor))
            if critico:
                criticos += 1
                # Color sobre el texto y no sobre el fondo: se ve igual en tema claro y oscuro.
                celda = self.tabla.item(fila, 4)
                celda.setForeground(QColor("#c0392b"))
                fuente = QFont(celda.font())
                fuente.setBold(True)
                celda.setFont(fuente)
        reordenar(self.tabla)

        aviso = f" — {criticos} bajo stock mínimo" if criticos else ""
        self.resumen.setText(f"{len(filas)} producto(s){aviso}")

    def _id_seleccionado(self) -> int | None:
        fila = self.tabla.currentRow()
        if fila < 0:
            return None
        return self.tabla.item(fila, 0).data(Qt.UserRole)

    def nuevo(self) -> None:
        if FormularioProducto(self).exec():
            self.recargar()

    def editar(self) -> None:
        producto_id = self._id_seleccionado()
        if producto_id is None:
            QMessageBox.information(self, "Sin selección", "Elige un producto de la lista.")
            return
        if FormularioProducto(self, producto_id).exec():
            self.recargar()


