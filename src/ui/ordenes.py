from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QStackedWidget, QWidget, QComboBox, QMessageBox, QSpinBox, QTextEdit, 
    QLineEdit, QSplitter, QTableWidgetItem, QInputDialog, QTabWidget, QHeaderView
)
from sqlalchemy import select, or_, cast, String
from ..database import SessionLocal
from ..models import Cliente, Vehiculo, Orden, DetalleOrden, Producto, Usuario
from .clientes import FormularioCliente, FormularioVehiculo
from .comunes import crear_tabla, ItemNumerico, clp
from ..auth import Sesion



class AsistenteNuevaOrden(QDialog):
    """Embudo de selección: Cliente -> Vehículo antes de abrir la orden."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nueva Orden - Paso 1: Cliente")
        self.resize(450, 200)
        self.setModal(True)

        self.vehiculo_id_seleccionado = None
        self.paginas = QStackedWidget()
        
        # --- PÁGINA 1: SELECCIÓN DE CLIENTE ---
        self.pagina_cliente = QWidget()
        layout_cli = QVBoxLayout(self.pagina_cliente)
        
        self.combo_clientes = QComboBox()
        self._cargar_clientes()
        
        self.boton_nuevo_cliente = QPushButton("Crear Cliente")
        self.boton_nuevo_cliente.clicked.connect(self.crear_cliente)
        
        self.boton_siguiente = QPushButton("Siguiente ->")
        self.boton_siguiente.setProperty("clase", "primario")
        self.boton_siguiente.clicked.connect(self.avanzar_a_vehiculos)

        barra_cli = QHBoxLayout()
        barra_cli.addWidget(self.boton_nuevo_cliente)
        barra_cli.addStretch()
        barra_cli.addWidget(self.boton_siguiente)

        layout_cli.addWidget(QLabel("Selecciona el Cliente titular:"))
        layout_cli.addWidget(self.combo_clientes)
        layout_cli.addLayout(barra_cli)

        # --- PÁGINA 2: SELECCIÓN DE VEHÍCULO ---
        self.pagina_vehiculo = QWidget()
        layout_veh = QVBoxLayout(self.pagina_vehiculo)
        
        self.combo_vehiculos = QComboBox()
        
        self.boton_volver = QPushButton("<- Volver")
        self.boton_volver.clicked.connect(self.volver_a_clientes)
        
        self.boton_nuevo_vehiculo = QPushButton("Añadir Vehículo")
        self.boton_nuevo_vehiculo.clicked.connect(self.crear_vehiculo)
        
        self.boton_confirmar = QPushButton("Iniciar Orden")
        self.boton_confirmar.setProperty("clase", "primario")
        self.boton_confirmar.clicked.connect(self.finalizar_asistente)

        barra_veh = QHBoxLayout()
        barra_veh.addWidget(self.boton_volver)
        barra_veh.addWidget(self.boton_nuevo_vehiculo)
        barra_veh.addStretch()
        barra_veh.addWidget(self.boton_confirmar)

        layout_veh.addWidget(QLabel("Selecciona el Vehículo a ingresar:"))
        layout_veh.addWidget(self.combo_vehiculos)
        layout_veh.addLayout(barra_veh)

        self.paginas.addWidget(self.pagina_cliente)
        self.paginas.addWidget(self.pagina_vehiculo)

        layout_principal = QVBoxLayout(self)
        layout_principal.addWidget(self.paginas)

    def _cargar_clientes(self) -> None:
        self.combo_clientes.clear()
        with SessionLocal() as db:
            clientes = db.scalars(select(Cliente).order_by(Cliente.nombre_completo)).all()
            for c in clientes:
                self.combo_clientes.addItem(c.nombre_completo, c.id)

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
            vehiculos = db.scalars(select(Vehiculo).where(Vehiculo.cliente_id == self.cliente_id)).all()
            for v in vehiculos:
                # Formateo amigable por si la marca o modelo vienen vacíos
                nombre = f"{v.marca or ''} {v.modelo or ''}".strip() or "Vehículo sin marca/modelo"
                self.combo_vehiculos.addItem(f"{nombre} ({v.patente})", v.id)

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
            QMessageBox.warning(self, "Aviso", "El cliente debe tener al menos un vehículo seleccionado.")
            return
        self.accept()

class OrdenesWidget(QWidget):
    """Contenedor principal con pestañas: Nueva Orden y Historial."""
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.tabs = QTabWidget()
        
        # --- Pestaña 1: Nueva Orden ---
        self.tab_nueva_orden = QWidget()
        self._configurar_ui_nueva_orden() 
        
        # --- Pestaña 2: Historial ---
        self.tab_historial = QWidget()
        self._configurar_ui_historial()
        
        self.tabs.addTab(self.tab_nueva_orden, "Nueva Orden")
        self.tabs.addTab(self.tab_historial, "Historial de Órdenes")
        
        # Refrescar historial cada vez que el usuario cambie a la pestaña 2
        self.tabs.currentChanged.connect(self._al_cambiar_pestana)

        layout_principal = QVBoxLayout(self)
        layout_principal.setContentsMargins(0, 0, 0, 0)
        layout_principal.addWidget(self.tabs)

    def _configurar_ui_nueva_orden(self) -> None:
        """Todo el diseño que ya teníamos para crear una orden nueva."""
        self.boton_nueva_orden = QPushButton("Nueva Orden de Trabajo")
        self.boton_nueva_orden.setProperty("clase", "primario")
        self.boton_nueva_orden.clicked.connect(self.abrir_asistente)
        
        self.label_contexto = QLabel("Seleccione 'Nueva Orden' para comenzar.")
        fuente_contexto = self.label_contexto.font()
        fuente_contexto.setBold(True)
        self.label_contexto.setFont(fuente_contexto)
        
        barra_sup = QHBoxLayout()
        barra_sup.addWidget(self.boton_nueva_orden)
        barra_sup.addSpacing(20)
        barra_sup.addWidget(self.label_contexto)
        barra_sup.addStretch()

        self.panel_trabajo = QWidget()
        self.panel_trabajo.setEnabled(False) # Bloqueado al inicio
        
        # Lado Izquierdo
        self.busqueda_productos = QLineEdit(placeholderText="Buscar repuesto, aceite o insumo...")
        self.busqueda_productos.returnPressed.connect(self.abrir_buscador)
        self.tabla_carrito = crear_tabla(["Producto", "Cant.", "Precio Unit.", "Subtotal"], ancha=0, orden=0, numericas=(1, 2, 3))
        
        layout_izq = QVBoxLayout()
        layout_izq.addWidget(QLabel("1. Insumos y Servicios Aplicados:"))
        layout_izq.addWidget(self.busqueda_productos)
        layout_izq.addWidget(self.tabla_carrito)
        
        # Lado Derecho
        self.spin_kilometraje = QSpinBox()
        self.spin_kilometraje.setRange(0, 9999999)
        self.spin_kilometraje.setSuffix(" km")
        self.spin_kilometraje.setGroupSeparatorShown(True)
        
        self.combo_combustible = QComboBox()
        self.combo_combustible.addItems(["No registrado", "Reserva", "1/4", "Medio", "3/4", "Lleno"])
        
        self.texto_observaciones = QTextEdit()
        self.texto_observaciones.setPlaceholderText("Ej: Vehículo ingresa con raya en puerta...")
        
        self.label_total = QLabel("Total: $0")
        self.label_total.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fuente_total = self.label_total.font()
        fuente_total.setPointSize(fuente_total.pointSize() + 4)
        fuente_total.setBold(True)
        self.label_total.setFont(fuente_total)
        
        # Botones de Cierre
        self.boton_cancelar = QPushButton("Cancelar")
        self.boton_cancelar.clicked.connect(self.cancelar_orden)

        self.boton_guardar = QPushButton("Guardar Orden")
        self.boton_guardar.setProperty("clase", "primario")
        self.boton_guardar.clicked.connect(self.guardar_orden)

        layout_botones = QHBoxLayout()
        layout_botones.addWidget(self.boton_cancelar)
        layout_botones.addWidget(self.boton_guardar)
        
        layout_der = QVBoxLayout()
        layout_der.addWidget(QLabel("2. Kilometraje de Ingreso *"))
        layout_der.addWidget(self.spin_kilometraje)
        layout_der.addSpacing(10)
        layout_der.addWidget(QLabel("3. Nivel de Combustible (Opcional)"))
        layout_der.addWidget(self.combo_combustible)
        layout_der.addSpacing(10)
        layout_der.addWidget(QLabel("4. Observaciones y Estado Visual"))
        layout_der.addWidget(self.texto_observaciones)
        layout_der.addStretch()
        layout_der.addWidget(self.label_total)

        layout_der.addLayout(layout_botones)
        
        division = QSplitter(Qt.Horizontal)
        widget_izq = QWidget()
        widget_izq.setLayout(layout_izq)
        widget_der = QWidget()
        widget_der.setLayout(layout_der)
        
        division.addWidget(widget_izq)
        division.addWidget(widget_der)
        division.setSizes([600, 350]) 
        
        layout_trabajo = QVBoxLayout(self.panel_trabajo)
        layout_trabajo.setContentsMargins(0, 15, 0, 0)
        layout_trabajo.addWidget(division)

        # Fíjate que el layout se aplica a tab_nueva_orden, no a self
        layout_tab_1 = QVBoxLayout(self.tab_nueva_orden)
        layout_tab_1.addLayout(barra_sup)
        layout_tab_1.addWidget(self.panel_trabajo)

    def _configurar_ui_historial(self) -> None:
        """Diseño visual de la segunda pestaña (Historial)."""
        self.busqueda_historial = QLineEdit(placeholderText="Buscar por N° OT, Patente o Cliente...")
        self.busqueda_historial.textChanged.connect(self.cargar_historial)

        self.tabla_historial = crear_tabla(
            ["ID OT", "Fecha", "Cliente", "Patente", "Vehículo", "Mecánico", "Total"],
            ancha=0, orden=0
        )
        self.tabla_historial.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tabla_historial.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)

        self.tabla_historial.doubleClicked.connect(self.abrir_detalle_orden)

        layout_tab_2 = QVBoxLayout(self.tab_historial)
        layout_tab_2.setContentsMargins(15, 15, 15, 15)
        layout_tab_2.addWidget(self.busqueda_historial)
        layout_tab_2.addWidget(self.tabla_historial)

    def _al_cambiar_pestana(self, index: int) -> None:
        if index == 1:
            self.cargar_historial()

    def cargar_historial(self) -> None:
        texto = self.busqueda_historial.text().strip()
        
        with SessionLocal() as db:
            # Unimos las 4 tablas relacionadas
            query = (
                select(Orden, Cliente, Vehiculo, Usuario)
                .join(Vehiculo, Orden.vehiculo_id == Vehiculo.id)
                .join(Cliente, Vehiculo.cliente_id == Cliente.id)
                .join(Usuario, Orden.usuario_id == Usuario.id)
                .order_by(Orden.id.desc())
            )
            
            # Filtro dinámico si hay texto en el buscador
            if texto:
                termino = f"%{texto}%"
                query = query.where(
                    or_(
                        cast(Orden.id, String).ilike(termino),
                        Vehiculo.patente.ilike(termino),
                        Cliente.nombre_completo.ilike(termino)
                    )
                )
                
            resultados = db.execute(query).all()
            
            # Apagamos el ordenamiento para insertar rápido
            self.tabla_historial.setSortingEnabled(False)
            self.tabla_historial.setRowCount(0)
            
            for fila, (orden, cliente, vehiculo, usuario) in enumerate(resultados):
                self.tabla_historial.insertRow(fila)
                
                vehiculo_str = f"{vehiculo.marca or ''} {vehiculo.modelo or ''}".strip() or "S/D"
                fecha_str = orden.fecha_creacion.strftime("%d-%m-%Y %H:%M")
                
                # Columnas: ["ID OT", "Fecha", "Cliente", "Patente", "Vehículo", "Mecánico", "Total"]
                celda_id = ItemNumerico(str(orden.id), orden.id)
                celda_id.setData(Qt.UserRole, orden.id)
                self.tabla_historial.setItem(fila, 0, celda_id)
                self.tabla_historial.setItem(fila, 1, QTableWidgetItem(fecha_str))
                self.tabla_historial.setItem(fila, 2, QTableWidgetItem(cliente.nombre_completo))
                self.tabla_historial.setItem(fila, 3, QTableWidgetItem(vehiculo.patente))
                self.tabla_historial.setItem(fila, 4, QTableWidgetItem(vehiculo_str))
                self.tabla_historial.setItem(fila, 5, QTableWidgetItem(usuario.nombre))
                self.tabla_historial.setItem(fila, 6, ItemNumerico(clp(orden.total_final), orden.total_final))
                
            self.tabla_historial.setSortingEnabled(True)

    def abrir_asistente(self) -> None:
        dialogo = AsistenteNuevaOrden(self)
        if dialogo.exec():
            print(f"Vehículo ID capturado: {dialogo.vehiculo_id_seleccionado}")
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
        
        # Reiniciar campos visuales para una orden limpia
        self.tabla_carrito.setRowCount(0)
        self.spin_kilometraje.setValue(0)
        self.combo_combustible.setCurrentIndex(0)
        self.texto_observaciones.clear()
        self.label_total.setText("Total: $0")
        
        # Desbloquear el panel de trabajo y bloquear el botón de nueva orden
        self.panel_trabajo.setEnabled(True)
        self.boton_nueva_orden.setEnabled(False)

    def abrir_buscador(self) -> None:
        texto = self.busqueda_productos.text().strip()
        if not texto: return

        dialogo = DialogoBuscarProducto(texto, self)
        if dialogo.exec() and dialogo.producto_seleccionado_id:
            self.agregar_al_carrito(dialogo.producto_seleccionado_id)
            self.busqueda_productos.clear()

    def agregar_al_carrito(self, producto_id: int) -> None:
        with SessionLocal() as db:
            producto = db.get(Producto, producto_id)
            if not producto: return

            # Solicitar cantidad al usuario
            cantidad, ok = QInputDialog.getInt(
                self, "Cantidad", f"¿Cuántas unidades de '{producto.nombre}'?", 
                1, 1, 1000
            )
            if not ok: return

            if producto.stock_actual < cantidad:
                QMessageBox.warning(self, "Stock Insuficiente", f"Solo quedan {producto.stock_actual} en inventario.")
                return

            subtotal = int(producto.precio_venta * cantidad)

            # Apagamos ordenamiento
            self.tabla_carrito.setSortingEnabled(False)
            fila = self.tabla_carrito.rowCount()
            self.tabla_carrito.insertRow(fila)

            # 1. Columna Nombre (Ocultando el ID del producto)
            item_nombre = QTableWidgetItem(producto.nombre)
            item_nombre.setData(Qt.UserRole, producto.id)
            self.tabla_carrito.setItem(fila, 0, item_nombre)

            # 2. Columna Cantidad
            item_cant = ItemNumerico(str(cantidad), cantidad)
            item_cant.setData(Qt.UserRole, cantidad)
            self.tabla_carrito.setItem(fila, 1, item_cant)

            # 3. Columna Precio Unitario
            item_precio = ItemNumerico(clp(producto.precio_venta), producto.precio_venta)
            item_precio.setData(Qt.UserRole, int(producto.precio_venta))
            self.tabla_carrito.setItem(fila, 2, item_precio)

            # 4. Columna Subtotal
            item_sub = ItemNumerico(clp(subtotal), subtotal)
            item_sub.setData(Qt.UserRole, subtotal)
            self.tabla_carrito.setItem(fila, 3, item_sub)

            self.tabla_carrito.setSortingEnabled(True)

            self.recalcular_total()

    def recalcular_total(self) -> None:
        suma_total = 0
        for fila in range(self.tabla_carrito.rowCount()):
            # Extraemos el valor matemático del subtotal usando Qt.UserRole
            subtotal = self.tabla_carrito.item(fila, 3).data(Qt.UserRole)
            suma_total += subtotal
            
        self.label_total.setText(f"Total: {clp(suma_total)}")

    def guardar_orden(self) -> None:
        if self.tabla_carrito.rowCount() == 0:
            QMessageBox.warning(self, "Aviso", "La orden no tiene repuestos ni servicios cargados.")
            return

        # Capturar totales y empaquetar detalles
        suma_total = 0
        detalles = []
        for fila in range(self.tabla_carrito.rowCount()):
            producto_id = self.tabla_carrito.item(fila, 0).data(Qt.UserRole)
            cantidad = self.tabla_carrito.item(fila, 1).data(Qt.UserRole)
            precio = self.tabla_carrito.item(fila, 2).data(Qt.UserRole)
            subtotal = self.tabla_carrito.item(fila, 3).data(Qt.UserRole)
            
            suma_total += subtotal
            detalles.append({
                "producto_id": producto_id,
                "cantidad": cantidad,
                "precio": precio
            })

        # Armar las notas incluyendo el nivel de combustible
        combustible = self.combo_combustible.currentText()
        obs = self.texto_observaciones.toPlainText().strip()
        notas_finales = f"Nivel de Combustible: {combustible}"
        if obs:
            notas_finales += f"\nObservaciones: {obs}"

        try:
            with SessionLocal() as db:
                if not Sesion.activa():
                    raise ValueError("No hay un usuario autenticado en el sistema.")

                nueva_orden = Orden(
                    vehiculo_id=self.vehiculo_actual_id,
                    usuario_id=Sesion.usuario_id,  # Extraído de tu clase auth
                    kilometraje_ingreso=self.spin_kilometraje.value(),
                    subtotal=suma_total,
                    total_final=suma_total,
                    notas=notas_finales
                )
                db.add(nueva_orden)
                db.flush() 

                for det in detalles:
                    nuevo_detalle = DetalleOrden(
                        orden_id=nueva_orden.id,
                        producto_id=det["producto_id"],
                        cantidad=det["cantidad"],
                        precio_unitario_cobrado=det["precio"]
                    )
                    db.add(nuevo_detalle)
                    
                db.commit()
                QMessageBox.information(self, "Éxito", f"Orden N° {nueva_orden.id} guardada correctamente.")
                
                # Reiniciar UI al estado bloqueado inicial
                self.panel_trabajo.setEnabled(False)
                self.boton_nueva_orden.setEnabled(True)
                self.label_contexto.setText("Seleccione 'Nueva Orden' para comenzar.")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Ocurrió un error al guardar la orden: {str(e)}")

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
                "Tienes productos y servicios cargados. ¿Estás seguro de que deseas descartar esta orden?",
                QMessageBox.Yes | QMessageBox.No
            )
            if confirmacion != QMessageBox.Yes:
                return

        # Restaurar la interfaz al estado de reposo (Gris)
        self.panel_trabajo.setEnabled(False)
        self.boton_nueva_orden.setEnabled(True)
        self.label_contexto.setText("Seleccione 'Nueva Orden' para comenzar.")
        
        # Limpiar los campos para que no queden datos fantasma
        self.tabla_carrito.setRowCount(0)
        self.spin_kilometraje.setValue(0)
        self.combo_combustible.setCurrentIndex(0)
        self.texto_observaciones.clear()
        self.label_total.setText("Total: $0")
        self.vehiculo_actual_id = None

class DialogoBuscarProducto(QDialog):
    """Buscador rápido de insumos y repuestos para la OT."""
    def __init__(self, busqueda_inicial="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Buscar Insumo / Repuesto")
        self.resize(600, 300)
        self.setModal(True)
        self.producto_seleccionado_id = None

        self.busqueda = QLineEdit(busqueda_inicial)
        self.busqueda.textChanged.connect(self.filtrar)

        self.tabla = crear_tabla(["Producto", "Stock", "Precio"], ancha=0, orden=0, numericas=(1, 2))
        self.tabla.doubleClicked.connect(self.seleccionar)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Doble clic sobre el producto para agregarlo:"))
        layout.addWidget(self.busqueda)
        layout.addWidget(self.tabla)

        self.filtrar(busqueda_inicial)

    def filtrar(self, texto: str) -> None:
        self.tabla.setRowCount(0)
        if len(texto) < 2:
            return

        with SessionLocal() as db:
            termino = f"%{texto}%"
            # Busca coincidencias en nombre o código de barras
            productos = db.scalars(
                select(Producto)
                .where(Producto.activo.is_(True))
                .where(or_(Producto.nombre.ilike(termino), Producto.marca.ilike(termino)))
                .limit(20)
            ).all()

            self.tabla.setSortingEnabled(False)
            self.tabla.setRowCount(len(productos))
            
            for fila, p in enumerate(productos):
                item_nombre = QTableWidgetItem(p.nombre)
                item_nombre.setData(Qt.UserRole, p.id) # Ocultamos el ID en el nombre
                
                self.tabla.setItem(fila, 0, item_nombre)
                self.tabla.setItem(fila, 1, ItemNumerico(str(p.stock_actual), p.stock_actual))
                self.tabla.setItem(fila, 2, ItemNumerico(clp(p.precio_venta), p.precio_venta))
                
            self.tabla.setSortingEnabled(True)

    def seleccionar(self) -> None:
        fila = self.tabla.currentRow()
        if fila < 0: return
        self.producto_seleccionado_id = self.tabla.item(fila, 0).data(Qt.UserRole)
        self.accept()

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
                f"<b>Vehículo:</b> {vehiculo.marca or ''} {vehiculo.modelo or ''} ({vehiculo.patente})<br>"
                f"<b>Kilometraje:</b> {orden.kilometraje_ingreso} km<br>"
                f"<b>Mecánico:</b> {usuario.nombre} | <b>Fecha:</b> {orden.fecha_creacion.strftime('%d-%m-%Y %H:%M')}"
            )
            label_info = QLabel(info_html)
            
            # Tabla de productos
            tabla = crear_tabla(["Producto", "Cant.", "Precio Unit.", "Subtotal"], ancha=0, orden=0, numericas=(1, 2, 3))
            
            # La relación 'orden.detalles' nos permite acceder a los productos sin hacer joins manuales
            tabla.setRowCount(len(orden.detalles))
            for fila, det in enumerate(orden.detalles):
                subtotal = int(det.cantidad * det.precio_unitario_cobrado)
                precio = int(det.precio_unitario_cobrado)
                
                tabla.setItem(fila, 0, QTableWidgetItem(det.producto.nombre))
                tabla.setItem(fila, 1, ItemNumerico(str(det.cantidad), det.cantidad))
                tabla.setItem(fila, 2, ItemNumerico(clp(precio), precio))
                tabla.setItem(fila, 3, ItemNumerico(clp(subtotal), subtotal))
                
            # Observaciones y Nivel de Combustible
            notas = QTextEdit()
            notas.setReadOnly(True)
            notas.setPlainText(orden.notas or "Sin observaciones registradas.")
            notas.setMaximumHeight(80)
            
            # Total
            label_total = QLabel(f"Total Final: {clp(int(orden.total_final))}")
            fuente = label_total.font()
            fuente.setPointSize(14)
            fuente.setBold(True)
            label_total.setFont(fuente)
            label_total.setAlignment(Qt.AlignRight)
            
            # Ensamble
            layout = QVBoxLayout(self)
            layout.addWidget(label_info)
            layout.addSpacing(10)
            layout.addWidget(QLabel("<b>Insumos y Servicios:</b>"))
            layout.addWidget(tabla)
            layout.addWidget(QLabel("<b>Notas y Combustible:</b>"))
            layout.addWidget(notas)
            layout.addWidget(label_total)