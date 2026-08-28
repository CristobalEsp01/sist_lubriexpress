"""Mantenedor de Clientes y sus vehículos."""
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QSplitter, QTableWidgetItem,
    QVBoxLayout, QWidget,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..database import SessionLocal
from ..models import Cliente, Vehiculo
from ..rut import es_valido, formatear
from ..texto import columna_normalizada, filtro_busqueda
from .comunes import (
    BADGE_ACENTO, BADGE_INFO, BADGE_NEUTRAL, ROL_INSIGNIA,
    ItemNumerico, barra, botonera, con_aviso_vacio, crear_tabla,
    layout_de_dialogo, layout_de_pantalla, reordenar,
)
from .tema import CANAL_PANEL, fuente_tabular

COLUMNAS_CLIENTE = ["RUT", "Nombre", "Tipo", "Teléfono", "Vehículos"]
COLUMNAS_VEHICULO = ["Patente", "Marca", "Modelo", "Año", "Combustible", "Transmisión"]
# Sugerencias, no restricciones: el esquema acepta texto libre y los combos son editables.
COMBUSTIBLES = ["", "Bencina", "Diésel", "Eléctrico", "Híbrido", "GLP"]
TRANSMISIONES = ["", "Manual", "Automática", "CVT"]
TRACCIONES = ["", "4x2", "4x4", "AWD"]
PATENTE = re.compile(r"^([A-Z]{2}\d{4}|[A-Z]{4}\d{2})$")


class FormularioCliente(QDialog):
    """Alta y edición de un cliente."""

    def __init__(self, parent=None, cliente_id: int | None = None):
        super().__init__(parent)
        self.cliente_id = cliente_id
        self.setWindowTitle("Nuevo cliente" if cliente_id is None else "Editar cliente")
        self.setMinimumWidth(420)

        self.rut = QLineEdit(placeholderText="12.345.678-5")
        self.etiqueta_rut = QLabel()
        self.nombre = QLineEdit(placeholderText="Ej: Juan Pérez / Transportes Sur SpA")
        self.tipo = QComboBox()
        self.tipo.addItems(["PERSONA", "EMPRESA"])
        self.telefono = QLineEdit(placeholderText="+56 9 1234 5678")

        form = QFormLayout()
        form.setSpacing(12)
        form.addRow(self.etiqueta_rut, self.rut)
        form.addRow("Nombre / Razón social *", self.nombre)
        form.addRow("Tipo", self.tipo)
        form.addRow("Teléfono", self.telefono)

        self.tipo.currentTextChanged.connect(self._marcar_rut)
        self._marcar_rut(self.tipo.currentText())

        botones = botonera(self)

        layout = layout_de_dialogo(self)
        layout.addLayout(form)
        layout.addWidget(botones)

        if cliente_id is not None:
            self._cargar()

    def _marcar_rut(self, tipo: str) -> None:
        """El asterisco no puede mentir: el RUT solo es obligatorio para empresas."""
        self.etiqueta_rut.setText("RUT *" if tipo == "EMPRESA" else "RUT")

    def _cargar(self) -> None:
        with SessionLocal() as db:
            c = db.get(Cliente, self.cliente_id)
            self.rut.setText(c.rut or "")
            self.nombre.setText(c.nombre_completo)
            self.tipo.setCurrentText(c.tipo_cliente)
            self.telefono.setText(c.telefono or "")

    def accept(self) -> None:
        rut = self.rut.text().strip()
        if rut and not es_valido(rut):
            QMessageBox.warning(
                self, "RUT inválido",
                "El dígito verificador no corresponde. Revisa el RUT antes de guardar.",
            )
            return
        if not rut and self.tipo.currentText() == "EMPRESA":
            QMessageBox.warning(
                self, "Falta el RUT",
                "Las empresas y los servicios públicos necesitan RUT para facturarles.",
            )
            return
        if not self.nombre.text().strip():
            QMessageBox.warning(self, "Falta el nombre", "El cliente necesita un nombre.")
            return
        if self.guardar():
            super().accept()

    def guardar(self) -> bool:
        rut = self.rut.text().strip()
        with SessionLocal() as db:
            cliente = db.get(Cliente, self.cliente_id) if self.cliente_id else Cliente()
            cliente.rut = formatear(rut) or None
            cliente.nombre_completo = self.nombre.text().strip()
            cliente.tipo_cliente = self.tipo.currentText()
            cliente.telefono = self.telefono.text().strip() or None
            if self.cliente_id is None:
                db.add(cliente)
            try:
                db.commit()
            except IntegrityError as e:
                db.rollback()
                # Ya no hay una sola forma de fallar: además del UNIQUE están el
                # CHECK de empresa sin RUT y las bases que todavía no corrieron la
                # migración. Dar el mensaje equivocado esconde la causa real.
                if "clientes_rut_key" in str(e.orig):
                    QMessageBox.warning(
                        self, "RUT repetido",
                        f"Ya existe un cliente con el RUT {formatear(rut)}.",
                    )
                else:
                    QMessageBox.warning(
                        self, "No se pudo guardar",
                        f"La base de datos rechazó el cliente:\n\n{e.orig}",
                    )
                return False
            self.cliente_id = cliente.id
        return True



class FormularioVehiculo(QDialog):
    """Alta y edición de un vehículo, siempre colgando de un cliente."""

    def __init__(self, parent=None, cliente_id: int | None = None, vehiculo_id: int | None = None):
        super().__init__(parent)
        self.cliente_id = cliente_id
        self.vehiculo_id = vehiculo_id
        self.setWindowTitle("Nuevo vehículo" if vehiculo_id is None else "Editar vehículo")
        self.setMinimumWidth(420)

        self.patente = QLineEdit(placeholderText="BBBB12 / AA1234")
        self.marca = QLineEdit(placeholderText="Ej: Toyota, Chevrolet, Nissan")
        self.modelo = QLineEdit(placeholderText="Ej: Hilux, Sail, Versa")
        self.anio = QSpinBox(minimum=1899, maximum=2100)
        self.anio.setSpecialValueText("Sin dato")
        self.color = QLineEdit(placeholderText="Ej: Blanco, Gris Plata, Rojo")
        self.combustible = self._combo(COMBUSTIBLES)
        self.transmision = self._combo(TRANSMISIONES)
        self.traccion = self._combo(TRACCIONES)
        self.cilindrada = QLineEdit(placeholderText="Ej: 1.6, 2.0, 2.8 Turbo")

        form = QFormLayout()
        form.setSpacing(12)
        form.addRow("Patente *", self.patente)
        form.addRow("Marca", self.marca)
        form.addRow("Modelo", self.modelo)
        form.addRow("Año", self.anio)
        form.addRow("Color", self.color)
        form.addRow("Combustible", self.combustible)
        form.addRow("Transmisión", self.transmision)
        form.addRow("Tracción", self.traccion)
        form.addRow("Cilindrada", self.cilindrada)

        botones = botonera(self)

        layout = layout_de_dialogo(self)
        layout.addLayout(form)
        layout.addWidget(botones)

        if vehiculo_id is not None:
            self._cargar()

    @staticmethod
    def _combo(opciones: list[str]) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(opciones)
        return combo

    def _cargar(self) -> None:
        with SessionLocal() as db:
            v = db.get(Vehiculo, self.vehiculo_id)
            self.cliente_id = v.cliente_id
            self.patente.setText(v.patente)
            self.marca.setText(v.marca or "")
            self.modelo.setText(v.modelo or "")
            self.anio.setValue(v.anio_fabricacion or 1899)
            self.color.setText(v.color or "")
            self.combustible.setCurrentText(v.combustible or "")
            self.transmision.setCurrentText(v.transmision or "")
            self.traccion.setCurrentText(v.traccion or "")
            self.cilindrada.setText(v.cilindrada or "")

    def patente_normalizada(self) -> str:
        return re.sub(r"[.\-\s]", "", self.patente.text()).upper()

    def accept(self) -> None:
        patente = self.patente_normalizada()
        if not patente:
            QMessageBox.warning(self, "Falta la patente", "El vehículo necesita una patente.")
            return
        if not PATENTE.match(patente):
            confirmar = QMessageBox.question(
                self, "Patente con formato raro",
                f"'{patente}' no parece una patente chilena (BBBB12 o AA1234). ¿Guardar igual?",
            )
            if confirmar != QMessageBox.Yes:
                return
        if self.guardar(patente):
            super().accept()

    def guardar(self, patente: str) -> bool:
        with SessionLocal() as db:
            vehiculo = db.get(Vehiculo, self.vehiculo_id) if self.vehiculo_id else Vehiculo()
            vehiculo.cliente_id = self.cliente_id
            vehiculo.patente = patente
            vehiculo.marca = self.marca.text().strip() or None
            vehiculo.modelo = self.modelo.text().strip() or None
            vehiculo.anio_fabricacion = self.anio.value() if self.anio.value() > 1899 else None
            vehiculo.color = self.color.text().strip() or None
            vehiculo.combustible = self.combustible.currentText().strip() or None
            vehiculo.transmision = self.transmision.currentText().strip() or None
            vehiculo.traccion = self.traccion.currentText().strip() or None
            vehiculo.cilindrada = self.cilindrada.text().strip() or None
            if self.vehiculo_id is None:
                db.add(vehiculo)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                QMessageBox.warning(
                    self, "Patente repetida",
                    f"La patente {patente} ya está registrada en otro cliente.",
                )
                return False
            self.vehiculo_id = vehiculo.id
        return True



class ClientesWidget(QWidget):
    """Clientes arriba, vehículos del cliente seleccionado abajo."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.busqueda = QLineEdit(placeholderText="Buscar por patente, nombre o RUT…")
        self.busqueda.setClearButtonEnabled(True)
        self.busqueda.textChanged.connect(self.recargar)

        boton_nuevo = QPushButton("Nuevo cliente")
        boton_nuevo.setProperty("clase", "primario")
        boton_nuevo.clicked.connect(self.nuevo_cliente)
        # Los botones que necesitan una fila elegida nacen apagados y se
        # encienden con la selección, como en Inventario: avisar con un cartel
        # después del click es hacer preguntar por algo que se puede mostrar.
        self.boton_editar = QPushButton("Editar cliente")
        self.boton_editar.setEnabled(False)
        self.boton_editar.clicked.connect(self.editar_cliente)

        self.tabla = con_aviso_vacio(
            crear_tabla(COLUMNAS_CLIENTE, ancha=1, orden=1, numericas=(4,)),
            "No hay clientes registrados.",
        )  # ordena por Nombre
        self.tabla.itemSelectionChanged.connect(self.recargar_vehiculos)
        self.tabla.doubleClicked.connect(self.editar_cliente)

        self.tabla_vehiculos = con_aviso_vacio(
            crear_tabla(COLUMNAS_VEHICULO, ancha=2, orden=0, numericas=(3,)),
            "Elige un cliente para ver sus vehículos.",
        )  # ordena por Patente
        self.tabla_vehiculos.doubleClicked.connect(self.editar_vehiculo)
        self.tabla_vehiculos.itemSelectionChanged.connect(self._actualizar_boton_vehiculo)

        self.titulo_vehiculos = QLabel("Vehículos")
        self.titulo_vehiculos.setProperty("clase", "seccion")
        self.boton_nuevo_vehiculo = QPushButton("Agregar vehículo")
        self.boton_nuevo_vehiculo.clicked.connect(self.nuevo_vehiculo)
        self.boton_editar_vehiculo = QPushButton("Editar vehículo")
        self.boton_editar_vehiculo.setEnabled(False)
        self.boton_editar_vehiculo.clicked.connect(self.editar_vehiculo)

        self.resumen = QLabel()
        self.resumen.setProperty("clase", "resumen")

        barra_clientes = barra(self.busqueda, boton_nuevo, self.boton_editar)
        barra_vehiculos = barra(
            self.titulo_vehiculos, self.boton_nuevo_vehiculo, self.boton_editar_vehiculo,
        )

        arriba = QWidget()
        layout_arriba = QVBoxLayout(arriba)
        layout_arriba.setContentsMargins(0, 0, 0, CANAL_PANEL)
        layout_arriba.addLayout(barra_clientes)
        layout_arriba.addWidget(self.tabla)

        abajo = QWidget()
        layout_abajo = QVBoxLayout(abajo)
        layout_abajo.setContentsMargins(0, CANAL_PANEL, 0, 0)
        layout_abajo.addLayout(barra_vehiculos)
        layout_abajo.addWidget(self.tabla_vehiculos)

        division = QSplitter(Qt.Vertical)
        division.setHandleWidth(1)
        division.addWidget(arriba)
        division.addWidget(abajo)
        division.setSizes([380, 220])

        layout = layout_de_pantalla(self)
        layout.addWidget(division)
        layout.addWidget(self.resumen)

        self.recargar()

    def recargar(self) -> None:
        consulta = filtro_busqueda(
            select(Cliente, func.count(Vehiculo.id))
            .outerjoin(Vehiculo)
            .group_by(Cliente.id)
            .order_by(Cliente.nombre_completo),
            self.busqueda.text(),
            Cliente.rut, Cliente.nombre_completo,
            # any() genera un EXISTS: filtrar por el join descuadraría el
            # count(Vehiculo.id) y un cliente con 3 autos aparecería con 1.
            tambien=lambda aguja: Cliente.vehiculos.any(
                columna_normalizada(Vehiculo.patente).like(aguja)
            ),
        )

        with SessionLocal() as db:
            filas = [
                (c.id, c.rut or "", c.nombre_completo, c.tipo_cliente, c.telefono or "", n)
                for c, n in db.execute(consulta).all()
            ]

        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(filas))
        for fila, (cid, rut, nombre, tipo, telefono, vehiculos) in enumerate(filas):
            for columna, texto_celda in enumerate([rut, nombre, tipo.capitalize(), telefono]):
                item = QTableWidgetItem(texto_celda)
                if columna == 0:
                    item.setFont(fuente_tabular())
                    item.setData(Qt.UserRole, cid)
                elif columna == 2:
                    # Pastilla distintiva para Empresa / Persona
                    item.setData(ROL_INSIGNIA, BADGE_INFO if tipo == "EMPRESA" else BADGE_NEUTRAL)
                self.tabla.setItem(fila, columna, item)

            item_veh = ItemNumerico(str(vehiculos), vehiculos)
            if vehiculos > 0:
                item_veh.setData(ROL_INSIGNIA, BADGE_ACENTO)
            self.tabla.setItem(fila, 4, item_veh)
        reordenar(self.tabla)

        self.tabla.aviso.setText(
            "Ningún cliente coincide con la búsqueda." if self.busqueda.text().strip()
            else "No hay clientes registrados."
        )
        self.resumen.setText(f"{len(filas)} cliente(s)")
        self.recargar_vehiculos()

    def cliente_seleccionado(self) -> int | None:
        fila = self.tabla.currentRow()
        if fila < 0 or not self.tabla.item(fila, 0):
            return None
        return self.tabla.item(fila, 0).data(Qt.UserRole)

    def vehiculo_seleccionado(self) -> int | None:
        fila = self.tabla_vehiculos.currentRow()
        if fila < 0 or not self.tabla_vehiculos.item(fila, 0):
            return None
        return self.tabla_vehiculos.item(fila, 0).data(Qt.UserRole)

    def _actualizar_boton_vehiculo(self) -> None:
        self.boton_editar_vehiculo.setEnabled(self.vehiculo_seleccionado() is not None)

    def recargar_vehiculos(self) -> None:
        cliente_id = self.cliente_seleccionado()
        hay_cliente = cliente_id is not None
        self.boton_editar.setEnabled(hay_cliente)
        self.boton_nuevo_vehiculo.setEnabled(hay_cliente)
        self._actualizar_boton_vehiculo()

        if not hay_cliente:
            self.titulo_vehiculos.setText("Vehículos")
            self.tabla_vehiculos.aviso.setText("Elige un cliente para ver sus vehículos.")
            self.tabla_vehiculos.setRowCount(0)
            return

        with SessionLocal() as db:
            cliente = db.get(Cliente, cliente_id)
            nombre = cliente.nombre_completo
            filas = [
                (v.id, v.patente, v.marca or "", v.modelo or "",
                 v.anio_fabricacion, v.combustible or "", v.transmision or "")
                for v in db.scalars(
                    select(Vehiculo).where(Vehiculo.cliente_id == cliente_id).order_by(Vehiculo.patente)
                )
            ]

        self.titulo_vehiculos.setText(f"Vehículos de {nombre} ({len(filas)})")
        self.tabla_vehiculos.aviso.setText("Este cliente no tiene vehículos registrados.")
        self.tabla_vehiculos.setSortingEnabled(False)
        self.tabla_vehiculos.setRowCount(len(filas))
        for fila, (vid, patente, marca, modelo, anio, combustible, transmision) in enumerate(filas):
            item_patente = QTableWidgetItem(patente)
            item_patente.setFont(fuente_tabular())
            item_patente.setData(Qt.UserRole, vid)
            self.tabla_vehiculos.setItem(fila, 0, item_patente)
            self.tabla_vehiculos.setItem(fila, 1, QTableWidgetItem(marca))
            self.tabla_vehiculos.setItem(fila, 2, QTableWidgetItem(modelo))
            self.tabla_vehiculos.setItem(fila, 3, ItemNumerico(str(anio or ""), anio or 0))

            item_comb = QTableWidgetItem(combustible)
            if combustible:
                item_comb.setData(ROL_INSIGNIA, BADGE_NEUTRAL)
            self.tabla_vehiculos.setItem(fila, 4, item_comb)

            self.tabla_vehiculos.setItem(fila, 5, QTableWidgetItem(transmision))
        reordenar(self.tabla_vehiculos)

    def nuevo_cliente(self) -> None:
        if FormularioCliente(self).exec():
            self.recargar()

    def editar_cliente(self) -> None:
        cliente_id = self.cliente_seleccionado()
        if cliente_id is None:
            return  # el botón está apagado; solo queda el doble click al vacío
        if FormularioCliente(self, cliente_id).exec():
            self.recargar()

    def nuevo_vehiculo(self) -> None:
        cliente_id = self.cliente_seleccionado()
        if cliente_id is None:
            return
        if FormularioVehiculo(self, cliente_id=cliente_id).exec():
            self.recargar()

    def editar_vehiculo(self) -> None:
        vehiculo_id = self.vehiculo_seleccionado()
        if vehiculo_id is None:
            return  # el botón está apagado; solo queda el doble click al vacío
        if FormularioVehiculo(self, vehiculo_id=vehiculo_id).exec():
            self.recargar()

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        self.busqueda.setFocus()


