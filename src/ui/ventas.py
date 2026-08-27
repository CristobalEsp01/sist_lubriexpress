"""Módulo de Ventas de Mostrador (Propuesta 3.3).

Catálogo a la izquierda, carrito y cobro a la derecha. El carrito vive en
memoria (una lista de dicts) hasta que se confirma la venta: recién ahí se
escribe en la base de datos, en una sola transacción, y son los triggers de
Postgres los que descuentan el stock y dejan el rastro en el Kardex — este
módulo nunca toca "stock_actual" directamente (ver database/schema_lubriexpress.sql).
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSplitter, QTableWidgetItem, QVBoxLayout, QWidget, QTabWidget, QDialog
)
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from ..auth import Sesion
from ..database import SessionLocal
from ..models import Cliente, DetalleVenta, Producto, Venta, Usuario
from .comunes import ItemNumerico, clp, crear_tabla, reordenar
from .tema import ALERTA

COLUMNAS_CATALOGO = ["Nombre", "Marca", "Categoría", "Stock", "Precio"]
COLUMNAS_CARRITO = ["Producto", "Cantidad", "Precio Unit.", "Subtotal"]


class PuntoVentaWidget(QWidget):
    """Venta de mostrador: buscar, agregar al carrito, cobrar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.carrito: list[dict] = []

        # ---------------- Catálogo (izquierda) ----------------
        self.busqueda = QLineEdit(placeholderText="Buscar por nombre, marca o categoría…")
        self.busqueda.setClearButtonEnabled(True)
        self.busqueda.textChanged.connect(self.recargar_catalogo)

        self.tabla_catalogo = crear_tabla(COLUMNAS_CATALOGO, ancha=0, orden=0, numericas=(3, 4))
        self.tabla_catalogo.itemSelectionChanged.connect(self._actualizar_boton_agregar)
        self.tabla_catalogo.doubleClicked.connect(self.agregar_seleccionado)

        self.boton_agregar = QPushButton("Agregar al carrito")
        self.boton_agregar.setEnabled(False)
        self.boton_agregar.clicked.connect(self.agregar_seleccionado)

        barra_catalogo = QHBoxLayout()
        barra_catalogo.setSpacing(10)
        barra_catalogo.addWidget(self.busqueda, 1)
        barra_catalogo.addWidget(self.boton_agregar)

        panel_catalogo = QWidget()
        layout_catalogo = QVBoxLayout(panel_catalogo)
        layout_catalogo.setContentsMargins(0, 0, 10, 0)
        layout_catalogo.setSpacing(8)
        layout_catalogo.addLayout(barra_catalogo)
        layout_catalogo.addWidget(self.tabla_catalogo)

        # ---------------- Carrito y cobro (derecha) ----------------
        self.tabla_carrito = crear_tabla(COLUMNAS_CARRITO, ancha=0, orden=0, numericas=(1, 2, 3))
        self.tabla_carrito.setSortingEnabled(False)  # el orden del carrito es el de agregado
        self.tabla_carrito.doubleClicked.connect(self.cambiar_cantidad)
        self.tabla_carrito.itemSelectionChanged.connect(
            lambda: self.boton_quitar.setEnabled(self.tabla_carrito.currentRow() >= 0)
        )

        titulo_carrito = QLabel("Carrito")
        titulo_carrito.setProperty("clase", "seccion")
        self.boton_quitar = QPushButton("Quitar")
        self.boton_quitar.setEnabled(False)
        self.boton_quitar.clicked.connect(self.quitar_seleccionado)

        barra_carrito = QHBoxLayout()
        barra_carrito.addWidget(titulo_carrito, 1)
        barra_carrito.addWidget(self.boton_quitar)

        self.cliente = QComboBox()
        self._cargar_clientes()

        self.boleta = QLineEdit(placeholderText="N.º de boleta *")

        self.total = QLabel("$0")
        self.total.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fuente_total = self.total.font()
        fuente_total.setPointSize(fuente_total.pointSize() + 6)
        fuente_total.setBold(True)
        self.total.setFont(fuente_total)

        self.boton_vaciar = QPushButton("Vaciar carrito")
        self.boton_vaciar.clicked.connect(self.vaciar_carrito)
        self.boton_cobrar = QPushButton("Generar Venta")
        self.boton_cobrar.setProperty("clase", "primario")
        self.boton_cobrar.setEnabled(False)
        self.boton_cobrar.clicked.connect(self.generar_venta)

        barra_cobro = QHBoxLayout()
        barra_cobro.setSpacing(10)
        barra_cobro.addWidget(self.boton_vaciar)
        barra_cobro.addWidget(self.boton_cobrar, 1)

        panel_carrito = QWidget()
        layout_carrito = QVBoxLayout(panel_carrito)
        layout_carrito.setContentsMargins(10, 0, 0, 0)
        layout_carrito.setSpacing(8)
        layout_carrito.addLayout(barra_carrito)
        layout_carrito.addWidget(self.tabla_carrito, 1)
        layout_carrito.addWidget(QLabel("Cliente (opcional)"))
        layout_carrito.addWidget(self.cliente)
        layout_carrito.addWidget(self.boleta)
        layout_carrito.addWidget(self.total)
        layout_carrito.addLayout(barra_cobro)

        division = QSplitter(Qt.Horizontal)
        division.setHandleWidth(1)
        division.addWidget(panel_catalogo)
        division.addWidget(panel_carrito)
        division.setSizes([560, 380])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.addWidget(division)

        self.recargar_catalogo()

    # ------------------------------------------------------------------
    # Catálogo
    # ------------------------------------------------------------------
    def recargar_catalogo(self) -> None:
        texto = self.busqueda.text().strip()
        consulta = select(Producto).where(Producto.activo.is_(True)).order_by(Producto.nombre)
        if texto:
            patron = f"%{texto}%"
            consulta = consulta.where(or_(
                Producto.nombre.ilike(patron),
                Producto.marca.ilike(patron),
                Producto.categoria.ilike(patron),
            ))

        with SessionLocal() as db:
            productos = db.scalars(consulta).all()
            filas = [
                (p.id, p.nombre, p.marca or "", p.categoria or "", p.stock_actual, p.precio_venta)
                for p in productos
            ]

        self.tabla_catalogo.setSortingEnabled(False)
        self.tabla_catalogo.setRowCount(len(filas))
        for fila, (pid, nombre, marca, categoria, stock, precio) in enumerate(filas):
            for columna, valor in enumerate([nombre, marca, categoria]):
                item = QTableWidgetItem(valor)
                if columna == 0:
                    item.setData(Qt.UserRole, pid)
                self.tabla_catalogo.setItem(fila, columna, item)
            celda_stock = ItemNumerico(str(stock), stock)
            if stock <= 0:
                celda_stock.setForeground(QColor(ALERTA))
            self.tabla_catalogo.setItem(fila, 3, celda_stock)
            self.tabla_catalogo.setItem(fila, 4, ItemNumerico(clp(precio), precio))
        reordenar(self.tabla_catalogo)
        self._actualizar_boton_agregar()

    def _actualizar_boton_agregar(self) -> None:
        self.boton_agregar.setEnabled(self._producto_seleccionado() is not None)

    def _producto_seleccionado(self) -> int | None:
        fila = self.tabla_catalogo.currentRow()
        if fila < 0:
            return None
        return self.tabla_catalogo.item(fila, 0).data(Qt.UserRole)

    def agregar_seleccionado(self) -> None:
        producto_id = self._producto_seleccionado()
        if producto_id is not None:
            self.agregar_producto(producto_id)

    # ------------------------------------------------------------------
    # Carrito
    # ------------------------------------------------------------------
    def agregar_producto(self, producto_id: int, cantidad: int = 1) -> None:
        """Agrega un producto al carrito, sumando a la cantidad si ya estaba.

        Es también el punto de entrada del acceso directo "Generar Venta"
        desde Inventario (Propuesta 3.3): VentanaPrincipal.iniciar_venta_con_producto
        llama a este mismo método.
        """
        with SessionLocal() as db:
            producto = db.get(Producto, producto_id)

        if producto is None or not producto.activo:
            QMessageBox.warning(
                self, "Producto no disponible",
                "Este producto ya no está activo en el catálogo.",
            )
            return
        if producto.stock_actual <= 0:
            QMessageBox.warning(self, "Sin stock", f"'{producto.nombre}' no tiene stock disponible.")
            return

        existente = next((e for e in self.carrito if e["producto_id"] == producto_id), None)
        cantidad_previa = existente["cantidad"] if existente else 0
        nueva_cantidad = cantidad_previa + cantidad

        if nueva_cantidad > producto.stock_actual:
            QMessageBox.warning(
                self, "Stock insuficiente",
                f"Solo quedan {producto.stock_actual} unidad(es) de '{producto.nombre}'.",
            )
            nueva_cantidad = producto.stock_actual
            if nueva_cantidad == cantidad_previa:
                return  # ya estaba en el tope, no hay nada que cambiar

        if existente:
            existente["cantidad"] = nueva_cantidad
            existente["stock_disponible"] = producto.stock_actual
        else:
            self.carrito.append({
                "producto_id": producto.id,
                "nombre": producto.nombre,
                "precio_unitario": producto.precio_venta,
                "cantidad": nueva_cantidad,
                "stock_disponible": producto.stock_actual,
            })
        self._redibujar_carrito()

    def cambiar_cantidad(self) -> None:
        fila = self.tabla_carrito.currentRow()
        if fila < 0:
            return
        entrada = self.carrito[fila]
        nueva, ok = QInputDialog.getInt(
            self, "Cambiar cantidad",
            f"Cantidad de '{entrada['nombre']}' (stock disponible: {entrada['stock_disponible']}):",
            entrada["cantidad"], 1, max(entrada["stock_disponible"], 1), 1,
        )
        if ok:
            entrada["cantidad"] = nueva
            self._redibujar_carrito()

    def quitar_seleccionado(self) -> None:
        fila = self.tabla_carrito.currentRow()
        if fila < 0:
            return
        del self.carrito[fila]
        self._redibujar_carrito()

    def vaciar_carrito(self) -> None:
        if not self.carrito:
            return
        confirmar = QMessageBox.question(
            self, "Vaciar carrito", "¿Quitar todos los productos del carrito?",
        )
        if confirmar == QMessageBox.Yes:
            self.carrito.clear()
            self._redibujar_carrito()

    def _redibujar_carrito(self) -> None:
        self.tabla_carrito.setRowCount(len(self.carrito))
        total = 0
        for fila, entrada in enumerate(self.carrito):
            subtotal = entrada["cantidad"] * entrada["precio_unitario"]
            total += subtotal
            self.tabla_carrito.setItem(fila, 0, QTableWidgetItem(entrada["nombre"]))
            self.tabla_carrito.setItem(
                fila, 1, ItemNumerico(str(entrada["cantidad"]), entrada["cantidad"])
            )
            self.tabla_carrito.setItem(
                fila, 2, ItemNumerico(clp(entrada["precio_unitario"]), entrada["precio_unitario"])
            )
            self.tabla_carrito.setItem(fila, 3, ItemNumerico(clp(subtotal), subtotal))
        self.total.setText(clp(total))
        self.boton_cobrar.setEnabled(bool(self.carrito))
        self.boton_quitar.setEnabled(False)

    # ------------------------------------------------------------------
    # Cliente
    # ------------------------------------------------------------------
    def _cargar_clientes(self) -> None:
        self.cliente.clear()
        self.cliente.addItem("Venta sin cliente registrado", None)
        with SessionLocal() as db:
            clientes = db.scalars(select(Cliente).order_by(Cliente.nombre_completo)).all()
            for c in clientes:
                etiqueta = f"{c.rut} — {c.nombre_completo}" if c.rut else c.nombre_completo
                self.cliente.addItem(etiqueta, c.id)

    # ------------------------------------------------------------------
    # Cobro
    # ------------------------------------------------------------------
    def generar_venta(self) -> None:
        if not Sesion.activa():
            QMessageBox.critical(
                self, "Sesión no válida",
                "No hay un usuario con sesión iniciada. Reinicia la aplicación.",
            )
            return
        if not self.carrito:
            QMessageBox.warning(self, "Carrito vacío", "Agrega al menos un producto antes de cobrar.")
            return
        numero_boleta = self.boleta.text().strip()
        if not numero_boleta:
            QMessageBox.warning(
                self, "Falta la boleta",
                "Ingresa el número de boleta antes de generar la venta.",
            )
            return

        # Revalidación de stock justo antes de cobrar: lo que se vio en el
        # catálogo puede haber quedado desactualizado mientras se armaba el
        # carrito. La última palabra la tiene siempre el CHECK de la base de
        # datos, pero avisar acá evita un error críptico al momento de guardar.
        with SessionLocal() as db:
            for entrada in self.carrito:
                stock_vigente = db.scalar(
                    select(Producto.stock_actual).where(Producto.id == entrada["producto_id"])
                )
                if stock_vigente is None or stock_vigente < entrada["cantidad"]:
                    QMessageBox.warning(
                        self, "Stock insuficiente",
                        f"'{entrada['nombre']}' ya no tiene stock suficiente "
                        f"(disponible: {stock_vigente or 0}).",
                    )
                    self.recargar_catalogo()
                    return

        total = sum(e["cantidad"] * e["precio_unitario"] for e in self.carrito)
        cliente_id = self.cliente.currentData()

        with SessionLocal() as db:
            venta = Venta(
                usuario_id=Sesion.usuario_id,
                cliente_id=cliente_id,
                numero_boleta=numero_boleta,
                total_final=total,
            )
            db.add(venta)
            try:
                db.flush()  # asigna venta.id sin cerrar la transacción
                for entrada in self.carrito:
                    db.add(DetalleVenta(
                        venta_id=venta.id,
                        producto_id=entrada["producto_id"],
                        cantidad=entrada["cantidad"],
                        precio_unitario_cobrado=entrada["precio_unitario"],
                    ))
                db.commit()
            except IntegrityError as e:
                db.rollback()
                detalle = str(e.orig)
                if "ventas_numero_boleta_key" in detalle:
                    QMessageBox.warning(
                        self, "Boleta repetida",
                        f"Ya existe una venta registrada con la boleta {numero_boleta}.",
                    )
                elif "stock_actual" in detalle:
                    QMessageBox.warning(
                        self, "Stock insuficiente",
                        "El stock cambió justo antes de confirmar la venta. "
                        "Revisa el carrito e inténtalo de nuevo.",
                    )
                else:
                    QMessageBox.warning(
                        self, "No se pudo generar la venta",
                        f"La base de datos rechazó la venta:\n\n{detalle}",
                    )
                self.recargar_catalogo()
                return

        QMessageBox.information(
            self, "Venta generada",
            f"Venta registrada por {clp(total)} (boleta {numero_boleta}).",
        )
        self.carrito.clear()
        self.boleta.clear()
        self.cliente.setCurrentIndex(0)
        self._redibujar_carrito()
        self.recargar_catalogo()

class DetalleVentaDialog(QDialog):
    """Ventana emergente que muestra los productos de una venta específica."""
    def __init__(self, venta_id: int, numero_boleta: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Detalle de Venta - Boleta {numero_boleta}")
        self.resize(550, 300)
        self.setModal(True)

        self.tabla = crear_tabla(["Producto", "Cantidad", "Precio Unit.", "Subtotal"], ancha=0, orden=0, numericas=(1, 2, 3))

        # NUEVO: Etiqueta gigante para el total en la parte inferior
        self.label_total = QLabel("Total: $0")
        fuente = self.label_total.font()
        fuente.setPointSize(fuente.pointSize() + 4)
        fuente.setBold(True)
        self.label_total.setFont(fuente)
        self.label_total.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabla)
        layout.addWidget(self.label_total)

        self._cargar_detalle(venta_id)

    def _cargar_detalle(self, venta_id: int) -> None:
        with SessionLocal() as db:
            detalles = db.scalars(select(DetalleVenta).where(DetalleVenta.venta_id == venta_id)).all()
            
            # 1. Apagar el ordenamiento (El antídoto contra el fantasma)
            self.tabla.setSortingEnabled(False)
            self.tabla.setRowCount(len(detalles))
            
            suma_total = 0

            for fila, det in enumerate(detalles):
                producto = db.get(Producto, det.producto_id)
                nombre = producto.nombre if producto else "Producto eliminado"
                subtotal = det.cantidad * det.precio_unitario_cobrado
                
                suma_total += subtotal

                self.tabla.setItem(fila, 0, QTableWidgetItem(nombre))
                self.tabla.setItem(fila, 1, ItemNumerico(str(det.cantidad), det.cantidad))
                self.tabla.setItem(fila, 2, ItemNumerico(clp(det.precio_unitario_cobrado), det.precio_unitario_cobrado))
                self.tabla.setItem(fila, 3, ItemNumerico(clp(subtotal), subtotal))

            # 2. Encender el ordenamiento de nuevo
            self.tabla.setSortingEnabled(True)
            
            # 3. Mostrar la suma total formateada
            self.label_total.setText(f"Total: {clp(suma_total)}")


class HistorialVentasWidget(QWidget):
    """Pestaña para visualizar las ventas ya generadas."""
    def __init__(self, parent=None):
        super().__init__(parent)

        self.tabla = crear_tabla(["Fecha", "Nº Boleta", "Cliente", "Vendedor", "Total"], ancha=0, orden=0, numericas=(4,))
        self.tabla.doubleClicked.connect(self.abrir_detalle)

        self.boton_actualizar = QPushButton("Actualizar Historial")
        self.boton_actualizar.clicked.connect(self.cargar_ventas)

        barra = QHBoxLayout()
        barra.addStretch()
        barra.addWidget(self.boton_actualizar)

        layout = QVBoxLayout(self)
        layout.addLayout(barra)
        layout.addWidget(self.tabla)

        self.cargar_ventas()

    def cargar_ventas(self) -> None:
        with SessionLocal() as db:
            ventas = db.scalars(select(Venta).order_by(Venta.id.desc())).all()
            
            # 1. Apagamos el ordenamiento automático ANTES de llenar la tabla
            self.tabla.setSortingEnabled(False)
            
            self.tabla.setRowCount(len(ventas))

            for fila, venta in enumerate(ventas):
                cliente_nombre = "Venta sin cliente"
                if venta.cliente_id:
                    cliente = db.get(Cliente, venta.cliente_id)
                    if cliente:
                        cliente_nombre = cliente.nombre_completo

                vendedor_nombre = "Desconocido"
                if venta.usuario_id:
                    usuario = db.get(Usuario, venta.usuario_id)
                    if usuario:
                        vendedor_nombre = usuario.nombre

                fecha_str = venta.fecha_venta.strftime("%d-%m-%Y %H:%M") if getattr(venta, "fecha_venta", None) else "--"

                item_fecha = QTableWidgetItem(fecha_str)
                item_fecha.setData(Qt.UserRole, venta.id)

                self.tabla.setItem(fila, 0, item_fecha)
                self.tabla.setItem(fila, 1, QTableWidgetItem(venta.numero_boleta))
                self.tabla.setItem(fila, 2, QTableWidgetItem(cliente_nombre))
                self.tabla.setItem(fila, 3, QTableWidgetItem(vendedor_nombre))
                self.tabla.setItem(fila, 4, ItemNumerico(clp(venta.total_final), venta.total_final))

            # 2. Volvemos a encender el ordenamiento DESPUÉS de llenar todo
            self.tabla.setSortingEnabled(True)

    def abrir_detalle(self) -> None:
        fila = self.tabla.currentRow()
        if fila < 0:
            return

        venta_id = self.tabla.item(fila, 0).data(Qt.UserRole)
        numero_boleta = self.tabla.item(fila, 1).text()

        dialogo = DetalleVentaDialog(venta_id, numero_boleta, self)
        dialogo.exec()


class VentasWidget(QTabWidget):
    """Contenedor principal del módulo de ventas con sus sub-pestañas.
    Reemplaza al VentasWidget original para no romper el main.py ni __init__.py"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.punto_venta = PuntoVentaWidget(self)
        self.historial = HistorialVentasWidget(self)
        
        self.addTab(self.punto_venta, "Nueva Venta")
        self.addTab(self.historial, "Historial de Ventas")
        
    def agregar_producto(self, producto_id: int, cantidad: int = 1) -> None:
        """Delega el acceso directo (desde Inventario) al punto de venta y cambia a esa pestaña."""
        self.setCurrentWidget(self.punto_venta)
        self.punto_venta.agregar_producto(producto_id, cantidad)