"""Módulo de Órdenes de Trabajo del taller.

El flujo es el que describió Fabián imitando el programa actual: primero el
cliente, después su vehículo, y recién entonces se abre la orden — insumos al
centro, kilometraje, combustible y observaciones al lateral.

Igual que en ventas, la orden se escribe en una sola transacción y son los
triggers de Postgres los que descuentan el stock y dejan el rastro en el Kardex:
este módulo nunca toca "stock_actual" (ver database/schema_lubriexpress.sql).
"""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import (
    QDesktopServices, QImage, QKeySequence, QPageSize, QPdfWriter, QShortcut, QTextDocument,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog,
    QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QSplitter, QStackedWidget, QTabWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)
from sqlalchemy import String, cast, func, select
from sqlalchemy.exc import IntegrityError

from .. import convenios
from ..auth import Sesion
from ..database import SessionLocal
from ..documentos import estado_de_pago, html_de_orden
from ..models import (
    Cliente, DetalleOrden, Orden, PagoOrden, Producto, Servicio, Usuario, Vehiculo,
)
from ..texto import filtro_busqueda
from ..whatsapp import PLANTILLAS, describir_vehiculo, enlace_whatsapp, redactar
from .clientes import FormularioCliente, FormularioVehiculo
from .catalogo import Catalogo
from .comunes import (
    BADGE_ACENTO, BADGE_ALERTA, BADGE_EXITO, BADGE_INFO, BADGE_NEUTRAL, ROL_INSIGNIA,
    ItemNumerico, barra, bloque_total, botonera,
    carpeta_de_documentos, clp, combo_medio_pago, con_aviso_vacio, crear_tabla, hacer_buscable,
    layout_de_dialogo, layout_de_pantalla, medio_elegido, reordenar,
)
from .tema import ALTO_FILA, CANAL_PANEL, ESPACIO_BARRA, ESPACIO_PANTALLA, LOGO, fuente_tabular

COLUMNAS_CARRITO = ["Ítem", "Cant.", "Precio Unit.", "Subtotal"]
COLUMNAS_DETALLE = ["Ítem", "Cant.", "Precio Unit.", "Subtotal"]
COLUMNAS_HISTORIAL = [
    "ID OT", "Fecha", "Cliente", "Patente", "Vehículo", "Mecánico", "Folio MP",
    "Estado", "Pago", "Total",
]
COLUMNAS_ABIERTAS = [
    "ID OT", "Abierta el", "Cliente", "Patente", "Vehículo", "Mecánico", "Ítems", "Total",
]
# En qué va el trabajo, que no es lo mismo que el pago.
ESTADOS = {
    "ABIERTA": ("Abierta", BADGE_ACENTO),
    "ENTREGADA": ("Entregada", BADGE_EXITO),
    "ANULADA": ("Anulada", BADGE_NEUTRAL),
}
NIVELES_COMBUSTIBLE = ["No registrado", "Reserva", "1/4", "Medio", "3/4", "Lleno"]
# Un selector y un solo campo: la base prohíbe porcentaje y monto a la vez
# (CHECK descuento_exclusivo_orden) y la pantalla lo hace imposible de intentar.
TIPOS_DESCUENTO = ["Sin descuento", "Porcentaje (%)", "Monto ($)",
                   "Flyer (10 %)", "Gremio/Sindicato (15 %)"]
# Convenios: descuentan solo ciertas líneas (src/convenios.py).
CONVENIO_DEL_TIPO = {3: "FLYER", 4: "GREMIO"}
# El filtro del historial: la propuesta pide separar lo institucional (con
# folio de Mercado Público) de los clientes tradicionales.
FILTROS_HISTORIAL = ["Todas", "Mercado Público", "Clientes"]

REPOSO = "Seleccione 'Nueva Orden' para comenzar."
# Marca las líneas del carrito que ya existen en la base.
ROL_DETALLE = Qt.UserRole + 1
# Categoría del producto: decide si la línea entra en un convenio.
ROL_CATEGORIA = Qt.UserRole + 2


def _leer_notas(notas: str) -> tuple[str, str]:
    """Separa el nivel de combustible de las observaciones.

    Las dos cosas viajan en un solo campo porque el esquema tiene uno; al
    retomar una orden hay que devolverlas a sus dos controles.
    """
    nivel, observaciones = "", ""
    for linea in notas.splitlines():
        if linea.startswith("Nivel de Combustible: "):
            nivel = linea.removeprefix("Nivel de Combustible: ").strip()
        elif linea.startswith("Observaciones: "):
            observaciones = linea.removeprefix("Observaciones: ").strip()
        elif observaciones:
            observaciones += "\n" + linea
    return nivel, observaciones


def km(valor: int) -> str:
    """120000 -> '120.000 km'."""
    return f"{valor:,} km".replace(",", ".")


def guardar_pdf_de_orden(orden_id: int, ruta) -> None:
    """La orden como PDF para el cliente (Propuesta 3.4): lo guardado, tal cual."""
    with SessionLocal() as db:
        orden = db.get(Orden, orden_id)
        vehiculo, cliente, usuario = orden.vehiculo, orden.vehiculo.cliente, orden.usuario
        datos = {
            "numero": orden.id, "fecha": orden.fecha_creacion,
            "cliente": cliente.nombre_completo, "rut": cliente.rut, "telefono": cliente.telefono,
            "patente": vehiculo.patente,
            "vehiculo": " ".join(filter(None, (
                vehiculo.marca, vehiculo.modelo,
                str(vehiculo.anio_fabricacion) if vehiculo.anio_fabricacion else None,
            ))) or "Sin marca ni modelo",
            "kilometraje": orden.kilometraje_ingreso, "tecnico": usuario.nombre,
            "lineas": [((d.producto or d.servicio).nombre, d.cantidad, int(d.precio_unitario_cobrado))
                       for d in orden.detalles],
            "subtotal": orden.subtotal, "descuento": orden.descuento_aplicado,
            "impuesto": orden.impuesto, "ajuste": orden.ajuste_redondeo,
            "total": orden.total_final,
            "pagada": orden.estado_pago, "pagado": orden.monto_pagado,
            "folio": orden.folio_mercado_publico, "notas": orden.notas,
            "convenio": convenios.rotulo(orden.convenio, orden.folio_flyer),
        }
    documento = QTextDocument()
    if LOGO.is_file():
        documento.addResource(QTextDocument.ImageResource, QUrl("logo"), QImage(str(LOGO)))
    documento.setHtml(html_de_orden(datos))
    escritor = QPdfWriter(str(ruta))
    escritor.setPageSize(QPageSize(QPageSize.A4))
    documento.print_(escritor)


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


class DialogoWhatsApp(QDialog):
    """Avisarle al cliente cómo va su vehículo, desde la orden abierta.

    Una plantilla arriba y el texto abajo, editable: el borrador es para no
    escribir lo mismo veinte veces al día, no para mandarlo a ciegas. Al
    aceptar se abre WhatsApp con el mensaje ya puesto en la conversación y el
    envío lo hace el operador, que es quien sabe si el auto está listo.
    """

    def __init__(self, *, telefono: str, cliente: str, vehiculo: str,
                 orden_id: int | None = None, parent=None):
        super().__init__(parent)
        self.telefono = telefono
        self.cliente = cliente
        self.vehiculo = vehiculo
        self.orden_id = orden_id

        self.setWindowTitle("Avisar al cliente por WhatsApp")
        self.setMinimumWidth(520)

        self.destinatario = QLabel(f"Para: {cliente} · {telefono}")
        self.destinatario.setProperty("clase", "tarjeta-texto")

        self.combo_plantilla = QComboBox()
        self.combo_plantilla.addItems(PLANTILLAS)
        self.combo_plantilla.currentTextChanged.connect(self._poner_plantilla)

        self.texto = QTextEdit()
        self.texto.setMinimumHeight(180)

        self.boton_cancelar = QPushButton("Cancelar")
        self.boton_cancelar.setAutoDefault(False)
        self.boton_cancelar.clicked.connect(self.reject)
        # No dice "Enviar" porque no envía: deja el mensaje escrito en WhatsApp
        # y el operador decide. Prometer el envío sería mentirle al rótulo.
        self.boton_abrir = QPushButton("Abrir en WhatsApp")
        self.boton_abrir.setProperty("clase", "primario")
        self.boton_abrir.setAutoDefault(False)
        self.boton_abrir.clicked.connect(self.abrir_whatsapp)

        layout = layout_de_dialogo(self)
        layout.addWidget(self.destinatario)
        layout.addWidget(QLabel("Mensaje"))
        layout.addWidget(self.combo_plantilla)
        layout.addWidget(self.texto, 1)
        layout.addLayout(barra(self.boton_cancelar, self.boton_abrir, estira=1))

        self._poner_plantilla(self.combo_plantilla.currentText())

    def _poner_plantilla(self, plantilla: str) -> None:
        """Cambiar de plantilla reescribe el borrador, ediciones incluidas: son
        cuatro avisos distintos, no cuatro variantes del mismo."""
        self.texto.setPlainText(redactar(
            plantilla, cliente=self.cliente, vehiculo=self.vehiculo, orden_id=self.orden_id,
        ))

    def abrir_whatsapp(self) -> None:
        mensaje = self.texto.toPlainText().strip()
        if not mensaje:
            QMessageBox.warning(self, "Mensaje vacío", "Escribe el mensaje antes de enviarlo.")
            return
        enlace = enlace_whatsapp(self.telefono, mensaje)
        if enlace is None:
            # El botón que abre este diálogo ya lo valida, así que llegar acá
            # significa que el teléfono cambió en la base mientras tanto.
            QMessageBox.warning(
                self, "Teléfono no válido",
                "El teléfono del cliente no parece un celular chileno.",
            )
            return
        QDesktopServices.openUrl(QUrl(enlace))
        self.accept()


class OrdenesWidget(QTabWidget):
    """Pestaña Órdenes: la que se está armando, las que siguen abiertas y el
    historial. Varios autos pueden estar en el taller a la vez: una orden se
    deja abierta, se retoma y se entrega cuando el trabajo termina."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.vehiculo_actual_id = None

        self.tab_nueva_orden = QWidget()
        self._configurar_ui_nueva_orden()

        self.tab_abiertas = QWidget()
        self._configurar_ui_abiertas()

        self.tab_historial = QWidget()
        self._configurar_ui_historial()

        self.addTab(self.tab_nueva_orden, "Nueva Orden")
        self.addTab(self.tab_abiertas, "Órdenes Abiertas")
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

        # La tarjeta del vehículo en proceso: patente grande (es lo que se lee
        # desde el patio), el auto, el dueño y el último servicio registrado,
        # que es contra lo que se compara el kilometraje de hoy.
        self.tarjeta = QFrame()
        self.tarjeta.setProperty("clase", "tarjeta")
        self.label_patente = QLabel()
        self.label_patente.setProperty("clase", "patente")
        self.label_vehiculo = QLabel()
        self.label_vehiculo.setProperty("clase", "tarjeta-titulo")
        self.label_cliente = QLabel()
        self.label_cliente.setProperty("clase", "tarjeta-texto")
        self.label_servicio = QLabel()
        self.label_servicio.setProperty("clase", "tarjeta-texto")
        columna = QVBoxLayout()
        columna.setSpacing(2)
        columna.addWidget(self.label_vehiculo)
        columna.addWidget(self.label_cliente)
        columna.addWidget(self.label_servicio)
        # Avisarle al cliente cómo va su vehículo mientras la orden está
        # abierta. Va en la tarjeta y no en la barra de arriba porque el
        # destinatario es el dueño del auto que la tarjeta muestra; apagado si
        # no tiene un teléfono que parezca celular chileno.
        self.boton_whatsapp = QPushButton("Avisar por WhatsApp")
        self.boton_whatsapp.setAutoDefault(False)
        self.boton_whatsapp.setEnabled(False)
        self.boton_whatsapp.clicked.connect(self.avisar_por_whatsapp)

        fila_tarjeta = QHBoxLayout(self.tarjeta)
        fila_tarjeta.setContentsMargins(14, 10, 14, 10)
        fila_tarjeta.setSpacing(16)
        fila_tarjeta.addWidget(self.label_patente)
        fila_tarjeta.addLayout(columna, 1)
        fila_tarjeta.addWidget(self.boton_whatsapp)
        self.tarjeta.hide()
        self.ultimo_km: int | None = None
        # La orden que se está retomando, y las líneas que se le sacaron: al
        # guardar, borrarlas es lo que devuelve su stock a la bodega.
        self.orden_abierta_id: int | None = None
        self.detalles_borrados: list[int] = []
        # Lo que necesita el aviso por WhatsApp, tomado al abrir la orden.
        self.contacto_whatsapp: dict | None = None

        self.panel_trabajo = QWidget()
        self.panel_trabajo.setEnabled(False)  # Bloqueado al inicio

        # --- Lado izquierdo: los insumos que se le aplican al vehículo ---
        # Enter o doble clic agrega una unidad; la cantidad se corrige en la
        # orden. Guardarla, que mueve stock, sigue exigiendo un click.
        self.catalogo = Catalogo(self, servicios=True)
        self.catalogo.elegido.connect(self._agregar_elegido)
        # Hasta cinco filas: lo importante es la orden. Máximo y no fijo, para
        # que en la ventana chica ceda en vez de encimarse.
        tabla = self.catalogo.tabla
        tabla.setMaximumHeight(tabla.horizontalHeader().sizeHint().height() + 5 * ALTO_FILA
                               + 2 * tabla.frameWidth())

        self.tabla_carrito = con_aviso_vacio(
            crear_tabla(COLUMNAS_CARRITO, ancha=0, orden=0, numericas=(1, 2, 3)),
            "Busca arriba lo que se usó y agrégalo con Enter o doble clic.",
        )
        self.tabla_carrito.setToolTip("Doble clic en una línea para cambiar la cantidad.")
        self.tabla_carrito.doubleClicked.connect(self.cambiar_cantidad)
        QShortcut(QKeySequence.Delete, self.tabla_carrito, self.quitar_del_carrito,
                  context=Qt.WidgetShortcut)
        self.tabla_carrito.itemSelectionChanged.connect(
            lambda: self.boton_quitar.setEnabled(
                self.tabla_carrito.selectionModel().hasSelection()
            )
        )

        # Nace apagado y se enciende con la fila elegida, como en el resto: sin
        # esto, equivocarse de insumo obligaba a cancelar la orden entera y
        # volver a pasar por el asistente.
        self.boton_quitar = QPushButton("Quitar")
        self.boton_quitar.setAutoDefault(False)
        self.boton_quitar.setEnabled(False)
        self.boton_quitar.clicked.connect(self.quitar_del_carrito)

        titulo_insumos = QLabel("1. Insumos y Servicios Aplicados")
        titulo_insumos.setProperty("clase", "seccion")
        en_la_orden = QLabel("En la orden")
        en_la_orden.setProperty("clase", "seccion")

        panel_izq = QWidget()
        layout_izq = QVBoxLayout(panel_izq)
        layout_izq.setContentsMargins(0, 0, CANAL_PANEL, 0)
        layout_izq.setSpacing(ESPACIO_PANTALLA)
        layout_izq.addWidget(titulo_insumos)
        layout_izq.addLayout(barra(self.catalogo.busqueda, self.catalogo.categoria,
                                   self.catalogo.boton))
        layout_izq.addLayout(barra(self.catalogo.pestanas, QWidget(), self.catalogo.resumen,
                                   estira=1))
        layout_izq.addWidget(self.catalogo.tabla)
        layout_izq.addLayout(barra(en_la_orden, QWidget(), self.boton_quitar, estira=1))
        layout_izq.addWidget(self.tabla_carrito, 1)

        # --- Lado derecho: lo que se anota del vehículo al recibirlo ---
        self.spin_kilometraje = QSpinBox()
        self.spin_kilometraje.setRange(0, 9999999)
        self.spin_kilometraje.setSuffix(" km")
        self.spin_kilometraje.setGroupSeparatorShown(True)
        # En el mínimo dice "Sin registrar" en vez de "0 km": el asterisco
        # promete que es obligatorio y un cero se lee como un dato ya escrito.
        # Sin el kilometraje la OT no sirve — es con lo que se calcula el
        # próximo servicio, que es a lo que vuelve el cliente. El rótulo es el
        # mismo que usa el combo de combustible justo abajo. (Una cadena vacía
        # acá no sirve: Qt la toma como "sin texto especial".)
        self.spin_kilometraje.setSpecialValueText("Sin registrar")
        self.spin_kilometraje.valueChanged.connect(self._actualizar_boton_guardar)

        self.combo_combustible = QComboBox()
        self.combo_combustible.addItems(NIVELES_COMBUSTIBLE)

        self.texto_observaciones = QTextEdit()
        self.texto_observaciones.setPlaceholderText("Ej: Vehículo ingresa con raya en puerta...")
        # Crece con la ventana, pero hasta ahí: sin tope, en pantalla completa
        # queda una caja vacía de 700 px donde caben ocho líneas de texto.
        self.texto_observaciones.setMaximumHeight(240)
        # Y puede achicarse por debajo de lo que Qt pide de suyo: es el campo
        # que cede alto cuando la ventana está en su tamaño mínimo.
        self.texto_observaciones.setMinimumHeight(40)

        self.tipo_descuento = QComboBox()
        self.tipo_descuento.addItems(TIPOS_DESCUENTO)
        # Cerrado no pide el ancho de "Gremio/Sindicato (15 %)".
        self.tipo_descuento.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.tipo_descuento.setMinimumContentsLength(12)
        self.valor_descuento = QSpinBox()
        self.valor_descuento.setEnabled(False)
        self.tipo_descuento.currentIndexChanged.connect(self._cambiar_tipo_descuento)
        self.valor_descuento.valueChanged.connect(self.recalcular_total)

        self.folio = QLineEdit(placeholderText="Folio MP")
        self.folio.setToolTip("Folio de Mercado Público: solo en las órdenes institucionales.")
        self.pagada = QCheckBox("Pagada")
        self.pagada.toggled.connect(self._cambiar_pago)
        # El taller cobra por partes: un abono al dejar el auto y el saldo al
        # retirarlo. Acá se anota lo que el cliente paga al cerrar la orden; el
        # resto se registra después, desde el historial.
        self.abono = QSpinBox()
        self.abono.setPrefix("$ ")
        self.abono.setGroupSeparatorShown(True)
        self.abono.setButtonSymbols(QSpinBox.NoButtons)
        self.abono.setSpecialValueText("Sin abono")
        self.abono.setToolTip("Lo que el cliente paga al cerrar la orden; el saldo se "
                              "cobra después, desde el historial.")

        # Solo importa si se cobra algo al cerrar: apagado hasta entonces.
        self.combo_medio_pago = combo_medio_pago()
        self.combo_medio_pago.setEnabled(False)
        self.abono.valueChanged.connect(self._actualizar_medio)

        marco_total, self.totales = bloque_total()
        self.total = self.totales.total

        self.boton_cancelar = QPushButton("Cancelar")
        self.boton_cancelar.setAutoDefault(False)
        self.boton_cancelar.clicked.connect(self.cancelar_orden)

        # Dos salidas: el auto se lleva ahora, o se queda y la orden sigue
        # abierta para cargarle lo que falte.
        self.boton_dejar_abierta = QPushButton("Dejar abierta")
        self.boton_dejar_abierta.setAutoDefault(False)
        self.boton_dejar_abierta.setEnabled(False)
        self.boton_dejar_abierta.setToolTip(
            "Guarda la orden con el auto todavía en el taller. Se retoma desde "
            "'Órdenes Abiertas'."
        )
        self.boton_dejar_abierta.clicked.connect(lambda: self.guardar_orden("ABIERTA"))

        self.boton_guardar = QPushButton("Guardar y entregar")
        self.boton_guardar.setProperty("clase", "primario")
        self.boton_guardar.setAutoDefault(False)
        self.boton_guardar.setEnabled(False)
        # Con lambda y no con el método pelado: clicked manda su `checked` como
        # primer argumento, y ese bool terminaría de estado de la orden.
        self.boton_guardar.clicked.connect(lambda: self.guardar_orden("ENTREGADA"))

        panel_der = QWidget()
        layout_der = QVBoxLayout(panel_der)
        layout_der.setContentsMargins(CANAL_PANEL, 0, 0, 0)
        layout_der.setSpacing(ESPACIO_PANTALLA)
        # Lado a lado: en el portátil del taller (1366×768) una fila más
        # dejaba el total tapado por los botones.
        campos = QGridLayout()
        campos.setHorizontalSpacing(ESPACIO_BARRA)
        campos.addWidget(QLabel("2. Kilometraje *"), 0, 0)
        campos.addWidget(QLabel("3. Combustible"), 0, 1)
        campos.addWidget(self.spin_kilometraje, 1, 0)
        campos.addWidget(self.combo_combustible, 1, 1)
        layout_der.addLayout(campos)
        layout_der.addWidget(QLabel("4. Observaciones y Estado Visual"))
        layout_der.addWidget(self.texto_observaciones, 1)
        layout_der.addWidget(QLabel("5. Descuento, folio y pago"))
        # El folio va con el descuento: en la fila del pago no cabe.
        layout_der.addLayout(barra(self.tipo_descuento, self.valor_descuento, self.folio,
                                   estira=2))
        layout_der.addLayout(barra(self.pagada, self.abono, self.combo_medio_pago, estira=1))
        layout_der.addStretch()
        layout_der.addWidget(marco_total)
        layout_der.addLayout(barra(self.boton_cancelar, self.boton_dejar_abierta,
                                   self.boton_guardar, estira=0))

        division = QSplitter(Qt.Horizontal)
        division.setHandleWidth(1)
        division.addWidget(panel_izq)
        division.addWidget(panel_der)
        division.setSizes([600, 350])
        # Al agrandar la ventana el ancho extra es para los insumos: el lateral
        # son tres campos y no mejora por ser más ancho.
        division.setStretchFactor(0, 1)
        division.setStretchFactor(1, 0)

        layout_trabajo = QVBoxLayout(self.panel_trabajo)
        layout_trabajo.setContentsMargins(0, ESPACIO_PANTALLA, 0, 0)
        layout_trabajo.addWidget(division)

        # Oculta durante la orden (la tarjeta ya dice cuál es): en el portátil
        # esos 45 px tapaban el total.
        self.fila_reposo = QWidget()
        fila = barra(self.boton_nueva_orden, self.label_contexto, estira=1)
        fila.setContentsMargins(0, 0, 0, 0)
        self.fila_reposo.setLayout(fila)

        layout_tab_1 = layout_de_pantalla(self.tab_nueva_orden)
        layout_tab_1.addWidget(self.fila_reposo)
        layout_tab_1.addWidget(self.tarjeta)
        # El 1 es lo que hace que el alto sobrante se lo lleve la mesa de trabajo.
        # Sin él, el QLabel de contexto y el panel se reparten la ventana mitad y
        # mitad: en pantalla completa el rótulo medía 506 px de alto.
        layout_tab_1.addWidget(self.panel_trabajo, 1)

    def _configurar_ui_abiertas(self) -> None:
        """Los autos que siguen en el taller. Una orden abierta ya descontó su
        stock: retomarla es seguir cargándole cosas, no volver a empezar."""
        self.tabla_abiertas = con_aviso_vacio(
            crear_tabla(COLUMNAS_ABIERTAS, ancha=2, orden=0, descendente=True,
                        numericas=(0, 6, 7)),
            "No hay órdenes abiertas: todos los autos están entregados.",
        )
        self.tabla_abiertas.doubleClicked.connect(self.retomar_orden)
        self.tabla_abiertas.itemSelectionChanged.connect(self._al_elegir_abierta)

        self.boton_retomar = QPushButton("Retomar")
        self.boton_retomar.setProperty("clase", "primario")
        self.boton_retomar.setAutoDefault(False)
        self.boton_retomar.setEnabled(False)
        self.boton_retomar.clicked.connect(self.retomar_orden)

        self.boton_anular = QPushButton("Anular")
        self.boton_anular.setAutoDefault(False)
        self.boton_anular.setEnabled(False)
        self.boton_anular.setToolTip("Devuelve a la bodega lo que la orden había descontado")
        self.boton_anular.clicked.connect(self.anular_orden_abierta)

        aviso = QLabel(
            "Una orden abierta ya descontó su stock. Anularla lo devuelve a la bodega, "
            "y queda registrado en el Kardex."
        )
        aviso.setWordWrap(True)
        aviso.setProperty("clase", "resumen")

        layout = layout_de_pantalla(self.tab_abiertas)
        layout.addLayout(barra(QWidget(), self.boton_retomar, self.boton_anular, estira=0))
        layout.addWidget(aviso)
        layout.addWidget(self.tabla_abiertas, 1)

    def _al_elegir_abierta(self) -> None:
        hay = self.tabla_abiertas.selectionModel().hasSelection()
        self.boton_retomar.setEnabled(hay)
        self.boton_anular.setEnabled(hay)

    def cargar_abiertas(self) -> None:
        cuantos_items = (
            select(func.count(DetalleOrden.id))
            .where(DetalleOrden.orden_id == Orden.id).scalar_subquery()
        )
        consulta = (
            select(Orden, Cliente, Vehiculo, Usuario, cuantos_items)
            .join(Vehiculo, Orden.vehiculo_id == Vehiculo.id)
            .join(Cliente, Vehiculo.cliente_id == Cliente.id)
            .join(Usuario, Orden.usuario_id == Usuario.id)
            .where(Orden.estado == "ABIERTA")
            .order_by(Orden.id.desc())
        )
        with SessionLocal() as db:
            filas = [
                (orden.id, orden.fecha_creacion, cliente.nombre_completo, vehiculo.patente,
                 f"{vehiculo.marca or ''} {vehiculo.modelo or ''}".strip() or "S/D",
                 usuario.nombre, int(items), orden.total_final)
                for orden, cliente, vehiculo, usuario, items in db.execute(consulta).all()
            ]

        self.tabla_abiertas.setSortingEnabled(False)
        self.tabla_abiertas.setRowCount(len(filas))
        for fila, (oid, fecha, cliente, patente, vehiculo, mecanico, items, total) in enumerate(filas):
            celda_id = ItemNumerico(str(oid), oid)
            celda_id.setData(Qt.UserRole, oid)
            celda_fecha = ItemNumerico(fecha.strftime("%d-%m-%Y %H:%M"), fecha.timestamp())
            celda_fecha.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            celda_patente = QTableWidgetItem(patente)
            celda_patente.setFont(fuente_tabular())
            self.tabla_abiertas.setItem(fila, 0, celda_id)
            self.tabla_abiertas.setItem(fila, 1, celda_fecha)
            self.tabla_abiertas.setItem(fila, 2, QTableWidgetItem(cliente))
            self.tabla_abiertas.setItem(fila, 3, celda_patente)
            self.tabla_abiertas.setItem(fila, 4, QTableWidgetItem(vehiculo))
            self.tabla_abiertas.setItem(fila, 5, QTableWidgetItem(mecanico))
            self.tabla_abiertas.setItem(fila, 6, ItemNumerico(str(items), items))
            self.tabla_abiertas.setItem(fila, 7, ItemNumerico(clp(total), total))
        reordenar(self.tabla_abiertas)
        self.setTabText(1, f"Órdenes Abiertas ({len(filas)})" if filas else "Órdenes Abiertas")
        self._al_elegir_abierta()

    def _configurar_ui_historial(self) -> None:
        """Diseño visual de la segunda pestaña (Historial)."""
        self.busqueda_historial = QLineEdit(
            placeholderText="Buscar por N° OT, Patente o Cliente..."
        )
        self.busqueda_historial.textChanged.connect(self.cargar_historial)
        self.filtro_historial = QComboBox()
        self.filtro_historial.addItems(FILTROS_HISTORIAL)
        self.filtro_historial.currentIndexChanged.connect(self.cargar_historial)

        self.tabla_historial = con_aviso_vacio(
            crear_tabla(COLUMNAS_HISTORIAL, ancha=2, orden=0, descendente=True,
                        numericas=(0, 9)),
            "Todavía no hay órdenes de trabajo registradas.",
        )
        self.tabla_historial.doubleClicked.connect(self.abrir_detalle_orden)

        layout_tab_2 = layout_de_pantalla(self.tab_historial)
        layout_tab_2.addLayout(barra(self.busqueda_historial, self.filtro_historial, estira=0))
        layout_tab_2.addWidget(self.tabla_historial)

    def _al_cambiar_pestana(self, index: int) -> None:
        if index == 1:
            self.cargar_abiertas()
        elif index == 2:
            self.cargar_historial()

    def cargar_historial(self) -> None:
        # Lo abonado por orden, en la misma consulta: traerlo después, fila por
        # fila, son 200 consultas para pintar una tabla de 200 órdenes.
        pagado_de_la_orden = (
            select(func.coalesce(func.sum(PagoOrden.monto), 0))
            .where(PagoOrden.orden_id == Orden.id)
            .scalar_subquery()
        )
        consulta = filtro_busqueda(
            # Unimos las 4 tablas relacionadas
            select(Orden, Cliente, Vehiculo, Usuario, pagado_de_la_orden)
            .join(Vehiculo, Orden.vehiculo_id == Vehiculo.id)
            .join(Cliente, Vehiculo.cliente_id == Cliente.id)
            .join(Usuario, Orden.usuario_id == Usuario.id)
            .order_by(Orden.id.desc()),
            self.busqueda_historial.text(),
            # Con el ilike a mano, una patente tecleada con guión o un cliente
            # con tilde no encontraban nada.
            cast(Orden.id, String), Vehiculo.patente, Cliente.nombre_completo,
        )
        filtro = self.filtro_historial.currentText()
        if filtro == "Mercado Público":
            consulta = consulta.where(Orden.folio_mercado_publico.is_not(None))
        elif filtro == "Clientes":
            consulta = consulta.where(Orden.folio_mercado_publico.is_(None))

        with SessionLocal() as db:
            filas = [
                (orden.id, orden.fecha_creacion, cliente.nombre_completo, vehiculo.patente,
                 f"{vehiculo.marca or ''} {vehiculo.modelo or ''}".strip() or "S/D",
                 usuario.nombre, orden.folio_mercado_publico or "", orden.estado,
                 orden.estado_pago, int(pagado), orden.total_final)
                for orden, cliente, vehiculo, usuario, pagado in db.execute(consulta).all()
            ]

        # Apagamos el ordenamiento para insertar rápido
        self.tabla_historial.setSortingEnabled(False)
        self.tabla_historial.setRowCount(len(filas))

        for fila, (oid, fecha, cliente, patente, vehiculo, mecanico, folio, estado_ot,
                   pagada, pagado, total) in enumerate(filas):
            celda_id = ItemNumerico(str(oid), oid)
            celda_id.setData(Qt.UserRole, oid)
            # Ordenable por el instante real: como texto, "%d-%m-%Y" ordena por
            # el día del mes. Mismo patrón que el historial de ventas.
            formato = "%d-%m-%Y" if (fecha.hour, fecha.minute) == (0, 0) else "%d-%m-%Y %H:%M"
            celda_fecha = ItemNumerico(fecha.strftime(formato), fecha.timestamp())
            celda_fecha.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            celda_patente = QTableWidgetItem(patente)
            celda_patente.setFont(fuente_tabular())

            self.tabla_historial.setItem(fila, 0, celda_id)
            self.tabla_historial.setItem(fila, 1, celda_fecha)
            self.tabla_historial.setItem(fila, 2, QTableWidgetItem(cliente))
            self.tabla_historial.setItem(fila, 3, celda_patente)
            self.tabla_historial.setItem(fila, 4, QTableWidgetItem(vehiculo))
            self.tabla_historial.setItem(fila, 5, QTableWidgetItem(mecanico))
            celda_folio = QTableWidgetItem(folio)
            celda_folio.setFont(fuente_tabular())
            self.tabla_historial.setItem(fila, 6, celda_folio)
            # Una orden abonada no es "No pagada": el mesón tiene que ver de
            # un vistazo cuáles quedaron a medio cobrar.
            rotulo, insignia = (
                ("Pagada", BADGE_EXITO) if pagada
                else ("Abonada", BADGE_INFO) if pagado
                else ("No pagada", BADGE_ALERTA)
            )
            estado = QTableWidgetItem(rotulo)
            estado.setData(ROL_INSIGNIA, insignia)
            if rotulo == "Abonada":
                estado.setToolTip(estado_de_pago(pagada, pagado, int(total)))
            rotulo_ot, insignia_ot = ESTADOS[estado_ot]
            celda_estado = QTableWidgetItem(rotulo_ot)
            celda_estado.setData(ROL_INSIGNIA, insignia_ot)
            self.tabla_historial.setItem(fila, 7, celda_estado)
            self.tabla_historial.setItem(fila, 8, estado)
            self.tabla_historial.setItem(fila, 9, ItemNumerico(clp(total), total))

        # Sin folios a la vista la columna es aire que le falta al cliente.
        self.tabla_historial.setColumnHidden(6, not any(f[6] for f in filas))
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
            ultima = db.scalar(
                select(Orden).where(Orden.vehiculo_id == vehiculo_id)
                .order_by(Orden.fecha_creacion.desc(), Orden.id.desc()).limit(1)
            )

            self.label_contexto.setText("OT en proceso")
            self.label_patente.setText(vehiculo.patente)
            self.label_vehiculo.setText(" ".join(filter(None, (
                vehiculo.marca, vehiculo.modelo,
                str(vehiculo.anio_fabricacion) if vehiculo.anio_fabricacion else None,
            ))) or "Vehículo sin marca ni modelo")
            self.label_cliente.setText(" · ".join(filter(None, (
                cliente.nombre_completo, cliente.telefono, vehiculo.color,
            ))))
            # Se copia acá adentro: fuera del `with` los objetos del ORM quedan
            # desprendidos de la sesión y leerles un atributo vuelve a la base.
            self.contacto_whatsapp = {
                "telefono": cliente.telefono or "",
                "cliente": cliente.nombre_completo,
                "vehiculo": describir_vehiculo(
                    vehiculo.patente, vehiculo.marca, vehiculo.modelo,
                    vehiculo.anio_fabricacion,
                ),
            }
            self.ultimo_km = ultima.kilometraje_ingreso if ultima else None
            if ultima is None:
                self.label_servicio.setText("Primer servicio registrado en el sistema.")
            else:
                self.label_servicio.setText(
                    f"Último servicio: OT #{ultima.id} el {ultima.fecha_creacion:%d-%m-%Y}"
                    + (f", con {km(self.ultimo_km)}" if self.ultimo_km is not None else "")
                )
        self.tarjeta.show()
        self.fila_reposo.hide()
        tiene_whatsapp = enlace_whatsapp(self.contacto_whatsapp["telefono"]) is not None
        self.boton_whatsapp.setEnabled(tiene_whatsapp)
        self.boton_whatsapp.setToolTip(
            "" if tiene_whatsapp
            else "El cliente no tiene registrado un celular al que escribirle."
        )
        self.spin_kilometraje.setToolTip(
            f"Último registrado: {km(self.ultimo_km)}" if self.ultimo_km is not None else ""
        )

        self._vaciar_formulario()
        # Cada orden relee el catálogo: la anterior pudo mover el stock.
        self.catalogo.cargar()

        # Desbloquear el panel de trabajo y bloquear el botón de nueva orden
        self.panel_trabajo.setEnabled(True)
        self.boton_nueva_orden.setEnabled(False)
        self.catalogo.busqueda.setFocus()

    def _vaciar_formulario(self) -> None:
        """Deja la pestaña 1 en blanco.

        Vive acá porque estaba copiado tres veces, y una de las copias —la de
        `abrir_detalle_orden`— borraba la orden que se estaba armando con solo
        mirar el historial.
        """
        self.tabla_carrito.setRowCount(0)
        self.spin_kilometraje.setValue(0)
        self.combo_combustible.setCurrentIndex(0)
        self.texto_observaciones.clear()
        self.tipo_descuento.setCurrentIndex(0)
        self.detalles_borrados = []
        self.folio.clear()
        self.pagada.setChecked(False)
        self.abono.setValue(0)
        self.combo_medio_pago.setCurrentIndex(-1)
        self.recalcular_total()

    def _cambiar_pago(self, pagada: bool) -> None:
        """Marcar 'Pagada' es pagar el total, así que el abono sobra."""
        self.abono.setEnabled(not pagada)
        if pagada:
            self.abono.setValue(0)
        self._actualizar_medio()

    def _actualizar_medio(self, *_) -> None:
        cobra = self.pagada.isChecked() or self.abono.value() > 0
        self.combo_medio_pago.setEnabled(cobra)
        if not cobra:
            self.combo_medio_pago.setCurrentIndex(-1)

    def _cambiar_tipo_descuento(self, indice: int) -> None:
        """El campo cambia de forma con el tipo: tope 100 y sufijo % para el
        porcentaje, pesos para el monto, el número impreso para el flyer, y
        apagado sin descuento o con gremio, que no pide nada."""
        self.valor_descuento.setValue(0)
        self.valor_descuento.setEnabled(indice in (1, 2, 3))
        self.valor_descuento.setSpecialValueText("")
        if indice == 1:
            self.valor_descuento.setRange(0, 100)
            self.valor_descuento.setPrefix("")
            self.valor_descuento.setSuffix(" %")
        elif indice == 3:
            self.valor_descuento.setRange(0, convenios.FOLIOS_FLYER[-1])
            self.valor_descuento.setPrefix("N° ")
            self.valor_descuento.setSuffix("")
            self.valor_descuento.setGroupSeparatorShown(False)
            self.valor_descuento.setSpecialValueText("N° del flyer")
        else:
            self.valor_descuento.setRange(0, 99_999_999)
            self.valor_descuento.setPrefix("$ ")
            self.valor_descuento.setSuffix("")
            self.valor_descuento.setGroupSeparatorShown(True)
        self.recalcular_total()

    def _descuento(self, neto: int) -> tuple[int, int, int]:
        """(porcentaje, monto, pesos aplicados) según lo elegido. Solo uno de
        los dos primeros es distinto de cero; es lo que se guarda."""
        tipo, valor = self.tipo_descuento.currentIndex(), self.valor_descuento.value()
        if tipo in CONVENIO_DEL_TIPO:
            # Se recalcula con las líneas de ahora: una orden retomada puede
            # haber ganado un filtro desde que se guardó.
            pesos = convenios.descuento(CONVENIO_DEL_TIPO[tipo], (
                (self.tabla_carrito.item(fila, 0).data(ROL_CATEGORIA),
                 self.tabla_carrito.item(fila, 3).data(Qt.UserRole))
                for fila in range(self.tabla_carrito.rowCount())
            ))
            return 0, pesos, pesos
        if tipo == 1 and valor:
            return valor, 0, int(round(neto * valor / 100))
        if tipo == 2 and valor:
            return 0, valor, min(valor, neto)
        return 0, 0, 0

    def _flyer_disponible(self, folio: int) -> bool:
        """Cada flyer sirve una vez. La base también lo impide; acá es para
        decir en qué orden se usó."""
        if folio not in convenios.FOLIOS_FLYER:
            QMessageBox.warning(self, "Falta el folio del flyer",
                                "Anota el número impreso en el flyer, del 1 al 1000.")
            return False
        with SessionLocal() as db:
            usado_en = db.scalar(select(Orden.id).where(
                Orden.folio_flyer == folio, Orden.estado != "ANULADA",
                Orden.id != (self.orden_abierta_id or 0),
            ))
        if usado_en:
            QMessageBox.warning(self, "Flyer ya usado",
                                f"El flyer N° {folio:04d} ya se usó en la OT #{usado_en}.")
            return False
        return True

    def avisar_por_whatsapp(self) -> None:
        """El aviso se manda sobre la orden abierta, así que sale con los datos
        del vehículo que está en la tarjeta, no con los de una fila elegida."""
        if not self.contacto_whatsapp:
            return
        DialogoWhatsApp(parent=self, **self.contacto_whatsapp).exec()

    def _volver_al_reposo(self) -> None:
        self._vaciar_formulario()
        self.orden_abierta_id = None
        self.detalles_borrados = []
        self.vehiculo_actual_id = None
        self.ultimo_km = None
        self.contacto_whatsapp = None
        self.boton_whatsapp.setEnabled(False)
        self.tarjeta.hide()
        self.panel_trabajo.setEnabled(False)
        self.boton_nueva_orden.setEnabled(True)
        self.label_contexto.setText(REPOSO)
        self.fila_reposo.show()

    def _agregar_elegido(self, item: dict) -> None:
        if "producto_id" in item:
            self.agregar_al_carrito(item["producto_id"])
        else:
            self.agregar_servicio_al_carrito(item["servicio_id"])

    def agregar_al_carrito(self, producto_id: int, cantidad: int = 1) -> None:
        """Si ya está en la orden como línea nueva, suma a esa línea."""
        fila = self._linea_nueva({"producto_id": producto_id})
        previa = 0 if fila is None else self.tabla_carrito.item(fila, 1).data(Qt.UserRole)
        with SessionLocal() as db:
            producto = db.get(Producto, producto_id)
            if not producto:
                return

            # Se relee acá: desde que se cargó el catálogo pudo venderse.
            if producto.stock_actual < previa + cantidad:
                QMessageBox.warning(
                    self, "Stock Insuficiente",
                    f"Solo quedan {producto.stock_actual} unidades de '{producto.nombre}'.",
                )
                return

            nombre, precio = producto.nombre, int(producto.precio_venta)
            categoria = producto.categoria

        if fila is not None:
            self._fijar_cantidad(fila, previa + cantidad)
        else:
            self._insertar_en_carrito({"producto_id": producto_id}, nombre, precio, cantidad,
                                      categoria=categoria)

    def agregar_servicio_al_carrito(self, servicio_id: int, cantidad: int = 1) -> None:
        fila = self._linea_nueva({"servicio_id": servicio_id})
        if fila is not None:
            previa = self.tabla_carrito.item(fila, 1).data(Qt.UserRole)
            self._fijar_cantidad(fila, previa + cantidad)
            return
        with SessionLocal() as db:
            servicio = db.get(Servicio, servicio_id)
            if not servicio:
                return
            nombre, precio = servicio.nombre, int(servicio.precio_venta)
        self._insertar_en_carrito({"servicio_id": servicio_id}, nombre, precio, cantidad)

    def _linea_nueva(self, item: dict) -> int | None:
        """La fila de ese ítem que aún no está en la base. Las guardadas no se
        tocan: el trigger mueve stock al insertar y borrar, no al cambiar."""
        for fila in range(self.tabla_carrito.rowCount()):
            celda = self.tabla_carrito.item(fila, 0)
            if celda.data(Qt.UserRole) == item and celda.data(ROL_DETALLE) is None:
                return fila
        return None

    def _fijar_cantidad(self, fila: int, cantidad: int) -> None:
        precio = self.tabla_carrito.item(fila, 2).data(Qt.UserRole)
        # Sin ordenar mientras se escribe: Qt reubicaría la fila a mitad.
        self.tabla_carrito.setSortingEnabled(False)
        for columna, valor, texto in ((1, cantidad, str(cantidad)),
                                      (3, precio * cantidad, clp(precio * cantidad))):
            celda = ItemNumerico(texto, valor)
            celda.setData(Qt.UserRole, valor)
            self.tabla_carrito.setItem(fila, columna, celda)
        reordenar(self.tabla_carrito)
        self.recalcular_total()

    def cambiar_cantidad(self) -> None:
        """Doble clic en una línea nueva. Una guardada se quita y se agrega de
        nuevo, que es lo que devuelve su stock."""
        fila = self.tabla_carrito.currentRow()
        if fila < 0:
            return
        celda = self.tabla_carrito.item(fila, 0)
        if celda.data(ROL_DETALLE) is not None:
            QMessageBox.information(
                self, "Línea ya guardada",
                "Esta línea ya descontó su stock. Para cambiar la cantidad, quítala y "
                "agrégala de nuevo.",
            )
            return
        item, tope = celda.data(Qt.UserRole), 1000
        if "producto_id" in item:
            with SessionLocal() as db:
                tope = db.scalar(select(Producto.stock_actual)
                                 .where(Producto.id == item["producto_id"])) or 0
            if tope <= 0:
                QMessageBox.warning(self, "Sin stock", f"'{celda.text()}' se quedó sin stock.")
                return
        actual = self.tabla_carrito.item(fila, 1).data(Qt.UserRole)
        stock = f" (stock: {tope})" if "producto_id" in item else ""
        nueva, ok = QInputDialog.getInt(
            self, "Cambiar cantidad", f"Cantidad de '{celda.text()}'{stock}:",
            min(actual, tope), 1, tope, 1,
        )
        if ok:
            self._fijar_cantidad(fila, nueva)

    def _insertar_en_carrito(self, item: dict, nombre: str, precio: int, cantidad: int,
                             detalle_id: int | None = None, categoria: str | None = None) -> None:
        """`detalle_id` marca las líneas que ya están en la base —las de una
        orden retomada—: su stock ya salió, así que al guardar no se insertan
        de nuevo."""
        subtotal = precio * cantidad

        self.tabla_carrito.setSortingEnabled(False)
        fila = self.tabla_carrito.rowCount()
        self.tabla_carrito.insertRow(fila)

        # El ítem ({"producto_id": n} o {"servicio_id": n}), la cantidad y los
        # precios viajan en Qt.UserRole: la tabla es la que guarda la orden en
        # curso, y guardar_orden la lee de vuelta.
        celda_nombre = QTableWidgetItem(nombre)
        celdas = (celda_nombre, ItemNumerico(str(cantidad), cantidad),
                  ItemNumerico(clp(precio), precio), ItemNumerico(clp(subtotal), subtotal))
        for columna, (celda, valor) in enumerate(
            zip(celdas, (item, cantidad, precio, subtotal))
        ):
            celda.setData(Qt.UserRole, valor)
            self.tabla_carrito.setItem(fila, columna, celda)

        celda_nombre.setData(ROL_DETALLE, detalle_id)
        celda_nombre.setData(ROL_CATEGORIA, categoria)
        reordenar(self.tabla_carrito)
        self.recalcular_total()

    def quitar_del_carrito(self) -> None:
        """Saca la fila elegida. Se indexa por la fila visible y eso está bien:
        acá el producto, la cantidad y los precios viajan dentro de la fila, así
        que ordenar la tabla no descalza nada."""
        fila = self.tabla_carrito.currentRow()
        if fila < 0:
            return
        detalle_id = self.tabla_carrito.item(fila, 0).data(ROL_DETALLE)
        if detalle_id is not None:
            # Ya estaba guardada: se borra recién al guardar, y ahí el trigger
            # le devuelve el stock a la bodega.
            self.detalles_borrados.append(detalle_id)
        self.tabla_carrito.removeRow(fila)
        self.recalcular_total()

    def recalcular_total(self) -> None:
        # El valor matemático del subtotal viaja en Qt.UserRole
        suma_total = sum(
            self.tabla_carrito.item(fila, 3).data(Qt.UserRole)
            for fila in range(self.tabla_carrito.rowCount())
        )
        _, _, total = self.totales.calcular(suma_total, self._descuento(suma_total)[2])
        # Nadie abona más de lo que vale la orden, y la orden cambia mientras
        # se arma: el tope se mueve con ella.
        self.abono.setMaximum(total)
        self._actualizar_boton_guardar()

    def _actualizar_boton_guardar(self) -> None:
        """Guardar exige insumos Y kilometraje, y lo dice apagándose."""
        listo = self.tabla_carrito.rowCount() > 0 and self.spin_kilometraje.value() > 0
        self.boton_guardar.setEnabled(listo)
        self.boton_dejar_abierta.setEnabled(listo)

    def retomar_orden(self) -> None:
        """Trae una orden abierta a la mesa de trabajo tal como quedó.

        Sus líneas vienen marcadas con el id que tienen en la base: ya
        descontaron stock, así que al guardar no se insertan de nuevo, y
        sacarlas es lo que se lo devuelve.
        """
        fila = self.tabla_abiertas.currentRow()
        if fila < 0:
            return
        orden_id = self.tabla_abiertas.item(fila, 0).data(Qt.UserRole)

        if self.tabla_carrito.rowCount() and QMessageBox.question(
            self, "Hay una orden en curso",
            "Tienes insumos cargados en la mesa de trabajo. Si retomas otra orden "
            "se descartan. ¿Seguir?",
        ) != QMessageBox.Yes:
            return

        with SessionLocal() as db:
            orden = db.get(Orden, orden_id)
            lineas = [
                ({"producto_id": d.producto_id} if d.producto_id else {"servicio_id": d.servicio_id},
                 (d.producto or d.servicio).nombre, int(d.precio_unitario_cobrado),
                 d.cantidad, d.id, d.producto.categoria if d.producto else None)
                for d in orden.detalles
            ]
            datos = {
                "vehiculo_id": orden.vehiculo_id, "km": orden.kilometraje_ingreso or 0,
                "folio": orden.folio_mercado_publico or "", "notas": orden.notas or "",
                "porcentaje": int(orden.descuento_porcentaje),
                "monto": int(orden.descuento_monto), "pagado": orden.monto_pagado,
                "convenio": orden.convenio, "folio_flyer": orden.folio_flyer,
            }

        # Deja la tarjeta del vehículo y vacía el formulario; después se llena
        # con lo que la orden traía.
        self._iniciar_nueva_orden(datos["vehiculo_id"])
        self.orden_abierta_id = orden_id
        for item, nombre, precio, cantidad, detalle_id, categoria in lineas:
            self._insertar_en_carrito(item, nombre, precio, cantidad, detalle_id, categoria)

        self.spin_kilometraje.setValue(datos["km"])
        self.folio.setText(datos["folio"])
        nivel, observaciones = _leer_notas(datos["notas"])
        if nivel in NIVELES_COMBUSTIBLE:
            self.combo_combustible.setCurrentText(nivel)
        self.texto_observaciones.setPlainText(observaciones)
        # El convenio primero: leído como monto fijo dejaría de seguir a las líneas.
        if datos["convenio"]:
            tipo = next(t for t, c in CONVENIO_DEL_TIPO.items() if c == datos["convenio"])
            self.tipo_descuento.setCurrentIndex(tipo)
            self.valor_descuento.setValue(datos["folio_flyer"] or 0)
        elif datos["porcentaje"]:
            self.tipo_descuento.setCurrentIndex(1)
            self.valor_descuento.setValue(datos["porcentaje"])
        elif datos["monto"]:
            self.tipo_descuento.setCurrentIndex(2)
            self.valor_descuento.setValue(datos["monto"])
        self.recalcular_total()

        abonado = f" · abonado {clp(datos['pagado'])}" if datos["pagado"] else ""
        self.label_servicio.setText(f"Retomando la OT #{orden_id}{abonado}")
        self.setCurrentIndex(0)

    def anular_orden_abierta(self) -> None:
        """Devuelve a la bodega lo que la orden había descontado y la cierra.

        No se borra: queda en el historial marcada, porque el auto entró al
        taller y eso pasó.
        """
        fila = self.tabla_abiertas.currentRow()
        if fila < 0 or not Sesion.activa():
            return
        orden_id = self.tabla_abiertas.item(fila, 0).data(Qt.UserRole)
        if QMessageBox.question(
            self, "Anular la orden",
            f"Se anula la OT #{orden_id} y todo lo que había descontado vuelve a la "
            "bodega, con su movimiento en el Kardex. La orden queda en el historial.",
        ) != QMessageBox.Yes:
            return

        with SessionLocal() as db:
            orden = db.get(Orden, orden_id)
            for linea in list(orden.detalles):
                db.delete(linea)      # el trigger devuelve el stock
            db.flush()
            orden.estado = "ANULADA"
            db.commit()

        if self.orden_abierta_id == orden_id:
            self._volver_al_reposo()
        self.cargar_abiertas()

    def guardar_orden(self, estado: str = "ENTREGADA") -> None:
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
        if self.spin_kilometraje.value() == 0:
            QMessageBox.warning(
                self, "Falta el kilometraje",
                "Anota el kilometraje con que entró el vehículo: es con lo que "
                "se calcula el próximo servicio.",
            )
            return

        # Un kilometraje menor que el del servicio anterior es casi siempre un
        # dedo cambiado; se pregunta, no se prohíbe (hay cambios de tablero).
        if self.ultimo_km is not None and self.spin_kilometraje.value() < self.ultimo_km:
            seguir = QMessageBox.question(
                self, "Kilometraje menor que el anterior",
                f"El servicio anterior registró {km(self.ultimo_km)} y ahora se anotan "
                f"{km(self.spin_kilometraje.value())}. ¿Guardar igual?",
            )
            if seguir != QMessageBox.Yes:
                return

        convenio = CONVENIO_DEL_TIPO.get(self.tipo_descuento.currentIndex())
        folio_flyer = self.valor_descuento.value() if convenio == "FLYER" else None
        if folio_flyer is not None and not self._flyer_disponible(folio_flyer):
            return

        # Capturar totales y empaquetar detalles
        detalles = [
            {
                "detalle_id": self.tabla_carrito.item(fila, 0).data(ROL_DETALLE),
                "item": self.tabla_carrito.item(fila, 0).data(Qt.UserRole),
                "cantidad": self.tabla_carrito.item(fila, 1).data(Qt.UserRole),
                "precio": self.tabla_carrito.item(fila, 2).data(Qt.UserRole),
                "subtotal": self.tabla_carrito.item(fila, 3).data(Qt.UserRole),
            }
            for fila in range(self.tabla_carrito.rowCount())
        ]
        suma_total = sum(d["subtotal"] for d in detalles)
        porcentaje, monto, aplicado = self._descuento(suma_total)
        if folio_flyer is not None and not aplicado:
            # Guardarlo así gastaría el folio del cliente sin darle nada.
            QMessageBox.warning(
                self, "El flyer no descuenta nada",
                "Ningún producto de la orden entra en el flyer (aceite de motor y filtros). "
                "Agrégalos antes, o quita el flyer para no gastar el folio.",
            )
            return
        impuesto, ajuste, total_final = self.totales.calcular(suma_total, aplicado)

        # La caja cuenta el pago según su medio: sin medio no se guarda.
        pagado = total_final if self.pagada.isChecked() else self.abono.value()
        medio = medio_elegido(self.combo_medio_pago)
        if pagado and medio is None:
            QMessageBox.warning(
                self, "Falta el medio de pago",
                "Elige si el cliente pagó en efectivo, con tarjeta o por transferencia.",
            )
            return

        # Armar las notas incluyendo el nivel de combustible
        notas_finales = f"Nivel de Combustible: {self.combo_combustible.currentText()}"
        observaciones = self.texto_observaciones.toPlainText().strip()
        if observaciones:
            notas_finales += f"\nObservaciones: {observaciones}"

        with SessionLocal() as db:
            if self.orden_abierta_id:
                nueva_orden = db.get(Orden, self.orden_abierta_id)
            else:
                nueva_orden = Orden(vehiculo_id=self.vehiculo_actual_id,
                                    usuario_id=Sesion.usuario_id,
                                    estado_pago=self.pagada.isChecked())
                db.add(nueva_orden)
            # `estado_pago` no se vuelve a escribir al actualizar: sale de los
            # abonos contra el total, y de eso se encargan los triggers.
            nueva_orden.kilometraje_ingreso = self.spin_kilometraje.value()
            nueva_orden.descuento_porcentaje = porcentaje
            nueva_orden.descuento_monto = monto
            nueva_orden.convenio, nueva_orden.folio_flyer = convenio, folio_flyer
            nueva_orden.subtotal = suma_total
            nueva_orden.impuesto = impuesto
            nueva_orden.ajuste_redondeo = ajuste
            nueva_orden.total_final = total_final
            nueva_orden.folio_mercado_publico = self.folio.text().strip() or None
            nueva_orden.notas = notas_finales
            nueva_orden.estado = estado
            try:
                db.flush()  # asigna nueva_orden.id sin cerrar la transacción
                # Lo que se sacó de una orden retomada: al borrarlo, el trigger
                # le devuelve el stock a la bodega y lo escribe en el Kardex.
                for detalle_id in self.detalles_borrados:
                    linea = db.get(DetalleOrden, detalle_id)
                    if linea is not None:
                        db.delete(linea)
                db.flush()
                for det in detalles:
                    if det["detalle_id"] is not None:
                        continue      # ya está guardada; su stock ya salió
                    db.add(DetalleOrden(
                        orden_id=nueva_orden.id,
                        cantidad=det["cantidad"],
                        precio_unitario_cobrado=det["precio"],
                        **det["item"],
                    ))
                # Quien decide si con esto queda pagada es el trigger, no esta
                # pantalla.
                if pagado:
                    db.add(PagoOrden(
                        orden_id=nueva_orden.id, usuario_id=Sesion.usuario_id, monto=pagado,
                        medio_pago=medio,
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
                self.catalogo.cargar()
                return
            numero = nueva_orden.id

        QMessageBox.information(
            self, "Orden guardada",
            f"Orden N° {numero} " + ("guardada y entregada." if estado == "ENTREGADA"
                                     else "guardada. El auto queda en el taller."),
        )
        self._volver_al_reposo()
        if estado == "ABIERTA":
            self.cargar_abiertas()

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
        # Adentro se pueden registrar pagos: la insignia de la fila quedaría vieja.
        self.cargar_historial()

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


class DialogoPago(QDialog):
    """Monto y medio de un pago. El tope es el saldo: un pago se suma, no corrige."""

    def __init__(self, saldo: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registrar pago")
        self.setModal(True)

        self.monto = QSpinBox()
        self.monto.setRange(1, saldo)
        self.monto.setValue(saldo)
        self.monto.setPrefix("$ ")
        self.monto.setGroupSeparatorShown(True)
        self.medio = combo_medio_pago()

        saldo_texto = QLabel(f"Saldo pendiente: {clp(saldo)}")
        saldo_texto.setProperty("clase", "resumen")
        layout = layout_de_dialogo(self)
        layout.addWidget(saldo_texto)
        layout.addLayout(barra(QLabel("Monto"), self.monto, estira=1))
        layout.addLayout(barra(QLabel("Medio de pago"), self.medio, estira=1))
        layout.addWidget(botonera(self))
        self.monto.setFocus()
        self.monto.selectAll()

    def accept(self) -> None:
        if medio_elegido(self.medio) is None:
            QMessageBox.warning(
                self, "Falta el medio de pago",
                "Elige si el cliente pagó en efectivo, con tarjeta o por transferencia.",
            )
            return
        super().accept()


class DialogoDetalleOrden(QDialog):
    """Muestra el desglose de una orden guardada, incluyendo productos y notas."""

    def __init__(self, orden_id: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Detalle de Orden N° {orden_id}")
        self.resize(650, 500)
        self.setModal(True)
        self.orden_id = orden_id

        with SessionLocal() as db:
            orden = db.get(Orden, orden_id)
            vehiculo = db.get(Vehiculo, orden.vehiculo_id)
            cliente = db.get(Cliente, vehiculo.cliente_id)
            usuario = db.get(Usuario, orden.usuario_id)

            # Cabecera de contexto. El estado de pago se arma aparte porque
            # cambia sin cerrar el diálogo: acá adentro se registran los abonos.
            self._cabecera = (
                f"<b>Cliente:</b> {cliente.nombre_completo}<br>"
                f"<b>Vehículo:</b> {vehiculo.marca or ''} {vehiculo.modelo or ''} "
                f"({vehiculo.patente})<br>"
                f"<b>Kilometraje:</b> "
                f"{'sin registrar' if orden.kilometraje_ingreso is None else f'{orden.kilometraje_ingreso} km'}<br>"
                f"<b>Mecánico:</b> {usuario.nombre} | "
                f"<b>Fecha:</b> {orden.fecha_creacion.strftime('%d-%m-%Y %H:%M')}<br>"
                f"<b>Estado:</b> "
            )
            self._folio = (f" | <b>Folio MP:</b> {orden.folio_mercado_publico}"
                           if orden.folio_mercado_publico else "")
            if orden.convenio:
                self._folio += (f" | <b>Descuento:</b> "
                                f"{convenios.rotulo(orden.convenio, orden.folio_flyer)}")
            # El aviso por WhatsApp sale de acá con el número de OT: esta orden
            # ya está guardada, a diferencia de la que se está armando al lado.
            self._contacto = {
                "telefono": cliente.telefono or "",
                "cliente": cliente.nombre_completo,
                "vehiculo": describir_vehiculo(
                    vehiculo.patente, vehiculo.marca, vehiculo.modelo,
                    vehiculo.anio_fabricacion,
                ),
            }
            self.total = int(orden.total_final)
            # La relación 'orden.detalles' nos permite acceder a los productos
            # sin hacer joins manuales.
            lineas = [
                ((det.producto or det.servicio).nombre, det.cantidad,
                 int(det.precio_unitario_cobrado))
                for det in orden.detalles
            ]
            notas_guardadas = orden.notas or "Sin observaciones registradas."
            cifras = (orden.subtotal, orden.descuento_aplicado, orden.impuesto, orden.ajuste_redondeo, orden.total_final)

        # Tabla de productos
        tabla = con_aviso_vacio(
            crear_tabla(COLUMNAS_DETALLE, ancha=0, orden=0, numericas=(1, 2, 3)),
            "Orden migrada del sistema antiguo: sin detalle de insumos."
            if notas_guardadas.startswith("Migrada del sistema antiguo")
            else "Esta orden quedó guardada sin insumos cargados.",
        )
        tabla.setRowCount(len(lineas))
        for fila, (nombre, cantidad, precio) in enumerate(lineas):
            subtotal = precio * cantidad
            tabla.setItem(fila, 0, QTableWidgetItem(nombre))
            tabla.setItem(fila, 1, ItemNumerico(str(cantidad), cantidad))
            tabla.setItem(fila, 2, ItemNumerico(clp(precio), precio))
            tabla.setItem(fila, 3, ItemNumerico(clp(subtotal), subtotal))
        reordenar(tabla)
        # Al menos tres filas: con la fila del redondeo en el pie, la tabla
        # quedaba en 26 px. Así crece el diálogo, no se achica la tabla.
        tabla.setMinimumHeight(5 * ALTO_FILA)

        # Observaciones y Nivel de Combustible
        notas = QTextEdit()
        notas.setReadOnly(True)
        notas.setPlainText(notas_guardadas)
        notas.setMaximumHeight(80)

        marco_total, totales = bloque_total("Total final", menor=True)
        totales.fijar(*cifras)

        boton_pdf = QPushButton("Exportar PDF")
        boton_pdf.setAutoDefault(False)
        boton_pdf.clicked.connect(self.exportar_pdf)

        hay_celular = enlace_whatsapp(self._contacto["telefono"]) is not None
        self.boton_whatsapp = QPushButton("Avisar por WhatsApp")
        self.boton_whatsapp.setAutoDefault(False)
        self.boton_whatsapp.setEnabled(hay_celular)
        self.boton_whatsapp.setToolTip(
            "" if hay_celular
            else "El cliente no tiene registrado un celular al que escribirle."
        )
        self.boton_whatsapp.clicked.connect(self.avisar_por_whatsapp)

        self.boton_pago = QPushButton("Registrar pago")
        self.boton_pago.setProperty("clase", "primario")
        self.boton_pago.setAutoDefault(False)
        self.boton_pago.clicked.connect(self.registrar_pago)

        titulo_insumos = QLabel("Insumos y Servicios")
        titulo_insumos.setProperty("clase", "seccion")
        titulo_notas = QLabel("Notas y Combustible")
        titulo_notas.setProperty("clase", "seccion")

        # Ensamble
        self.info = QLabel()
        layout = layout_de_dialogo(self)
        layout.addWidget(self.info)
        layout.addWidget(titulo_insumos)
        layout.addWidget(tabla, 1)
        layout.addWidget(titulo_notas)
        layout.addWidget(notas)
        layout.addWidget(marco_total)
        layout.addLayout(barra(boton_pdf, self.boton_whatsapp, self.boton_pago, estira=0))
        self._refrescar_pago()

    def _refrescar_pago(self) -> None:
        """Relee el pago desde la base.

        Quien decide si la orden quedó pagada es el trigger, así que después de
        un abono hay que preguntárselo a él y no calcularlo acá.
        """
        with SessionLocal() as db:
            orden = db.get(Orden, self.orden_id)
            texto = estado_de_pago(orden.estado_pago, orden.monto_pagado, self.total)
            self.saldo, anulada = orden.saldo, orden.estado == "ANULADA"
        self.info.setText(self._cabecera + texto + self._folio)
        # Una orden anulada no tiene qué cobrar: el trabajo no se hizo y su
        # stock volvió a la bodega.
        self.boton_pago.setEnabled(self.saldo > 0 and not anulada)
        self.boton_pago.setToolTip(
            "Esta orden está anulada." if anulada
            else "" if self.saldo > 0 else "No queda saldo por cobrar."
        )

    def registrar_pago(self) -> None:
        """Un abono se suma a lo ya pagado, no corrige nada: por eso el tope es
        el saldo y no el total."""
        if self.saldo <= 0:
            return  # el botón está apagado; queda el atajo y las pruebas
        dialogo = DialogoPago(self.saldo, self)
        if dialogo.exec() != QDialog.Accepted:
            return
        with SessionLocal() as db:
            db.add(PagoOrden(
                orden_id=self.orden_id, usuario_id=Sesion.usuario_id,
                monto=dialogo.monto.value(), medio_pago=medio_elegido(dialogo.medio),
            ))
            db.commit()
        self._refrescar_pago()

    def avisar_por_whatsapp(self) -> None:
        """Desde una orden guardada el aviso puede citar el número de OT."""
        DialogoWhatsApp(parent=self, orden_id=self.orden_id, **self._contacto).exec()

    def exportar_pdf(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Guardar PDF", str(carpeta_de_documentos("Órdenes") / f"OT-{self.orden_id}.pdf"),
            "PDF (*.pdf)",
        )
        if not ruta:
            return
        guardar_pdf_de_orden(self.orden_id, ruta)
        QMessageBox.information(self, "PDF guardado", f"La orden quedó en:\n{ruta}")
