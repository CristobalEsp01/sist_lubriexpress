"""Módulo de Ventas de Mostrador (Propuesta 3.3).

Catálogo a la izquierda, carrito y cobro a la derecha. El carrito vive en
memoria (una lista de dicts) hasta que se confirma la venta: recién ahí se
escribe en la base de datos, en una sola transacción, y son los triggers de
Postgres los que descuentan el stock y dejan el rastro en el Kardex — este
módulo nunca toca "stock_actual" directamente (ver database/schema_lubriexpress.sql).
"""
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSplitter, QTabWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from ..auth import Sesion
from ..database import SessionLocal
from ..models import Cliente, DetalleVenta, Producto, Venta
from ..texto import filtro_busqueda
from .comunes import (
    ItemNumerico, barra, bloque_total, clp, con_aviso_vacio, crear_tabla,
    hacer_buscable, layout_de_dialogo, layout_de_pantalla, reordenar,
)
from .tema import ALERTA, CANAL_PANEL, ESPACIO_PANTALLA

COLUMNAS_CATALOGO = ["Nombre", "Marca", "Categoría", "Stock", "Precio"]
COLUMNAS_CARRITO = ["Producto", "Cantidad", "Precio Unit.", "Subtotal"]
COLUMNAS_DETALLE = ["Producto", "Cantidad", "Precio Unit.", "Subtotal"]
COLUMNAS_HISTORIAL = ["Fecha", "Nº Boleta", "Cliente", "Vendedor", "Total"]

CORRELATIVO = re.compile(r"^(.*?)(\d+)$")


def siguiente_boleta(ultima: str | None) -> str:
    """'B-1042' -> 'B-1043'. '000123' -> '000124'. Sin dígitos al final, ''.

    Es una sugerencia, no una asignación: el número de verdad lo manda el
    talonario o el folio del SII. Si el sistema fuera dueño del correlativo,
    bastaría una boleta anulada para que el papel y la base se separaran en
    silencio hasta el cuadre. Por eso se propone y se deja editable.
    """
    calce = CORRELATIVO.match((ultima or "").strip())
    if not calce:
        return ""
    prefijo, digitos = calce.groups()
    return f"{prefijo}{int(digitos) + 1:0{len(digitos)}d}"


class PuntoVentaWidget(QWidget):
    """Venta de mostrador: buscar, agregar al carrito, cobrar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.carrito: list[dict] = []

        # ---------------- Catálogo (izquierda) ----------------
        self.busqueda = QLineEdit(placeholderText="Buscar por nombre, marca o categoría…")
        self.busqueda.setClearButtonEnabled(True)
        self.busqueda.textChanged.connect(self.recargar_catalogo)
        self.busqueda.returnPressed.connect(self.agregar_desde_busqueda)

        self.tabla_catalogo = con_aviso_vacio(
            crear_tabla(COLUMNAS_CATALOGO, ancha=0, orden=0, numericas=(3, 4)),
            "No hay productos activos en el catálogo.",
        )
        self.tabla_catalogo.itemSelectionChanged.connect(self._actualizar_boton_agregar)
        self.tabla_catalogo.doubleClicked.connect(self.agregar_seleccionado)

        self.boton_agregar = QPushButton("Agregar al carrito")
        self.boton_agregar.setEnabled(False)
        self.boton_agregar.clicked.connect(self.agregar_seleccionado)

        self.resumen = QLabel()
        self.resumen.setProperty("clase", "resumen")

        panel_catalogo = QWidget()
        layout_catalogo = QVBoxLayout(panel_catalogo)
        layout_catalogo.setContentsMargins(0, 0, CANAL_PANEL, 0)
        layout_catalogo.setSpacing(ESPACIO_PANTALLA)
        layout_catalogo.addLayout(barra(self.busqueda, self.boton_agregar))
        layout_catalogo.addWidget(self.tabla_catalogo)
        layout_catalogo.addWidget(self.resumen)

        # ---------------- Carrito y cobro (derecha) ----------------
        self.tabla_carrito = con_aviso_vacio(
            crear_tabla(COLUMNAS_CARRITO, ancha=0, orden=0, numericas=(1, 2, 3)),
            "El carrito está vacío.\nBusca un producto y agrégalo.",
        )
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

        self.cliente = hacer_buscable(QComboBox())
        self.cliente.lineEdit().setPlaceholderText("Sin cliente — busca por RUT o nombre")
        self._cargar_clientes()

        self.boleta = QLineEdit(placeholderText="Ej: B-1043")
        self.boleta.returnPressed.connect(self.generar_venta)

        marco_total, self.total = bloque_total()

        self.boton_vaciar = QPushButton("Vaciar carrito")
        self.boton_vaciar.clicked.connect(self.vaciar_carrito)
        self.boton_cobrar = QPushButton("Generar Venta")
        self.boton_cobrar.setProperty("clase", "primario")
        self.boton_cobrar.setEnabled(False)
        self.boton_cobrar.clicked.connect(self.generar_venta)
        # Cobrar necesita carrito Y boleta: el botón lo dice apagándose, en vez
        # de dejarse apretar para responder con un aviso.
        self.boleta.textChanged.connect(self._actualizar_boton_cobrar)

        panel_carrito = QWidget()
        layout_carrito = QVBoxLayout(panel_carrito)
        layout_carrito.setContentsMargins(CANAL_PANEL, 0, 0, 0)
        layout_carrito.setSpacing(ESPACIO_PANTALLA)
        layout_carrito.addLayout(barra_carrito)
        layout_carrito.addWidget(self.tabla_carrito, 1)
        layout_carrito.addWidget(QLabel("Cliente (opcional)"))
        layout_carrito.addWidget(self.cliente)
        layout_carrito.addWidget(QLabel("N.º de boleta *"))
        layout_carrito.addWidget(self.boleta)
        layout_carrito.addWidget(marco_total)
        layout_carrito.addLayout(barra(self.boton_vaciar, self.boton_cobrar, estira=1))

        division = QSplitter(Qt.Horizontal)
        division.setHandleWidth(1)
        division.addWidget(panel_catalogo)
        division.addWidget(panel_carrito)
        division.setSizes([540, 430])

        layout = layout_de_pantalla(self)
        layout.addWidget(division)

        self.recargar_catalogo()

    # ------------------------------------------------------------------
    # Catálogo
    # ------------------------------------------------------------------
    def recargar_catalogo(self) -> None:
        consulta = filtro_busqueda(
            select(Producto).where(Producto.activo.is_(True)).order_by(Producto.nombre),
            self.busqueda.text(),
            Producto.nombre, Producto.marca, Producto.categoria,
        )

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
        self.resumen.setText(f"{len(filas)} producto(s) a la venta")
        if self.busqueda.text().strip():
            self.tabla_catalogo.aviso.setText("Ningún producto coincide con la búsqueda.")
        else:
            self.tabla_catalogo.aviso.setText("No hay productos activos en el catálogo.")
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

    def agregar_desde_busqueda(self) -> None:
        """Enter en la búsqueda: agrega lo seleccionado o, si la búsqueda dejó
        un solo producto, ese. Escribir hasta que quede uno y apretar Enter es
        el camino más corto para quien cobra sin soltar el teclado."""
        if self._producto_seleccionado() is None and self.tabla_catalogo.rowCount() == 1:
            self.tabla_catalogo.selectRow(0)
        self.agregar_seleccionado()

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

        # El stock del carrito se guardó al agregar el producto. Si mientras
        # tanto llegó mercadería, el tope viejo impediría vender lo que ya está
        # en bodega; si se vendió en otra caja, ofrecería de más.
        with SessionLocal() as db:
            stock = db.scalar(
                select(Producto.stock_actual).where(Producto.id == entrada["producto_id"])
            ) or 0
        if stock <= 0:
            QMessageBox.warning(
                self, "Sin stock", f"'{entrada['nombre']}' se quedó sin stock disponible.",
            )
            return
        entrada["stock_disponible"] = stock

        nueva, ok = QInputDialog.getInt(
            self, "Cambiar cantidad",
            f"Cantidad de '{entrada['nombre']}' (stock disponible: {stock}):",
            min(entrada["cantidad"], stock), 1, stock, 1,
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
        self.tabla_carrito.resizeColumnsToContents()
        self.total.setText(clp(total))
        self.boton_quitar.setEnabled(False)
        self._actualizar_boton_cobrar()

    def _actualizar_boton_cobrar(self) -> None:
        self.boton_cobrar.setEnabled(bool(self.carrito) and bool(self.boleta.text().strip()))

    # ------------------------------------------------------------------
    # Cliente
    # ------------------------------------------------------------------
    def showEvent(self, evento) -> None:
        """Al volver a la pestaña se pone todo al día: un cliente recién creado
        aparece, el stock del catálogo refleja lo que pasó en otras pantallas y
        el cursor queda donde empieza toda venta."""
        super().showEvent(evento)
        self._cargar_clientes()
        self.recargar_catalogo()
        if not self.boleta.text().strip():
            self._sugerir_boleta()
        self.busqueda.setFocus()

    def _sugerir_boleta(self) -> None:
        """Propone el correlativo siguiente al de la última venta registrada."""
        with SessionLocal() as db:
            ultima = db.scalar(select(Venta.numero_boleta).order_by(Venta.id.desc()).limit(1))
        self.boleta.setText(siguiente_boleta(ultima))

    def _cargar_clientes(self) -> None:
        seleccionado = self.cliente.currentData()
        self.cliente.clear()
        with SessionLocal() as db:
            clientes = db.scalars(select(Cliente).order_by(Cliente.nombre_completo)).all()
            for c in clientes:
                etiqueta = f"{c.rut} — {c.nombre_completo}" if c.rut else c.nombre_completo
                self.cliente.addItem(etiqueta, c.id)
        # Sin cliente el campo queda vacío, con su texto de fondo: la venta de
        # mostrador sin cliente es el caso normal y no necesita una opción que
        # ocupe el campo como si fuera alguien. Recargar tampoco puede perder al
        # cliente ya elegido para la venta en curso.
        self.cliente.setCurrentIndex(self.cliente.findData(seleccionado))

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
        self.cliente.setCurrentIndex(-1)  # la venta siguiente parte sin cliente
        self._sugerir_boleta()  # deja lista la siguiente
        self._redibujar_carrito()
        self.recargar_catalogo()


class DetalleVentaDialog(QDialog):
    """Ventana emergente que muestra los productos de una venta específica."""

    def __init__(self, venta_id: int, numero_boleta: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Detalle de Venta — Boleta {numero_boleta}")
        self.resize(550, 300)
        self.setModal(True)

        self.tabla = crear_tabla(COLUMNAS_DETALLE, ancha=0, orden=0, numericas=(1, 2, 3))
        marco_total, self.label_total = bloque_total("Total cobrado", menor=True)

        # Sin esto la única salida es la X de la ventana.
        cerrar = QDialogButtonBox(QDialogButtonBox.Close)
        cerrar.rejected.connect(self.reject)

        layout = layout_de_dialogo(self)
        layout.addWidget(self.tabla)
        layout.addWidget(marco_total)
        layout.addWidget(cerrar)

        self._cargar_detalle(venta_id)

    def _cargar_detalle(self, venta_id: int) -> None:
        with SessionLocal() as db:
            detalles = db.scalars(
                select(DetalleVenta)
                .options(joinedload(DetalleVenta.producto))  # sin esto, un SELECT por fila
                .where(DetalleVenta.venta_id == venta_id)
            ).all()
            self.tabla.setSortingEnabled(False)
            self.tabla.setRowCount(len(detalles))
            suma_total = 0

            for fila, det in enumerate(detalles):
                nombre = det.producto.nombre if det.producto else "Producto eliminado"
                subtotal = det.cantidad * det.precio_unitario_cobrado
                suma_total += subtotal

                self.tabla.setItem(fila, 0, QTableWidgetItem(nombre))
                self.tabla.setItem(fila, 1, ItemNumerico(str(det.cantidad), det.cantidad))
                self.tabla.setItem(
                    fila, 2,
                    ItemNumerico(clp(det.precio_unitario_cobrado), det.precio_unitario_cobrado),
                )
                self.tabla.setItem(fila, 3, ItemNumerico(clp(subtotal), subtotal))

        reordenar(self.tabla)
        self.label_total.setText(clp(suma_total))


class HistorialVentasWidget(QWidget):
    """Pestaña para visualizar las ventas ya generadas."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.tabla = con_aviso_vacio(
            crear_tabla(COLUMNAS_HISTORIAL, ancha=2, orden=0, descendente=True, numericas=(4,)),
            "Todavía no hay ventas registradas.\nLas que generes aparecerán acá.",
        )
        self.tabla.doubleClicked.connect(self.abrir_detalle)

        self.resumen = QLabel()
        self.resumen.setProperty("clase", "resumen")

        layout = layout_de_pantalla(self)
        layout.addWidget(self.tabla)
        layout.addWidget(self.resumen)

    def showEvent(self, evento) -> None:
        """Única puerta de entrada al historial: se recarga al mostrarse, así
        que una venta recién generada ya aparece al cambiar de pestaña."""
        super().showEvent(evento)
        self.cargar_ventas()

    def cargar_ventas(self) -> None:
        with SessionLocal() as db:
            ventas = db.scalars(
                select(Venta)
                # Sin los joinedload son dos SELECT por venta listada, y esta
                # consulta corre cada vez que se entra a la pestaña.
                .options(joinedload(Venta.cliente), joinedload(Venta.usuario))
                .order_by(Venta.id.desc())
            ).all()
            self.tabla.setSortingEnabled(False)
            self.tabla.setRowCount(len(ventas))

            for fila, venta in enumerate(ventas):
                cliente_nombre = (
                    venta.cliente.nombre_completo if venta.cliente else "Venta sin cliente"
                )
                vendedor_nombre = venta.usuario.nombre if venta.usuario else "Desconocido"
                fecha = getattr(venta, "fecha_venta", None)
                # Ordenable por el instante real: como texto "%d-%m-%Y" ordena
                # por día del mes. Mismo patrón que el kardex de inventario.
                celda_fecha = ItemNumerico(
                    fecha.strftime("%d-%m-%Y %H:%M") if fecha else "--",
                    fecha.timestamp() if fecha else 0,
                )
                celda_fecha.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                celda_fecha.setData(Qt.UserRole, venta.id)

                self.tabla.setItem(fila, 0, celda_fecha)
                self.tabla.setItem(fila, 1, QTableWidgetItem(venta.numero_boleta))
                self.tabla.setItem(fila, 2, QTableWidgetItem(cliente_nombre))
                self.tabla.setItem(fila, 3, QTableWidgetItem(vendedor_nombre))
                self.tabla.setItem(fila, 4, ItemNumerico(clp(venta.total_final), venta.total_final))

            total = sum(v.total_final for v in ventas)

        reordenar(self.tabla)
        self.resumen.setText(f"{len(ventas)} venta(s) — {clp(total)} en total")

    def abrir_detalle(self) -> None:
        fila = self.tabla.currentRow()
        if fila < 0:
            return

        venta_id = self.tabla.item(fila, 0).data(Qt.UserRole)
        numero_boleta = self.tabla.item(fila, 1).text()

        dialogo = DetalleVentaDialog(venta_id, numero_boleta, self)
        dialogo.exec()


class VentasWidget(QTabWidget):
    """Pestaña Ventas: el punto de venta y el historial, uno al lado del otro."""

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
