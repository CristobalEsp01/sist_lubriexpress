"""Mantenedor de Inventario: listado de productos, alta y edición."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
    QSplitter, QTableWidgetItem, QVBoxLayout, QWidget,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..auth import Sesion
from ..database import SessionLocal
from ..models import KardexMovimiento, Producto, Ubicacion, Usuario, Venta
from ..permisos import puede
from ..precios import con_iva
from ..texto import filtro_busqueda, normalizar
from .comunes import (
    BADGE_ACENTO, BADGE_ALERTA, BADGE_EXITO, BADGE_NEUTRAL, ROL_INSIGNIA,
    ItemNumerico, SpinBoxConPrefijo, ajustar_columnas, barra, botonera, clp, con_aviso_vacio,
    crear_tabla,
    exigir_permiso, hacer_buscable, layout_de_dialogo, layout_de_pantalla, reordenar,
)
from .carga_excel import CargaExcelDialog
from .tema import ALERTA, CANAL_PANEL, ESPACIO_BARRA, EXITO, TINTA_SUAVE, fuente_tabular

COLUMNAS_PRODUCTO = ["Nombre", "Marca", "Categoría", "Ubicación", "Stock", "Mín.", "Costo", "Venta neto"]
COLUMNAS_KARDEX = ["Fecha", "Tipo", "Cantidad", "Saldo", "Costo unit.", "Usuario", "Origen"]
COLUMNAS_INGRESO = ["Producto", "Stock Actual", "Ingreso", "Nuevo Stock", "Costo unit."]
MAX_CLP = 99_999_999

ETIQUETAS_MOVIMIENTO = {
    "ENTRADA": "Entrada",
    "SALIDA_VENTA": "Salida por venta",
    "SALIDA_ORDEN": "Salida por orden",
    "AJUSTE_MANUAL": "Ajuste manual",
}


def origen_de(orden_id: int | None, boleta: str | None, venta_id: int | None) -> str:
    """De dónde viene el movimiento, para mostrarlo en una columna."""
    if orden_id:
        return f"Orden #{orden_id}"
    if venta_id:
        return f"Boleta {boleta}" if boleta else f"Venta #{venta_id}"
    return "—"


def movimientos_de(db, producto_id: int) -> list[tuple]:
    """Historial de kardex de un producto, del más reciente al más antiguo.

    Separado del widget para poder probarlo dentro de una transacción que se
    revierte: el kardex es solo de agregado y las pruebas no deben borrarlo.
    """
    filas = db.execute(
        select(
            KardexMovimiento.fecha_movimiento,
            KardexMovimiento.tipo_movimiento,
            KardexMovimiento.cantidad_movida,
            KardexMovimiento.stock_resultante,
            KardexMovimiento.costo_unitario,
            Usuario.nombre,
            KardexMovimiento.orden_id,
            Venta.numero_boleta,
            KardexMovimiento.venta_id,
        )
        .join(Usuario, Usuario.id == KardexMovimiento.usuario_id)
        .outerjoin(Venta, Venta.id == KardexMovimiento.venta_id)
        .where(KardexMovimiento.producto_id == producto_id)
        .order_by(KardexMovimiento.fecha_movimiento.desc(), KardexMovimiento.id.desc())
    ).all()
    return [
        (fecha, ETIQUETAS_MOVIMIENTO.get(tipo, tipo), cantidad, saldo, costo, usuario,
         origen_de(orden_id, boleta, venta_id))
        for fecha, tipo, cantidad, saldo, costo, usuario, orden_id, boleta, venta_id in filas
    ]


class FormularioProducto(QDialog):
    """Alta y edición de un producto del inventario."""

    def __init__(self, parent=None, producto_id: int | None = None):
        super().__init__(parent)
        self.producto_id = producto_id
        self.setWindowTitle("Nuevo producto" if producto_id is None else "Editar producto")
        self.setMinimumWidth(440)

        self.nombre = QLineEdit()
        self.nombre.setPlaceholderText("Ej: Aceite 5W30 Sintético 4L")
        self.marca = QLineEdit()
        self.marca.setPlaceholderText("Ej: Mobil, Castrol, Mann")
        # Combo y no caja de texto: escribir la categoría a mano es como el
        # sistema antiguo llegó a tener "Filtro aire", "Filtro Aire",
        # "FILTRO AIRE" y "Filtr Aire" como cuatro repisas distintas. Acá se
        # elige de las que ya hay, y escribir una nueva sigue siendo posible.
        self.categoria = hacer_buscable(QComboBox(), libre=True)
        self.categoria.lineEdit().setPlaceholderText("Ej: Aceite Motor, Filtro de Aire")
        self.ubicacion = hacer_buscable(QComboBox(), libre=True)
        # En el lineEdit y no en el combo: Qt ignora setPlaceholderText()
        # apenas el combo es editable, y Ubicación quedaba como el único
        # campo del formulario sin una pista de qué se escribe ahí.
        self.ubicacion.lineEdit().setPlaceholderText("Ej: Pasillo 1 - Repisa B")
        self.descripcion = QPlainTextEdit()
        self.descripcion.setPlaceholderText("Detalles técnicos o aplicaciones específicas...")
        self.descripcion.setFixedHeight(65)
        self.precio_costo = self._campo_pesos()
        self.precio_venta = self._campo_pesos()
        # El catálogo guarda netos; el precio que paga el cliente se ve al lado.
        self.precio_con_iva = QLabel(clp(0))
        self.precio_venta.valueChanged.connect(
            lambda neto: self.precio_con_iva.setText(clp(con_iva(neto)))
        )
        self.stock_actual = QSpinBox(maximum=999_999)
        self.stock_minimo = QSpinBox(maximum=999_999)
        self.activo = QCheckBox("Producto activo (disponible en ventas y órdenes)")
        self.activo.setChecked(True)

        form = QFormLayout()
        form.setSpacing(11)
        form.addRow("Nombre *", self.nombre)
        form.addRow("Marca", self.marca)
        form.addRow("Categoría", self.categoria)
        form.addRow("Ubicación", self.ubicacion)
        form.addRow("Descripción", self.descripcion)
        form.addRow("Precio costo *", self.precio_costo)
        form.addRow("Precio venta neto *", self.precio_venta)
        form.addRow("Con IVA (19 %)", self.precio_con_iva)
        form.addRow("Stock inicial", self.stock_actual)
        form.addRow("Stock mínimo", self.stock_minimo)
        form.addRow("", self.activo)

        botones = botonera(self)

        layout = layout_de_dialogo(self)
        layout.addLayout(form)
        layout.addWidget(botones)

        self._cargar_ubicaciones()
        self._cargar_categorias()
        if producto_id is not None:
            self._cargar_producto()
            # El stock solo se mueve por el kardex; editarlo aquí sería un descuadre sin rastro.
            self.stock_actual.setEnabled(False)
            self.stock_actual.setToolTip(
                "El stock se ajusta con un movimiento de kardex (entrada o ajuste), "
                "no editando el producto."
            )

    @staticmethod
    def _campo_pesos() -> SpinBoxConPrefijo:
        campo = SpinBoxConPrefijo(maximum=MAX_CLP)
        campo.setGroupSeparatorShown(True)
        campo.setPrefix("$ ")
        # Nadie ajusta un precio de peso en peso: las flechas solo estorban.
        campo.setButtonSymbols(QSpinBox.NoButtons)
        return campo

    def _cargar_ubicaciones(self) -> None:
        with SessionLocal() as db:
            self._ubicaciones = db.scalars(
                select(Ubicacion.descripcion).order_by(Ubicacion.descripcion)
            ).all()
        self.ubicacion.addItems([""] + list(self._ubicaciones))

    def _cargar_categorias(self) -> None:
        with SessionLocal() as db:
            self._categorias = db.scalars(
                select(Producto.categoria).where(Producto.categoria.is_not(None))
                .distinct().order_by(Producto.categoria)
            ).all()
        self.categoria.addItems([""] + list(self._categorias))

    def _categoria_elegida(self) -> str | None:
        """Lo tecleado, salvo que ya exista escrito de otra forma: ahí vale la
        que existe. Es lo que evita que "filtro aire" nazca al lado de "Filtro
        aire" la primera vez que alguien no mira el desplegable."""
        escrito = self.categoria.currentText().strip()
        for existente in self._categorias:
            if normalizar(existente) == normalizar(escrito):
                return existente
        return escrito or None

    def _cargar_producto(self) -> None:
        with SessionLocal() as db:
            p = db.get(Producto, self.producto_id)
            self.nombre.setText(p.nombre)
            self.marca.setText(p.marca or "")
            self.categoria.setCurrentText(p.categoria or "")
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
            producto.categoria = self._categoria_elegida()
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



class IngresoMercaderiaDialog(QDialog):
    """Ventana para registrar la llegada de nueva mercadería masiva."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ingreso de Mercadería")
        self.resize(600, 400)
        self.setModal(True)

        self.lista_ingreso = []

        self.combo_productos = hacer_buscable(QComboBox())
        self.spin_cantidad = QSpinBox()
        self.spin_cantidad.setRange(1, 10000)

        # La mercadería llega con precios distintos cada vez. Al elegir el
        # producto se propone el costo que tiene hoy: casi siempre no cambió, y
        # obligar a retipearlo invita a dejarlo en cero.
        self.spin_costo = FormularioProducto._campo_pesos()
        self.spin_costo.setToolTip("Lo que costó esta compra. Actualiza el costo del producto.")
        self.combo_productos.currentIndexChanged.connect(self._proponer_costo)

        self.boton_agregar = QPushButton("Añadir a la lista")
        self.boton_agregar.setEnabled(False)
        self.boton_agregar.clicked.connect(self.agregar_a_lista)
        self.combo_productos.currentIndexChanged.connect(
            lambda indice: self.boton_agregar.setEnabled(indice >= 0)
        )
        # Enter en cualquier campo añade a la lista; confirmar el ingreso —que
        # mueve stock— exige un click deliberado.
        self.boton_agregar.setDefault(True)

        barra_superior = barra(
            QLabel("Producto"), self.combo_productos,
            QLabel("Cantidad"), self.spin_cantidad,
            QLabel("Costo unit."), self.spin_costo, self.boton_agregar, estira=1,
        )

        self.tabla = con_aviso_vacio(
            crear_tabla(COLUMNAS_INGRESO, ancha=0, orden=0, numericas=(1, 2, 3, 4)),
            "Elige un producto y una cantidad, y añádelo a la lista.",
        )
        # El orden de la tabla es el de la lista en memoria: quitar_seleccionado
        # indexa `lista_ingreso` por la fila visible, y ordenar las descalzaría.
        self.tabla.setSortingEnabled(False)
        self.tabla.itemSelectionChanged.connect(
            lambda: self.boton_quitar.setEnabled(
                self.tabla.selectionModel().hasSelection()
            )
        )

        self.boton_quitar = QPushButton("Quitar seleccionado")
        self.boton_quitar.setAutoDefault(False)
        self.boton_quitar.setEnabled(False)
        self.boton_quitar.clicked.connect(self.quitar_seleccionado)

        self.boton_confirmar = QPushButton("Confirmar Ingreso")
        self.boton_confirmar.setProperty("clase", "primario")
        self.boton_confirmar.setAutoDefault(False)
        self.boton_confirmar.setEnabled(False)  # se habilita al haber algo en la lista
        self.boton_confirmar.clicked.connect(self.confirmar_ingreso)

        barra_inferior = QHBoxLayout()
        barra_inferior.setSpacing(ESPACIO_BARRA)
        barra_inferior.addWidget(self.boton_quitar)
        barra_inferior.addStretch()
        barra_inferior.addWidget(self.boton_confirmar)

        layout = layout_de_dialogo(self)
        layout.addLayout(barra_superior)
        layout.addWidget(self.tabla)
        layout.addLayout(barra_inferior)

        self._cargar_productos()
        self.combo_productos.setFocus()

    def _cargar_productos(self) -> None:
        self.combo_productos.clear()
        with SessionLocal() as db:
            productos = db.scalars(select(Producto).where(Producto.activo.is_(True)).order_by(Producto.nombre)).all()
            for p in productos:
                # El nombre viaja en los datos, no se lee de currentText(): con
                # el combo editable ese texto puede ser un filtro a medio
                # escribir y quedaría guardado como nombre del producto.
                self.combo_productos.addItem(
                    p.nombre,
                    {"id": p.id, "nombre": p.nombre, "stock": p.stock_actual,
                     "costo": int(p.precio_costo)},
                )
        # Nace vacío, con su texto de fondo. Abrir con el primer producto del
        # catálogo ya elegido convierte un "Añadir" sin mirar en stock sumado al
        # producto equivocado, y eso se descubre recién cuando no cuadra el
        # inventario. Ventas y órdenes ya abren así.
        self.combo_productos.setCurrentIndex(-1)
        self.combo_productos.lineEdit().setPlaceholderText("Busca por nombre o marca")

    def _proponer_costo(self) -> None:
        datos = self.combo_productos.currentData()
        self.spin_costo.setValue(datos["costo"] if datos else 0)

    def agregar_a_lista(self) -> None:
        datos = self.combo_productos.currentData()
        if not datos:
            return

        existente = next(
            (item for item in self.lista_ingreso if item["producto_id"] == datos["id"]), None
        )
        if existente:
            # Dos entradas del mismo producto se suman, y manda el último costo
            # tecleado: es el dato más nuevo que alguien miró.
            existente["cantidad"] += self.spin_cantidad.value()
            existente["costo"] = self.spin_costo.value()
        else:
            self.lista_ingreso.append({
                "producto_id": datos["id"],
                "nombre": datos["nombre"],
                "stock_actual": datos["stock"],
                "cantidad": self.spin_cantidad.value(),
                "costo": self.spin_costo.value(),
            })

        self.spin_cantidad.setValue(1)
        self._redibujar_tabla()

    def quitar_seleccionado(self) -> None:
        fila = self.tabla.currentRow()
        if fila >= 0:
            del self.lista_ingreso[fila]
            self._redibujar_tabla()

    def _redibujar_tabla(self) -> None:
        self.tabla.setRowCount(len(self.lista_ingreso))
        for fila, item in enumerate(self.lista_ingreso):
            nuevo = item["stock_actual"] + item["cantidad"]
            self.tabla.setItem(fila, 0, QTableWidgetItem(item["nombre"]))
            self.tabla.setItem(fila, 1, ItemNumerico(str(item["stock_actual"]), item["stock_actual"]))
            self.tabla.setItem(fila, 2, ItemNumerico(f"+{item['cantidad']}", item["cantidad"]))
            self.tabla.setItem(fila, 3, ItemNumerico(str(nuevo), nuevo))
            self.tabla.setItem(fila, 4, ItemNumerico(clp(item["costo"]), item["costo"]))
        ajustar_columnas(self.tabla)
        hay_lista = bool(self.lista_ingreso)
        self.boton_confirmar.setEnabled(hay_lista)
        self.boton_quitar.setEnabled(hay_lista and self.tabla.selectionModel().hasSelection())

    def confirmar_ingreso(self) -> None:
        if not Sesion.activa():
            QMessageBox.critical(self, "Error", "No hay sesión activa.")
            return

        # Solo se inserta el movimiento: el trigger de la base
        # (fn_aplicar_movimiento_manual) suma el stock y calcula el
        # stock_resultante. Tocar stock_actual acá lo contaría dos veces.
        with SessionLocal() as db:
            for item in self.lista_ingreso:
                db.add(KardexMovimiento(
                    producto_id=item["producto_id"],
                    usuario_id=Sesion.usuario_id,
                    tipo_movimiento="ENTRADA",
                    cantidad_movida=item["cantidad"],
                    costo_unitario=item["costo"],
                ))
                # El costo del catálogo pasa a ser el de esta compra; el de las
                # anteriores queda en su movimiento, que es lo que se consulta
                # después. No se toca el precio de venta: el margen lo decide
                # el taller, no una regla de tres.
                db.get(Producto, item["producto_id"]).precio_costo = item["costo"]
            try:
                db.commit()
            except IntegrityError as e:
                # Sin esto, lo que rechaza la base sale por sys.excepthook y el
                # ingreso "no pasa nada" en pantalla. Es el mismo trato que ya
                # les da ventas, clientes y órdenes a sus escrituras.
                db.rollback()
                QMessageBox.warning(
                    self, "No se pudo registrar el ingreso",
                    f"La base de datos rechazó el movimiento:\n\n{e.orig}",
                )
                return

        QMessageBox.information(self, "Éxito", "Mercadería ingresada correctamente al inventario.")
        self.accept()

class AjusteStockDialog(QDialog):
    """Recuento físico: se anota lo que hay en la repisa y la diferencia entra
    al Kardex como AJUSTE_MANUAL. Es la forma de corregir un stock que no se
    puede reconstruir —el migrado del sistema antiguo, una merma, un error—
    sin perder el rastro de que se corrigió."""

    def __init__(self, parent=None, producto_id: int | None = None):
        super().__init__(parent)
        self.producto_id = producto_id
        with SessionLocal() as db:
            producto = db.get(Producto, producto_id)
            self.nombre, self.stock_actual = producto.nombre, producto.stock_actual
        self.setWindowTitle(f"Ajustar stock — {self.nombre}")
        self.setMinimumWidth(380)

        self.contado = QSpinBox(maximum=999_999)
        self.contado.setValue(self.stock_actual)
        self.diferencia = QLabel()
        self.contado.valueChanged.connect(self._mostrar_diferencia)
        self._mostrar_diferencia()

        form = QFormLayout()
        form.setSpacing(11)
        form.addRow("Stock en el sistema", QLabel(str(self.stock_actual)))
        form.addRow("Stock real contado *", self.contado)
        form.addRow("Ajuste", self.diferencia)

        layout = layout_de_dialogo(self)
        layout.addLayout(form)
        layout.addWidget(botonera(self))
        self.contado.setFocus()
        self.contado.selectAll()

    def _mostrar_diferencia(self) -> None:
        diferencia = self.contado.value() - self.stock_actual
        self.diferencia.setText(f"{diferencia:+d}" if diferencia else "sin cambios")

    def accept(self) -> None:
        if not Sesion.activa():
            QMessageBox.critical(self, "Error", "No hay sesión activa.")
            return
        diferencia = self.contado.value() - self.stock_actual
        if diferencia == 0:
            QMessageBox.information(self, "Sin cambios", "El recuento coincide con el sistema.")
            return
        # Solo el movimiento: el trigger mueve el stock y calcula el saldo.
        with SessionLocal() as db:
            db.add(KardexMovimiento(
                producto_id=self.producto_id, usuario_id=Sesion.usuario_id,
                tipo_movimiento="AJUSTE_MANUAL", cantidad_movida=diferencia,
            ))
            try:
                db.commit()
            except IntegrityError as e:
                db.rollback()
                QMessageBox.warning(
                    self, "No se pudo ajustar",
                    f"La base de datos rechazó el ajuste:\n\n{e.orig}",
                )
                return
        super().accept()


class MinimoPorCategoriaDialog(QDialog):
    """Fija el stock mínimo de toda una categoría de una vez (Propuesta 3.2).

    El mínimo sigue viviendo en cada producto —que es lo que lee
    `vw_stock_critico`— y cualquiera puede sobrescribirlo después desde su
    formulario; esto solo evita teclearlo 2.372 veces. No pasa por Kardex:
    `stock_minimo` no es stock, es el umbral con que se lo compara.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Stock mínimo por categoría")
        self.setMinimumWidth(420)

        self.categoria = hacer_buscable(QComboBox())
        self.categoria.lineEdit().setPlaceholderText("Busca la categoría")
        self.minimo = QSpinBox(maximum=999_999)
        self.cuantos = QLabel()
        self.categoria.currentIndexChanged.connect(self._contar)

        with SessionLocal() as db:
            self._categorias = db.scalars(
                select(Producto.categoria).where(Producto.categoria.is_not(None))
                .distinct().order_by(Producto.categoria)
            ).all()
        self.categoria.addItems(list(self._categorias))
        self.categoria.setCurrentIndex(-1)

        form = QFormLayout()
        form.setSpacing(11)
        form.addRow("Categoría *", self.categoria)
        form.addRow("Stock mínimo", self.minimo)
        form.addRow("", self.cuantos)

        layout = layout_de_dialogo(self)
        layout.addLayout(form)
        layout.addWidget(botonera(self))
        self._contar()

    def _contar(self) -> None:
        categoria = self.categoria.currentText().strip()
        if categoria not in self._categorias:
            self.cuantos.setText("")
            return
        with SessionLocal() as db:
            n = db.scalar(
                select(func.count(Producto.id)).where(Producto.categoria == categoria)
            )
        self.cuantos.setText(f"Se aplicará a {n} producto(s) de esta categoría.")

    def accept(self) -> None:
        categoria = self.categoria.currentText().strip()
        if categoria not in self._categorias:
            QMessageBox.warning(
                self, "Elige una categoría",
                "Escoge una de las categorías que ya existen en el inventario.",
            )
            return
        self.aplicar(categoria, self.minimo.value())
        super().accept()

    @staticmethod
    def aplicar(categoria: str, minimo: int) -> int:
        """Devuelve cuántos productos quedaron con ese mínimo."""
        with SessionLocal() as db:
            afectados = db.query(Producto).filter(Producto.categoria == categoria).update(
                {Producto.stock_minimo: minimo}, synchronize_session=False
            )
            db.commit()
        return afectados


class InventarioWidget(QWidget):
    """Listado de productos con búsqueda, alta y edición. Crear, editar,
    ingresar mercadería, ajustar stock y ver el costo están reservados a
    supervisores (permisos.py); el resto lo ve cualquiera."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.busqueda = QLineEdit(placeholderText="Buscar por nombre, marca o categoría…")
        self.busqueda.setClearButtonEnabled(True)
        self.busqueda.textChanged.connect(self.recargar)

        self.solo_criticos = QCheckBox("Solo stock crítico")
        self.solo_criticos.toggled.connect(self.recargar)

        self.boton_vender = QPushButton("Generar Venta")
        self.boton_vender.setToolTip("Iniciar una venta rápida con el producto seleccionado (Propuesta 3.3)")
        self.boton_vender.setEnabled(False)
        self.boton_vender.clicked.connect(self.generar_venta)

        boton_nuevo = QPushButton("Nuevo producto")
        boton_nuevo.setProperty("clase", "primario")
        boton_nuevo.clicked.connect(self.nuevo)
        self.boton_editar = QPushButton("Editar")
        self.boton_editar.setEnabled(False)
        self.boton_editar.clicked.connect(self.editar)

        self.boton_ingreso = QPushButton("Ingresar Mercadería")
        self.boton_ingreso.clicked.connect(self.abrir_ingreso_mercaderia)
        self.boton_ajuste = QPushButton("Ajustar stock")
        self.boton_ajuste.setEnabled(False)
        self.boton_ajuste.clicked.connect(self.ajustar_stock)
        self.boton_excel = QPushButton("Cargar Excel")
        self.boton_excel.clicked.connect(self.abrir_carga_excel)
        self.boton_minimos = QPushButton("Mínimo por categoría")
        self.boton_minimos.clicked.connect(self.fijar_minimos)

        # El rol manda: el botón nace apagado y lo dice, y el slot vuelve a
        # preguntar. Editar y Ajustar además exigen una fila (recargar_kardex).
        self.supervisa = puede("inventario")
        boton_nuevo.setEnabled(self.supervisa)
        self.boton_ingreso.setEnabled(self.supervisa)
        self.boton_excel.setEnabled(self.supervisa)
        self.boton_minimos.setEnabled(self.supervisa)
        if not self.supervisa:
            for boton in (boton_nuevo, self.boton_editar, self.boton_ingreso,
                          self.boton_ajuste, self.boton_excel, self.boton_minimos):
                boton.setToolTip("Reservado a supervisores y administradores")

        self.tabla = con_aviso_vacio(
            crear_tabla(COLUMNAS_PRODUCTO, ancha=0, orden=0, numericas=(4, 5, 6, 7)),
            "No hay productos registrados.",
        )  # ordena por Nombre
        self.tabla.setColumnHidden(6, not self.supervisa)  # el costo lo ven supervisores
        self.tabla.doubleClicked.connect(self.editar)
        self.tabla.itemSelectionChanged.connect(self.recargar_kardex)

        # Historial de kardex del producto seleccionado. Solo lectura: los
        # movimientos los escriben los triggers, nunca esta pantalla.
        self.tabla_kardex = con_aviso_vacio(
            crear_tabla(COLUMNAS_KARDEX, ancha=6, orden=0, descendente=True, numericas=(2, 3, 4)),
            "Elige un producto para ver sus movimientos.",
        )
        # El costo lo ven los mismos que ven la columna de costo del listado.
        self.tabla_kardex.setColumnHidden(4, not self.supervisa)
        self.titulo_kardex = QLabel()
        self.titulo_kardex.setProperty("clase", "seccion")

        self.resumen = QLabel()
        self.resumen.setProperty("clase", "resumen")

        # Dos filas: buscar y lo que se hace con el producto elegido arriba, y
        # las tareas de bodega abajo. En una sola, los siete botones aplastaban
        # la caja de búsqueda hasta dejarla en "Bus…".
        barra_superior = barra(
            self.busqueda, self.solo_criticos, self.boton_vender, self.boton_editar,
            boton_nuevo, estira=0,
        )
        barra_bodega = barra(
            QLabel("Bodega:"), self.boton_ingreso, self.boton_ajuste, self.boton_excel,
            self.boton_minimos, estira=5,
        )

        arriba = QWidget()
        layout_arriba = QVBoxLayout(arriba)
        layout_arriba.setContentsMargins(0, 0, 0, CANAL_PANEL)
        layout_arriba.addLayout(barra_superior)
        layout_arriba.addLayout(barra_bodega)
        layout_arriba.addWidget(self.tabla)

        abajo = QWidget()
        layout_abajo = QVBoxLayout(abajo)
        layout_abajo.setContentsMargins(0, CANAL_PANEL, 0, 0)
        layout_abajo.addWidget(self.titulo_kardex)
        layout_abajo.addWidget(self.tabla_kardex)

        division = QSplitter(Qt.Vertical)
        division.setHandleWidth(1)
        division.addWidget(arriba)
        division.addWidget(abajo)
        division.setSizes([380, 220])

        layout = layout_de_pantalla(self)
        layout.addWidget(division)
        layout.addWidget(self.resumen)

        self.recargar()

    def showEvent(self, evento) -> None:
        """Una venta o un ingreso hechos en otra pestaña cambian el stock: al
        volver acá la tabla tiene que estar al día, no como se dejó."""
        super().showEvent(evento)
        self.recargar()
        self.busqueda.setFocus()

    def recargar(self) -> None:
        # ponytail: carga la tabla completa en memoria. Sirve para un
        # lubricentro (2.372 productos); con decenas de miles de SKU la salida es
        # QAbstractTableModel con paginación.
        consulta = filtro_busqueda(
            select(Producto).order_by(Producto.nombre),
            self.busqueda.text(),
            Producto.nombre, Producto.marca, Producto.categoria,
        )
        if self.solo_criticos.isChecked():
            # Solo por stock: filtrar además por activo hacía desaparecer
            # productos que el listado sí mostraba y que el resumen contaba
            # como críticos, sin nada en pantalla que lo explicara.
            consulta = consulta.where(Producto.stock_actual <= Producto.stock_minimo)

        with SessionLocal() as db:
            productos = db.scalars(consulta).all()
            filas = [
                (p.id, p.nombre, p.marca or "", p.categoria or "",
                 p.ubicacion.descripcion if p.ubicacion else "",
                 p.stock_actual, p.stock_minimo, p.precio_costo, p.precio_venta,
                 p.stock_critico, p.activo)
                for p in productos
            ]

        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(filas))
        criticos = 0
        valorizado = 0
        for fila, (pid, nombre, marca, categoria, ubicacion, stock, minimo, costo, venta,
                   critico, activo) in enumerate(filas):
            for columna, texto in enumerate([nombre, marca, categoria, ubicacion]):
                item = QTableWidgetItem(texto)
                if columna == 0:
                    item.setData(Qt.UserRole, pid)
                self.tabla.setItem(fila, columna, item)
            numeros = [(str(stock), stock), (str(minimo), minimo), (clp(costo), costo), (clp(venta), venta)]
            for desplazamiento, (texto, valor) in enumerate(numeros):
                self.tabla.setItem(fila, 4 + desplazamiento, ItemNumerico(texto, valor))

            # Un producto inactivo no sale en ventas ni en órdenes. Si la fila
            # no lo dice, el único síntoma es que el producto "no aparece" en
            # otra pantalla y no hay dónde averiguar por qué.
            if not activo:
                for columna in range(self.tabla.columnCount()):
                    celda = self.tabla.item(fila, columna)
                    celda.setForeground(QColor(TINTA_SUAVE))
                    celda.setToolTip("Producto inactivo: no aparece en ventas ni en órdenes")

            valorizado += stock * int(costo)
            if critico:
                criticos += 1
                celda = self.tabla.item(fila, 4)
                celda.setData(ROL_INSIGNIA, BADGE_ALERTA)
                celda.setForeground(QColor(ALERTA))
                celda.setFont(fuente_tabular(negrita=True))
        reordenar(self.tabla)

        if self.busqueda.text().strip():
            self.tabla.aviso.setText("Ningún producto coincide con la búsqueda.")
        elif self.solo_criticos.isChecked():
            self.tabla.aviso.setText("Ningún producto está bajo su stock mínimo.")
        else:
            self.tabla.aviso.setText("No hay productos registrados.")

        aviso = f" — {criticos} bajo stock mínimo" if criticos else ""
        # A precio costo: es la plata que está inmovilizada en la bodega, no lo
        # que se va a vender. Sigue lo que muestra la tabla, así que con un
        # filtro puesto dice cuánto vale esa categoría. Lo ven los mismos que
        # ven la columna de costo.
        if self.supervisa:
            aviso += f" — {clp(valorizado)} a precio costo"
        self.resumen.setText(f"{len(filas)} producto(s){aviso}")
        self.recargar_kardex()

    def recargar_kardex(self) -> None:
        producto_id = self._id_seleccionado()
        hay_seleccion = producto_id is not None
        self.boton_vender.setEnabled(hay_seleccion)
        self.boton_editar.setEnabled(hay_seleccion and self.supervisa)
        self.boton_ajuste.setEnabled(hay_seleccion and self.supervisa)

        if not hay_seleccion:
            self.titulo_kardex.setText("Movimientos")
            self.tabla_kardex.aviso.setText("Elige un producto para ver sus movimientos.")
            self.tabla_kardex.setRowCount(0)
            return

        with SessionLocal() as db:
            nombre = db.get(Producto, producto_id).nombre
            movimientos = movimientos_de(db, producto_id)

        self.titulo_kardex.setText(f"Movimientos de {nombre} ({len(movimientos)})")
        self.tabla_kardex.aviso.setText("Este producto todavía no tiene movimientos.")
        self.tabla_kardex.setSortingEnabled(False)
        self.tabla_kardex.setRowCount(len(movimientos))
        for fila, (fecha, tipo, cantidad, saldo, costo, usuario, origen) in enumerate(movimientos):
            marca_tiempo = fecha.timestamp() if fecha else 0
            texto_fecha = fecha.strftime("%d-%m-%Y %H:%M") if fecha else ""
            # Monoespaciada para que las fechas calcen, pero a la izquierda:
            # una fecha alineada a la derecha se lee como si fuera una cifra.
            celda_fecha = ItemNumerico(texto_fecha, marca_tiempo)
            celda_fecha.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.tabla_kardex.setItem(fila, 0, celda_fecha)

            item_tipo = QTableWidgetItem(tipo)
            if tipo == "Entrada":
                item_tipo.setData(ROL_INSIGNIA, BADGE_EXITO)
            elif tipo == "Ajuste manual":
                item_tipo.setData(ROL_INSIGNIA, BADGE_ACENTO)
            elif "Salida" in tipo:
                item_tipo.setData(ROL_INSIGNIA, BADGE_NEUTRAL)
            self.tabla_kardex.setItem(fila, 1, item_tipo)

            celda_cant = ItemNumerico(f"{cantidad:+d}", cantidad)
            if cantidad < 0:
                celda_cant.setForeground(QColor(ALERTA))
            elif cantidad > 0:
                celda_cant.setForeground(QColor(EXITO))
            self.tabla_kardex.setItem(fila, 2, celda_cant)

            self.tabla_kardex.setItem(fila, 3, ItemNumerico(str(saldo), saldo))
            # Solo las entradas traen costo; una salida o un ajuste no compran nada.
            self.tabla_kardex.setItem(
                fila, 4, ItemNumerico(clp(costo) if costo is not None else "—", costo or 0))
            self.tabla_kardex.setItem(fila, 5, QTableWidgetItem(usuario))
            self.tabla_kardex.setItem(fila, 6, QTableWidgetItem(origen))
        reordenar(self.tabla_kardex)

    def _id_seleccionado(self) -> int | None:
        fila = self.tabla.currentRow()
        if fila < 0:
            return None
        return self.tabla.item(fila, 0).data(Qt.UserRole)

    def nuevo(self) -> None:
        if not exigir_permiso("inventario", self):
            return
        if FormularioProducto(self).exec():
            self.recargar()

    def editar(self) -> None:
        producto_id = self._id_seleccionado()
        if producto_id is None:
            return  # el botón está apagado; solo queda el doble click al vacío
        if not exigir_permiso("inventario", self):
            return
        if FormularioProducto(self, producto_id).exec():
            self.recargar()

    def ajustar_stock(self) -> None:
        producto_id = self._id_seleccionado()
        if producto_id is None or not exigir_permiso("inventario", self):
            return
        if AjusteStockDialog(self, producto_id).exec():
            self.recargar()

    def generar_venta(self) -> None:
        """Acceso directo acordado en la propuesta (Sec 3.3)."""
        producto_id = self._id_seleccionado()
        if producto_id is None:
            return
        self.window().iniciar_venta_con_producto(producto_id)

    def fijar_minimos(self) -> None:
        if not exigir_permiso("inventario", self):
            return
        if MinimoPorCategoriaDialog(self).exec():
            self.recargar()

    def abrir_carga_excel(self) -> None:
        if not exigir_permiso("inventario", self):
            return
        if CargaExcelDialog(self).exec():
            self.recargar()

    def abrir_ingreso_mercaderia(self) -> None:
        if not exigir_permiso("inventario", self):
            return
        dialogo = IngresoMercaderiaDialog(self)
        if dialogo.exec():
            # Si el usuario confirma, recargamos la tabla principal para ver los nuevos números
            self.recargar()

