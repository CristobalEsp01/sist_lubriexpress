"""Módulo de Órdenes de Trabajo del taller.

El flujo es el que describió Fabián imitando el programa actual: primero el
cliente, después su vehículo, y recién entonces se abre la orden — insumos al
centro, kilometraje, combustible y observaciones al lateral.

Igual que en ventas, la orden se escribe en una sola transacción y son los
triggers de Postgres los que descuentan el stock y dejan el rastro en el Kardex:
este módulo nunca toca "stock_actual" (ver database/schema_lubriexpress.sql).
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox,
    QSplitter, QStackedWidget, QTabWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)
from sqlalchemy import String, cast, select
from sqlalchemy.exc import IntegrityError

from ..auth import Sesion
from ..database import SessionLocal
from ..models import Cliente, DetalleOrden, Orden, Producto, Usuario, Vehiculo
from ..texto import filtro_busqueda
from .clientes import FormularioCliente, FormularioVehiculo
from .comunes import (
    ItemNumerico, barra, bloque_total, clp, con_aviso_vacio, crear_tabla,
    hacer_buscable, layout_de_dialogo, layout_de_pantalla, reordenar,
)
from .tema import CANAL_PANEL, ESPACIO_PANTALLA, fuente_tabular

COLUMNAS_CARRITO = ["Producto", "Cant.", "Precio Unit.", "Subtotal"]
COLUMNAS_DETALLE = ["Producto", "Cant.", "Precio Unit.", "Subtotal"]
COLUMNAS_HISTORIAL = ["ID OT", "Fecha", "Cliente", "Patente", "Vehículo", "Mecánico", "Total"]
NIVELES_COMBUSTIBLE = ["No registrado", "Reserva", "1/4", "Medio", "3/4", "Lleno"]

REPOSO = "Seleccione 'Nueva Orden' para comenzar."


class AsistenteNuevaOrden(QDialog):
    """Embudo de selección: Cliente -> Vehículo antes de abrir la orden."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nueva Orden - Paso 1: Cliente")
        self.resize(450, 200)
        self.setModal(True)

        self.cliente_id = None
        self.vehiculo_id_seleccionado = None
        self.paginas = QStackedWidget()

        # --- PÁGINA 1: SELECCIÓN DE CLIENTE ---
        self.combo_clientes = hacer_buscable(QComboBox())
        self.combo_clientes.lineEdit().setPlaceholderText("Busca por RUT o nombre")
        self._cargar_clientes()

        self.boton_nuevo_cliente = QPushButton("Crear Cliente")
        self.boton_nuevo_cliente.clicked.connect(self.crear_cliente)

        self.boton_siguiente = QPushButton("Siguiente ->")
        self.boton_siguiente.setProperty("clase", "primario")
        self.boton_siguiente.clicked.connect(self.avanzar_a_vehiculos)

        barra_cli = barra(self.boton_nuevo_cliente, self.boton_siguiente)
        barra_cli.insertStretch(1, 1)

        self.pagina_cliente = QWidget()
        layout_cli = QVBoxLayout(self.pagina_cliente)
        # Los márgenes de la ventana ya los puso layout_de_dialogo(): repetirlos
        # acá dejaría la página del stack con el doble de aire que el diálogo.
        layout_cli.setContentsMargins(0, 0, 0, 0)
        layout_cli.setSpacing(ESPACIO_PANTALLA)
        layout_cli.addWidget(QLabel("Selecciona el Cliente titular:"))
        layout_cli.addWidget(self.combo_clientes)
        layout_cli.addStretch()
        layout_cli.addLayout(barra_cli)

        # --- PÁGINA 2: SELECCIÓN DE VEHÍCULO ---
        self.combo_vehiculos = hacer_buscable(QComboBox())
        self.combo_vehiculos.lineEdit().setPlaceholderText("Busca por patente, marca o modelo")

        self.boton_volver = QPushButton("<- Volver")
        self.boton_volver.clicked.connect(self.volver_a_clientes)

        self.boton_nuevo_vehiculo = QPushButton("Añadir Vehículo")
        self.boton_nuevo_vehiculo.clicked.connect(self.crear_vehiculo)

        self.boton_confirmar = QPushButton("Iniciar Orden")
        self.boton_confirmar.setProperty("clase", "primario")
        self.boton_confirmar.clicked.connect(self.finalizar_asistente)

        barra_veh = barra(self.boton_volver, self.boton_nuevo_vehiculo, self.boton_confirmar)
        barra_veh.insertStretch(2, 1)

        self.pagina_vehiculo = QWidget()
        layout_veh = QVBoxLayout(self.pagina_vehiculo)
        layout_veh.setContentsMargins(0, 0, 0, 0)
        layout_veh.setSpacing(ESPACIO_PANTALLA)
        layout_veh.addWidget(QLabel("Selecciona el Vehículo a ingresar:"))
        layout_veh.addWidget(self.combo_vehiculos)
        layout_veh.addStretch()
        layout_veh.addLayout(barra_veh)

        self.paginas.addWidget(self.pagina_cliente)
        self.paginas.addWidget(self.pagina_vehiculo)

        layout_principal = layout_de_dialogo(self)
        layout_principal.addWidget(self.paginas)

    def _cargar_clientes(self) -> None:
        self.combo_clientes.clear()
        with SessionLocal() as db:
            clientes = db.scalars(select(Cliente).order_by(Cliente.nombre_completo)).all()
            for c in clientes:
                etiqueta = f"{c.rut} — {c.nombre_completo}" if c.rut else c.nombre_completo
                self.combo_clientes.addItem(etiqueta, c.id)
        # El campo nace vacío, con su texto de fondo. Preseleccionar al primero
        # de la lista alfabética es ofrecer un titular que nadie eligió, y una
        # orden abierta al cliente equivocado se descubre recién al cobrarla.
        self.combo_clientes.setCurrentIndex(-1)

    def crear_cliente(self) -> None:
        dialogo = FormularioCliente(self)
        if dialogo.exec():
            # Si se guardó correctamente, refrescamos la lista para que aparezca de inmediato
            self._cargar_clientes()

    def avanzar_a_vehiculos(self) -> None:
        self.cliente_id = self.combo_clientes.currentData()
        if not self.cliente_id:
            QMessageBox.warning(self, "Aviso", "Debes seleccionar un cliente.")
            return

        self._cargar_vehiculos()

        self.setWindowTitle("Nueva Orden - Paso 2: Vehículo")
        self.paginas.setCurrentIndex(1)

    def _cargar_vehiculos(self) -> None:
        self.combo_vehiculos.clear()
        with SessionLocal() as db:
            vehiculos = db.scalars(
                select(Vehiculo)
                .where(Vehiculo.cliente_id == self.cliente_id)
                .order_by(Vehiculo.patente)
            ).all()
            for v in vehiculos:
                # Formateo amigable por si la marca o modelo vienen vacíos
                nombre = f"{v.marca or ''} {v.modelo or ''}".strip() or "Vehículo sin marca/modelo"
                self.combo_vehiculos.addItem(f"{nombre} ({v.patente})", v.id)
        self.combo_vehiculos.setCurrentIndex(-1)

    def crear_vehiculo(self) -> None:
        # Le inyectamos el self.cliente_id para que el vehículo nazca vinculado al titular
        dialogo = FormularioVehiculo(self, cliente_id=self.cliente_id)
        if dialogo.exec():
            self._cargar_vehiculos()
            # Auto-seleccionar el vehículo que acabamos de crear
            if dialogo.vehiculo_id:
                indice = self.combo_vehiculos.findData(dialogo.vehiculo_id)
                if indice >= 0:
                    self.combo_vehiculos.setCurrentIndex(indice)

    def volver_a_clientes(self) -> None:
        self.setWindowTitle("Nueva Orden - Paso 1: Cliente")
        self.paginas.setCurrentIndex(0)

    def finalizar_asistente(self) -> None:
        self.vehiculo_id_seleccionado = self.combo_vehiculos.currentData()
        if not self.vehiculo_id_seleccionado:
            QMessageBox.warning(
                self, "Aviso", "El cliente debe tener al menos un vehículo seleccionado."
            )
            return
        self.accept()


class OrdenesWidget(QTabWidget):
    """Pestaña Órdenes: la orden en curso y el historial, una al lado de la otra."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.vehiculo_actual_id = None

        self.tab_nueva_orden = QWidget()
        self._configurar_ui_nueva_orden()

        self.tab_historial = QWidget()
        self._configurar_ui_historial()

        self.addTab(self.tab_nueva_orden, "Nueva Orden")
        self.addTab(self.tab_historial, "Historial de Órdenes")

        # Refrescar historial cada vez que el usuario cambie a la pestaña 2
        self.currentChanged.connect(self._al_cambiar_pestana)

    def _configurar_ui_nueva_orden(self) -> None:
        """Todo el diseño que ya teníamos para crear una orden nueva."""
        self.boton_nueva_orden = QPushButton("Nueva Orden de Trabajo")
        self.boton_nueva_orden.setProperty("clase", "primario")
        self.boton_nueva_orden.clicked.connect(self.abrir_asistente)

        self.label_contexto = QLabel(REPOSO)
        self.label_contexto.setProperty("clase", "seccion")

        self.panel_trabajo = QWidget()
        self.panel_trabajo.setEnabled(False)  # Bloqueado al inicio

        # --- Lado izquierdo: los insumos que se le aplican al vehículo ---
        self.combo_productos = hacer_buscable(QComboBox())
        self.combo_productos.lineEdit().setPlaceholderText("Buscar repuesto, aceite o insumo…")
        self.spin_cantidad = QSpinBox()
        self.spin_cantidad.setRange(1, 1000)

        self.boton_agregar = QPushButton("Agregar")
        self.boton_agregar.clicked.connect(self.agregar_desde_el_combo)
        # Enter agrega a la orden; guardarla —que mueve stock— exige un click
        # deliberado, igual que confirmar el ingreso de mercadería.
        self.boton_agregar.setDefault(True)

        self.tabla_carrito = con_aviso_vacio(
            crear_tabla(COLUMNAS_CARRITO, ancha=0, orden=0, numericas=(1, 2, 3)),
            "Elige un insumo y una cantidad, y agrégalo a la orden.",
        )

        titulo_insumos = QLabel("1. Insumos y Servicios Aplicados")
        titulo_insumos.setProperty("clase", "seccion")

        panel_izq = QWidget()
        layout_izq = QVBoxLayout(panel_izq)
        layout_izq.setContentsMargins(0, 0, CANAL_PANEL, 0)
        layout_izq.setSpacing(ESPACIO_PANTALLA)
        layout_izq.addWidget(titulo_insumos)
        layout_izq.addLayout(barra(
            QLabel("Producto"), self.combo_productos,
            QLabel("Cantidad"), self.spin_cantidad, self.boton_agregar, estira=1,
        ))
        layout_izq.addWidget(self.tabla_carrito, 1)

        # --- Lado derecho: lo que se anota del vehículo al recibirlo ---
        self.spin_kilometraje = QSpinBox()
        self.spin_kilometraje.setRange(0, 9999999)
        self.spin_kilometraje.setSuffix(" km")
        self.spin_kilometraje.setGroupSeparatorShown(True)

        self.combo_combustible = QComboBox()
        self.combo_combustible.addItems(NIVELES_COMBUSTIBLE)

        self.texto_observaciones = QTextEdit()
        self.texto_observaciones.setPlaceholderText("Ej: Vehículo ingresa con raya en puerta...")

        marco_total, self.total = bloque_total()

        self.boton_cancelar = QPushButton("Cancelar")
        self.boton_cancelar.setAutoDefault(False)
        self.boton_cancelar.clicked.connect(self.cancelar_orden)

        self.boton_guardar = QPushButton("Guardar Orden")
        self.boton_guardar.setProperty("clase", "primario")
        self.boton_guardar.setAutoDefault(False)
        self.boton_guardar.clicked.connect(self.guardar_orden)

        panel_der = QWidget()
        layout_der = QVBoxLayout(panel_der)
        layout_der.setContentsMargins(CANAL_PANEL, 0, 0, 0)
        layout_der.setSpacing(ESPACIO_PANTALLA)
        layout_der.addWidget(QLabel("2. Kilometraje de Ingreso *"))
        layout_der.addWidget(self.spin_kilometraje)
        layout_der.addWidget(QLabel("3. Nivel de Combustible (Opcional)"))
        layout_der.addWidget(self.combo_combustible)
        layout_der.addWidget(QLabel("4. Observaciones y Estado Visual"))
        layout_der.addWidget(self.texto_observaciones)
        layout_der.addStretch()
        layout_der.addWidget(marco_total)
        layout_der.addLayout(barra(self.boton_cancelar, self.boton_guardar, estira=1))

        division = QSplitter(Qt.Horizontal)
        division.setHandleWidth(1)
        division.addWidget(panel_izq)
        division.addWidget(panel_der)
        division.setSizes([600, 350])

        layout_trabajo = QVBoxLayout(self.panel_trabajo)
        layout_trabajo.setContentsMargins(0, ESPACIO_PANTALLA, 0, 0)
        layout_trabajo.addWidget(division)

        layout_tab_1 = layout_de_pantalla(self.tab_nueva_orden)
        layout_tab_1.addLayout(barra(self.boton_nueva_orden, self.label_contexto, estira=1))
        layout_tab_1.addWidget(self.panel_trabajo)

    def _configurar_ui_historial(self) -> None:
        """Diseño visual de la segunda pestaña (Historial)."""
        self.busqueda_historial = QLineEdit(
            placeholderText="Buscar por N° OT, Patente o Cliente..."
        )
        self.busqueda_historial.textChanged.connect(self.cargar_historial)

        self.tabla_historial = con_aviso_vacio(
            crear_tabla(COLUMNAS_HISTORIAL, ancha=2, orden=0, descendente=True,
                        numericas=(0, 6)),
            "Todavía no hay órdenes de trabajo registradas.",
        )
        self.tabla_historial.doubleClicked.connect(self.abrir_detalle_orden)

        layout_tab_2 = layout_de_pantalla(self.tab_historial)
        layout_tab_2.addWidget(self.busqueda_historial)
        layout_tab_2.addWidget(self.tabla_historial)

    def _al_cambiar_pestana(self, index: int) -> None:
        if index == 1:
            self.cargar_historial()

    def cargar_historial(self) -> None:
        consulta = filtro_busqueda(
            # Unimos las 4 tablas relacionadas
            select(Orden, Cliente, Vehiculo, Usuario)
            .join(Vehiculo, Orden.vehiculo_id == Vehiculo.id)
            .join(Cliente, Vehiculo.cliente_id == Cliente.id)
            .join(Usuario, Orden.usuario_id == Usuario.id)
            .order_by(Orden.id.desc()),
            self.busqueda_historial.text(),
            # Con el ilike a mano, una patente tecleada con guión o un cliente
            # con tilde no encontraban nada.
            cast(Orden.id, String), Vehiculo.patente, Cliente.nombre_completo,
        )

        with SessionLocal() as db:
            filas = [
                (orden.id, orden.fecha_creacion, cliente.nombre_completo, vehiculo.patente,
                 f"{vehiculo.marca or ''} {vehiculo.modelo or ''}".strip() or "S/D",
                 usuario.nombre, orden.total_final)
                for orden, cliente, vehiculo, usuario in db.execute(consulta).all()
            ]

        # Apagamos el ordenamiento para insertar rápido
        self.tabla_historial.setSortingEnabled(False)
        self.tabla_historial.setRowCount(len(filas))

        for fila, (oid, fecha, cliente, patente, vehiculo, mecanico, total) in enumerate(filas):
            celda_id = ItemNumerico(str(oid), oid)
            celda_id.setData(Qt.UserRole, oid)
            # Ordenable por el instante real: como texto, "%d-%m-%Y" ordena por
            # el día del mes. Mismo patrón que el historial de ventas.
            celda_fecha = ItemNumerico(fecha.strftime("%d-%m-%Y %H:%M"), fecha.timestamp())
            celda_fecha.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            celda_patente = QTableWidgetItem(patente)
            celda_patente.setFont(fuente_tabular())

            self.tabla_historial.setItem(fila, 0, celda_id)
            self.tabla_historial.setItem(fila, 1, celda_fecha)
            self.tabla_historial.setItem(fila, 2, QTableWidgetItem(cliente))
            self.tabla_historial.setItem(fila, 3, celda_patente)
            self.tabla_historial.setItem(fila, 4, QTableWidgetItem(vehiculo))
            self.tabla_historial.setItem(fila, 5, QTableWidgetItem(mecanico))
            self.tabla_historial.setItem(fila, 6, ItemNumerico(clp(total), total))

        reordenar(self.tabla_historial)
        self.tabla_historial.aviso.setText(
            "Ninguna orden coincide con la búsqueda."
            if self.busqueda_historial.text().strip()
            else "Todavía no hay órdenes de trabajo registradas."
        )

    def abrir_asistente(self) -> None:
        dialogo = AsistenteNuevaOrden(self)
        if dialogo.exec():
            self._iniciar_nueva_orden(dialogo.vehiculo_id_seleccionado)

    def _iniciar_nueva_orden(self, vehiculo_id: int) -> None:
        # Guardamos el ID del vehículo en la memoria de la ventana para usarlo al guardar
        self.vehiculo_actual_id = vehiculo_id

        with SessionLocal() as db:
            vehiculo = db.get(Vehiculo, vehiculo_id)
            cliente = db.get(Cliente, vehiculo.cliente_id)

            self.label_contexto.setText(
                f"OT en proceso | {cliente.nombre_completo} | "
                f"{vehiculo.marca or ''} {vehiculo.modelo or ''} ({vehiculo.patente})"
            )

        self._vaciar_formulario()
        self._cargar_productos()

        # Desbloquear el panel de trabajo y bloquear el botón de nueva orden
        self.panel_trabajo.setEnabled(True)
        self.boton_nueva_orden.setEnabled(False)
        self.combo_productos.setFocus()

    def _vaciar_formulario(self) -> None:
        """Deja la pestaña 1 en blanco.

        Vive acá porque estaba copiado tres veces, y una de las copias —la de
        `abrir_detalle_orden`— borraba la orden que se estaba armando con solo
        mirar el historial.
        """
        self.tabla_carrito.setRowCount(0)
        self.spin_kilometraje.setValue(0)
        self.spin_cantidad.setValue(1)
        self.combo_combustible.setCurrentIndex(0)
        self.texto_observaciones.clear()
        self.total.setText(clp(0))

    def _volver_al_reposo(self) -> None:
        self._vaciar_formulario()
        self.vehiculo_actual_id = None
        self.panel_trabajo.setEnabled(False)
        self.boton_nueva_orden.setEnabled(True)
        self.label_contexto.setText(REPOSO)

    def _cargar_productos(self) -> None:
        self.combo_productos.clear()
        with SessionLocal() as db:
            productos = db.scalars(
                select(Producto).where(Producto.activo.is_(True)).order_by(Producto.nombre)
            ).all()
            for p in productos:
                # El nombre viaja en los datos, no se lee de currentText(): con
                # el combo editable ese texto puede ser un filtro a medio
                # escribir. El stock no se guarda acá a propósito: se relee al
                # agregar, que es cuando importa.
                self.combo_productos.addItem(p.nombre, {"id": p.id, "nombre": p.nombre})
        self.combo_productos.setCurrentIndex(-1)

    def agregar_desde_el_combo(self) -> None:
        datos = self.combo_productos.currentData()
        if not datos:
            return
        self.agregar_al_carrito(datos["id"], self.spin_cantidad.value())

    def agregar_al_carrito(self, producto_id: int, cantidad: int = 1) -> None:
        with SessionLocal() as db:
            producto = db.get(Producto, producto_id)
            if not producto:
                return

            # El stock se relee acá y no se cachea al llenar el combo: entre que
            # se cargó la lista y este click pudo venderse lo que quedaba.
            if producto.stock_actual < cantidad:
                QMessageBox.warning(
                    self, "Stock Insuficiente",
                    f"Solo quedan {producto.stock_actual} unidades de '{producto.nombre}'.",
                )
                return

            nombre, precio = producto.nombre, int(producto.precio_venta)

        subtotal = precio * cantidad

        self.tabla_carrito.setSortingEnabled(False)
        fila = self.tabla_carrito.rowCount()
        self.tabla_carrito.insertRow(fila)

        # El id, la cantidad y los precios viajan en Qt.UserRole: la tabla es la
        # que guarda la orden en curso, y guardar_orden la lee de vuelta.
        celda_nombre = QTableWidgetItem(nombre)
        celdas = (celda_nombre, ItemNumerico(str(cantidad), cantidad),
                  ItemNumerico(clp(precio), precio), ItemNumerico(clp(subtotal), subtotal))
        for columna, (celda, valor) in enumerate(
            zip(celdas, (producto_id, cantidad, precio, subtotal))
        ):
            celda.setData(Qt.UserRole, valor)
            self.tabla_carrito.setItem(fila, columna, celda)

        reordenar(self.tabla_carrito)
        self.spin_cantidad.setValue(1)
        self.recalcular_total()

    def recalcular_total(self) -> None:
        # El valor matemático del subtotal viaja en Qt.UserRole
        suma_total = sum(
            self.tabla_carrito.item(fila, 3).data(Qt.UserRole)
            for fila in range(self.tabla_carrito.rowCount())
        )
        self.total.setText(clp(suma_total))

    def guardar_orden(self) -> None:
        if not Sesion.activa():
            QMessageBox.critical(
                self, "Sesión no válida",
                "No hay un usuario con sesión iniciada. Reinicia la aplicación.",
            )
            return
        if self.tabla_carrito.rowCount() == 0:
            QMessageBox.warning(
                self, "Orden vacía", "La orden no tiene repuestos ni servicios cargados."
            )
            return

        # Capturar totales y empaquetar detalles
        detalles = [
            {
                "producto_id": self.tabla_carrito.item(fila, 0).data(Qt.UserRole),
                "cantidad": self.tabla_carrito.item(fila, 1).data(Qt.UserRole),
                "precio": self.tabla_carrito.item(fila, 2).data(Qt.UserRole),
                "subtotal": self.tabla_carrito.item(fila, 3).data(Qt.UserRole),
            }
            for fila in range(self.tabla_carrito.rowCount())
        ]
        suma_total = sum(d["subtotal"] for d in detalles)

        # Armar las notas incluyendo el nivel de combustible
        notas_finales = f"Nivel de Combustible: {self.combo_combustible.currentText()}"
        observaciones = self.texto_observaciones.toPlainText().strip()
        if observaciones:
            notas_finales += f"\nObservaciones: {observaciones}"

        with SessionLocal() as db:
            nueva_orden = Orden(
                vehiculo_id=self.vehiculo_actual_id,
                usuario_id=Sesion.usuario_id,  # Extraído de tu clase auth
                kilometraje_ingreso=self.spin_kilometraje.value(),
                subtotal=suma_total,
                total_final=suma_total,
                notas=notas_finales,
            )
            db.add(nueva_orden)
            try:
                db.flush()  # asigna nueva_orden.id sin cerrar la transacción
                for det in detalles:
                    db.add(DetalleOrden(
                        orden_id=nueva_orden.id,
                        producto_id=det["producto_id"],
                        cantidad=det["cantidad"],
                        precio_unitario_cobrado=det["precio"],
                    ))
                # Al confirmar, los triggers descuentan el stock y escriben el
                # kardex. No queda ningún Producto vivo en esta sesión al que
                # refrescarle el saldo: la pantalla relee el catálogo entero al
                # empezar la orden siguiente.
                db.commit()
            except IntegrityError as e:
                # Solo lo que rechaza la base. El `except Exception` que había
                # acá se tragaba también los errores de programación y los
                # mostraba como si fueran culpa de quien atiende.
                db.rollback()
                detalle = str(e.orig)
                if "stock_actual" in detalle:
                    QMessageBox.warning(
                        self, "Stock insuficiente",
                        "El stock cambió justo antes de guardar la orden. "
                        "Revisa los insumos cargados e inténtalo de nuevo.",
                    )
                else:
                    QMessageBox.warning(
                        self, "No se pudo guardar la orden",
                        f"La base de datos rechazó la orden:\n\n{detalle}",
                    )
                self._cargar_productos()
                return
            numero = nueva_orden.id

        QMessageBox.information(
            self, "Orden guardada", f"Orden N° {numero} guardada correctamente."
        )
        self._volver_al_reposo()

    def abrir_detalle_orden(self) -> None:
        """Consultar una orden guardada no toca la que se esté armando.

        Este cuerpo tenía copiado el de `_iniciar_nueva_orden` y limpiaba el
        formulario de la otra pestaña: abrir una orden del historial para
        mirarla descartaba carrito, kilometraje y observaciones en curso.
        """
        fila = self.tabla_historial.currentRow()
        if fila < 0:
            return

        orden_id = self.tabla_historial.item(fila, 0).data(Qt.UserRole)
        DialogoDetalleOrden(orden_id, self).exec()

    def cancelar_orden(self) -> None:
        # Solo pedir confirmación si el carrito ya tiene insumos
        if self.tabla_carrito.rowCount() > 0:
            confirmacion = QMessageBox.question(
                self, "Cancelar Orden",
                "Tienes productos y servicios cargados. ¿Estás seguro de que "
                "deseas descartar esta orden?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirmacion != QMessageBox.Yes:
                return

        self._volver_al_reposo()


class DialogoDetalleOrden(QDialog):
    """Muestra el desglose de una orden guardada, incluyendo productos y notas."""

    def __init__(self, orden_id: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Detalle de Orden N° {orden_id}")
        self.resize(650, 500)
        self.setModal(True)

        with SessionLocal() as db:
            orden = db.get(Orden, orden_id)
            vehiculo = db.get(Vehiculo, orden.vehiculo_id)
            cliente = db.get(Cliente, vehiculo.cliente_id)
            usuario = db.get(Usuario, orden.usuario_id)

            # Cabecera de contexto
            info_html = (
                f"<b>Cliente:</b> {cliente.nombre_completo}<br>"
                f"<b>Vehículo:</b> {vehiculo.marca or ''} {vehiculo.modelo or ''} "
                f"({vehiculo.patente})<br>"
                f"<b>Kilometraje:</b> {orden.kilometraje_ingreso} km<br>"
                f"<b>Mecánico:</b> {usuario.nombre} | "
                f"<b>Fecha:</b> {orden.fecha_creacion.strftime('%d-%m-%Y %H:%M')}"
            )
            # La relación 'orden.detalles' nos permite acceder a los productos
            # sin hacer joins manuales.
            lineas = [
                (det.producto.nombre, det.cantidad, int(det.precio_unitario_cobrado))
                for det in orden.detalles
            ]
            notas_guardadas = orden.notas or "Sin observaciones registradas."
            total_guardado = int(orden.total_final)

        # Tabla de productos
        tabla = con_aviso_vacio(
            crear_tabla(COLUMNAS_DETALLE, ancha=0, orden=0, numericas=(1, 2, 3)),
            "Esta orden quedó guardada sin insumos cargados.",
        )
        tabla.setRowCount(len(lineas))
        for fila, (nombre, cantidad, precio) in enumerate(lineas):
            subtotal = precio * cantidad
            tabla.setItem(fila, 0, QTableWidgetItem(nombre))
            tabla.setItem(fila, 1, ItemNumerico(str(cantidad), cantidad))
            tabla.setItem(fila, 2, ItemNumerico(clp(precio), precio))
            tabla.setItem(fila, 3, ItemNumerico(clp(subtotal), subtotal))
        reordenar(tabla)

        # Observaciones y Nivel de Combustible
        notas = QTextEdit()
        notas.setReadOnly(True)
        notas.setPlainText(notas_guardadas)
        notas.setMaximumHeight(80)

        marco_total, cifra_total = bloque_total("Total final", menor=True)
        cifra_total.setText(clp(total_guardado))

        titulo_insumos = QLabel("Insumos y Servicios")
        titulo_insumos.setProperty("clase", "seccion")
        titulo_notas = QLabel("Notas y Combustible")
        titulo_notas.setProperty("clase", "seccion")

        # Ensamble
        layout = layout_de_dialogo(self)
        layout.addWidget(QLabel(info_html))
        layout.addWidget(titulo_insumos)
        layout.addWidget(tabla)
        layout.addWidget(titulo_notas)
        layout.addWidget(notas)
        layout.addWidget(marco_total)
