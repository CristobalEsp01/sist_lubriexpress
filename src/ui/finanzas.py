"""Pestaña de Finanzas: lo que se le debe al taller y lo que el taller debe.

Dos secciones. *Por cobrar*: las órdenes de Mercado Público que esperan factura,
las facturadas y sus abonos, con la mora a 30 días. *Por pagar*: las facturas de
los proveedores con su vencimiento. Las reglas y las cifras viven en
`src/finanzas.py`; acá solo se muestran y se piden los datos.

El supervisor ve el costo de cada cuenta, para revisar que los montos calzan;
el margen es solo del administrador (permiso "margen"), que ve el costo en el
tooltip del margen: las dos columnas no caben a 960 px.
"""
from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .. import finanzas
from ..auth import Sesion
from ..database import SessionLocal
from ..models import CuentaPorCobrar, FacturaProveedor, Proveedor
from ..permisos import puede
from ..precios import con_iva
from ..texto import sin_tildes
from .comunes import (
    BADGE_ACENTO, BADGE_ALERTA, BADGE_EXITO, BADGE_INFO, BADGE_NEUTRAL, ROL_INSIGNIA,
    ItemNumerico, SpinBoxConPrefijo, barra, botonera, clp, con_aviso_vacio,
    crear_tabla, exigir_permiso, hacer_buscable, layout_de_dialogo, layout_de_pantalla, reordenar,
)
from .tema import ALERTA, ESPACIO_PANTALLA, TINTA_SUAVE

MAX_CLP = 99_999_999
SIN_DATO = "—"

# El estado tal como se lee, y el color de su pastilla.
ESTADOS_COBRO = {
    "PENDIENTE_FACTURA": ("Por facturar", BADGE_INFO),
    "POR_COBRAR": ("Por cobrar", BADGE_ACENTO),
    "PAGADA": ("Pagada", BADGE_EXITO),
    "ANULADA": ("Anulada", BADGE_NEUTRAL),
}
FILTROS_COBRO = ["Vigentes", "Morosas", "Por facturar", "Pagadas", "Anuladas", "Todas"]
FILTROS_PAGAR = ["Pendientes", "Vencidas", "Pagadas", "Anuladas", "Todas"]
# El total con IVA y lo pagado van en el tooltip del saldo, y los días de mora
# en la pastilla del estado: con doce columnas el cliente quedaba cortado.
# Ancho desde el que caben Costo y Margen a la vez sin apretar al cliente; el
# portátil del taller (1366 px, maximizada) lo supera de sobra.
ANCHO_PARA_COSTO_Y_MARGEN = 1100
COLUMNAS_COBRO = ["Estado", "Cliente", "OC", "Factura", "Emitida", "Neto",
                  "Saldo", "Costo", "Margen"]
COLUMNAS_PAGAR = ["Estado", "Proveedor", "Factura", "Compra", "Vence", "Total", "Pagado",
                  "Saldo", "Mora"]


def _pesos() -> SpinBoxConPrefijo:
    campo = SpinBoxConPrefijo(maximum=MAX_CLP)
    campo.setGroupSeparatorShown(True)
    campo.setPrefix("$ ")
    campo.setButtonSymbols(QSpinBox.NoButtons)
    return campo


def _fecha(dia: date | None = None, *, hasta_hoy: bool = True) -> QDateEdit:
    campo = QDateEdit(QDate(dia.year, dia.month, dia.day) if dia else QDate.currentDate())
    campo.setCalendarPopup(True)
    campo.setDisplayFormat("dd-MM-yyyy")
    if hasta_hoy:
        campo.setMaximumDate(QDate.currentDate())
    campo.calendarWidget().setFirstDayOfWeek(Qt.Monday)
    return campo


def _texto_fecha(dia: date | None) -> str:
    return dia.strftime("%d-%m-%Y") if dia else SIN_DATO


def _apagar(tabla, fila: int, motivo: str = "") -> None:
    for columna in range(tabla.columnCount()):
        celda = tabla.item(fila, columna)
        celda.setForeground(QColor(TINTA_SUAVE))
        if motivo:
            celda.setToolTip(motivo)


def _numero(tabla, fila: int, columna: int, valor: int | None) -> None:
    """Un monto; sin dato se muestra una raya y ordena al final."""
    celda = ItemNumerico(SIN_DATO if valor is None else clp(valor), -1 if valor is None else valor)
    tabla.setItem(fila, columna, celda)


def _encontrado(texto: str, *campos: str) -> bool:
    """Cada palabra escrita tiene que estar en algún campo, sin mayúsculas ni tildes."""
    conjunto = sin_tildes(" ".join(campos))
    return all(palabra in conjunto for palabra in sin_tildes(texto).split())


def _formulario(dialogo: QDialog, *filas) -> QVBoxLayout:
    """El cuerpo de un diálogo: rótulos a la izquierda y campos alineados."""
    dialogo.setMinimumWidth(440)
    layout = layout_de_dialogo(dialogo)
    form = QFormLayout()
    form.setSpacing(11)
    for rotulo, campo in filas:
        form.addRow(rotulo, campo)
    layout.addLayout(form)
    return layout


class Cifras(QFrame):
    """La franja de cifras de arriba de un listado."""

    def __init__(self, cifras: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setProperty("clase", "total")
        fila = QHBoxLayout(self)
        fila.setSpacing(28)
        fila.setSizeConstraint(QLayout.SetMinimumSize)
        self._cifras: dict[str, QLabel] = {}
        self._notas: dict[str, QLabel] = {}
        self._bloques: dict[str, QWidget] = {}
        for clave, rotulo in cifras:
            bloque = QVBoxLayout()
            bloque.setSpacing(0)
            cifra = QLabel("$0")
            cifra.setProperty("clase", "total-cifra-menor")
            texto = QLabel(rotulo)
            texto.setProperty("clase", "total-rotulo")
            nota = QLabel()
            nota.setProperty("clase", "total-cifra-desglose")
            bloque.addWidget(cifra)
            bloque.addWidget(texto)
            bloque.addWidget(nota)
            contenedor = QWidget()
            contenedor.setLayout(bloque)
            fila.addWidget(contenedor)
            self._cifras[clave], self._notas[clave], self._bloques[clave] = cifra, nota, contenedor
        fila.addStretch()

    def fijar(self, clave: str, monto: int, nota: str = "") -> None:
        self._cifras[clave].setText(clp(monto))
        self._notas[clave].setText(nota)
        self._notas[clave].setVisible(bool(nota))

    def texto(self, clave: str) -> str:
        return self._cifras[clave].text()

    def esconder(self, clave: str) -> None:
        self._bloques[clave].hide()


# --- diálogos ------------------------------------------------------------------

class DialogoFactura(QDialog):
    """Número y fecha de la factura de una orden ya entregada."""

    def __init__(self, cliente: str, detalle: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registrar factura")
        self.setModal(True)
        self.numero = QLineEdit(placeholderText="N° de factura")
        self.numero.setMaxLength(50)
        self.fecha = _fecha()

        resumen = QLabel(f"{cliente}\n{detalle}")
        resumen.setProperty("clase", "resumen")
        resumen.setWordWrap(True)
        layout = layout_de_dialogo(self)
        self.setMinimumWidth(440)
        layout.addWidget(resumen)
        form = QFormLayout()
        form.setSpacing(11)
        form.addRow("Factura N° *", self.numero)
        form.addRow("Fecha de emisión *", self.fecha)
        layout.addLayout(form)
        aviso = QLabel("Al registrarla, el neto, el IVA y el costo quedan fijos: "
                       "si la orden se edita después, la factura no cambia.")
        aviso.setWordWrap(True)
        aviso.setProperty("clase", "resumen")
        layout.addWidget(aviso)
        layout.addWidget(botonera(self))
        self.numero.setFocus()

    def accept(self) -> None:
        if not self.numero.text().strip():
            QMessageBox.warning(self, "Falta el número", "Anota el número de la factura.")
            return
        super().accept()


class DialogoAbono(QDialog):
    """Un abono o pago: monto y fecha. El tope es el saldo."""

    def __init__(self, titulo: str, encabezado: str, saldo: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setModal(True)
        self.monto = _pesos()
        self.monto.setRange(1, saldo)
        self.monto.setValue(saldo)
        self.fecha = _fecha()

        texto = QLabel(f"{encabezado}\nSaldo pendiente: {clp(saldo)}")
        texto.setProperty("clase", "resumen")
        texto.setWordWrap(True)
        layout = layout_de_dialogo(self)
        self.setMinimumWidth(400)
        layout.addWidget(texto)
        form = QFormLayout()
        form.setSpacing(11)
        form.addRow("Monto", self.monto)
        form.addRow("Fecha", self.fecha)
        layout.addLayout(form)
        layout.addWidget(botonera(self))
        self.monto.setFocus()
        self.monto.selectAll()


class DialogoCuentaAnterior(QDialog):
    """Una deuda anterior al módulo, ingresada ya facturada."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ingresar cuenta anterior")
        self.setModal(True)
        self.cliente = QLineEdit(placeholderText="Organismo o cliente")
        self.cliente.setMaxLength(150)
        self.oc = QLineEdit(placeholderText="Opcional")
        self.oc.setMaxLength(50)
        self.factura = QLineEdit(placeholderText="N° de factura")
        self.factura.setMaxLength(50)
        self.fecha = _fecha()
        self.neto = _pesos()
        self.total = QLabel(clp(0))
        self.neto.valueChanged.connect(lambda neto: self.total.setText(clp(con_iva(neto))))
        # Sin dato es distinto de cero: un costo cero infla el margen.
        self.costo = _pesos()
        self.costo.setMinimum(-1)
        self.costo.setValue(-1)
        self.costo.setSpecialValueText("Sin dato")
        self.observaciones = QLineEdit(placeholderText="Opcional")
        self.observaciones.setMaxLength(200)

        layout = _formulario(
            self, ("Cliente *", self.cliente), ("Orden de compra", self.oc),
            ("Factura N° *", self.factura), ("Emitida el *", self.fecha),
            ("Neto *", self.neto), ("Total con IVA", self.total),
            ("Costo", self.costo), ("Observaciones", self.observaciones))
        layout.addWidget(botonera(self))
        self.cliente.setFocus()

    def costo_o_none(self) -> int | None:
        return None if self.costo.value() < 0 else self.costo.value()

    def accept(self) -> None:
        if not self.cliente.text().strip() or not self.factura.text().strip():
            QMessageBox.warning(self, "Faltan datos", "Anota el cliente y el número de factura.")
            return
        if self.neto.value() <= 0:
            QMessageBox.warning(self, "Falta el neto", "El neto tiene que ser mayor que cero.")
            return
        super().accept()


class DialogoProveedor(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nuevo proveedor")
        self.setModal(True)
        self.nombre = QLineEdit(placeholderText="Nombre o razón social")
        self.nombre.setMaxLength(150)
        self.rut = QLineEdit(placeholderText="12.345.678-5 (opcional)")
        self.plazo = QSpinBox(maximum=365, value=30, suffix=" días")
        layout = _formulario(self, ("Nombre *", self.nombre), ("RUT", self.rut),
                             ("Plazo de crédito", self.plazo))
        layout.addWidget(botonera(self))
        self.nombre.setFocus()


class DialogoFacturaProveedor(QDialog):
    """Una factura de proveedor. El vencimiento se propone con el plazo del
    proveedor y se puede corregir."""

    def __init__(self, parent=None, monto_sugerido: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Nueva factura de proveedor")
        self.setModal(True)
        self.proveedor = QComboBox()
        hacer_buscable(self.proveedor)
        self.boton_proveedor = QPushButton("Nuevo…")
        self.boton_proveedor.setAutoDefault(False)
        self.boton_proveedor.clicked.connect(self.nuevo_proveedor)
        self.numero = QLineEdit(placeholderText="N° de factura")
        self.numero.setMaxLength(50)
        self.compra = _fecha()
        self.vence = _fecha(hasta_hoy=False)
        self.monto = _pesos()
        if monto_sugerido > 0:
            # Desde un ingreso de mercadería: costo + IVA, a confirmar con la factura.
            self.monto.setValue(monto_sugerido)
            self.monto.setToolTip("Calculado con el costo ingresado más IVA: corrígelo con el total de la factura.")
        self.observaciones = QLineEdit(placeholderText="Opcional")
        self.observaciones.setMaxLength(200)
        self._plazos: dict[int, int] = {}
        self._cargar_proveedores()
        self.proveedor.currentIndexChanged.connect(self._proponer_vencimiento)
        self.compra.dateChanged.connect(self._proponer_vencimiento)
        self._proponer_vencimiento()

        layout = _formulario(
            self, ("Proveedor *", barra(self.proveedor, self.boton_proveedor)),
            ("Factura N° *", self.numero), ("Fecha de compra *", self.compra),
            ("Vence el *", self.vence), ("Total con IVA *", self.monto),
            ("Observaciones", self.observaciones))
        layout.addWidget(botonera(self))
        self.numero.setFocus()

    def _cargar_proveedores(self, elegido: int | None = None) -> None:
        with SessionLocal() as db:
            proveedores = db.execute(
                select(Proveedor.id, Proveedor.nombre, Proveedor.plazo_credito_dias)
                .where(Proveedor.activo.is_(True)).order_by(Proveedor.nombre)).all()
        self._plazos = {pid: plazo for pid, _, plazo in proveedores}
        self.proveedor.blockSignals(True)
        self.proveedor.clear()
        for pid, nombre, _ in proveedores:
            self.proveedor.addItem(nombre, pid)
        self.proveedor.setCurrentIndex(self.proveedor.findData(elegido) if elegido else
                                       (0 if proveedores else -1))
        self.proveedor.blockSignals(False)

    def _proponer_vencimiento(self, *_) -> None:
        plazo = self._plazos.get(self.proveedor.currentData(), 30)
        self.vence.setDate(self.compra.date().addDays(plazo))

    def nuevo_proveedor(self) -> None:
        dialogo = DialogoProveedor(self)
        while dialogo.exec() == QDialog.Accepted:
            try:
                with SessionLocal() as db:
                    proveedor = finanzas.crear_proveedor(
                        db, dialogo.nombre.text(), dialogo.rut.text(), dialogo.plazo.value())
                    db.commit()
                    nuevo = proveedor.id
            except ValueError as e:
                QMessageBox.warning(self, "No se pudo crear", str(e))
                continue
            except IntegrityError:
                QMessageBox.warning(self, "Proveedor repetido",
                                    "Ya hay un proveedor con ese nombre o ese RUT.")
                continue
            self._cargar_proveedores(nuevo)
            self._proponer_vencimiento()
            return

    def accept(self) -> None:
        if self.proveedor.currentData() is None:
            QMessageBox.warning(self, "Falta el proveedor", "Elige un proveedor o crea uno nuevo.")
            return
        if not self.numero.text().strip() or self.monto.value() <= 0:
            QMessageBox.warning(self, "Faltan datos", "Anota el número y el total de la factura.")
            return
        super().accept()


# --- por cobrar ----------------------------------------------------------------

class PorCobrarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._filas: list[finanzas.FilaCobro] = []
        self.ve_margen = puede("margen")

        self.cifras = Cifras([("por_cobrar", "Por cobrar"), ("moroso", "Moroso (más de 30 días)"),
                              ("sin_factura", "Por facturar"), ("margen_mes", "Margen del mes")])
        if not self.ve_margen:
            self.cifras.esconder("margen_mes")

        self.busqueda = QLineEdit(placeholderText="Buscar por cliente, orden de compra o factura…")
        self.busqueda.textChanged.connect(self.mostrar)
        self.filtro = QComboBox()
        self.filtro.addItems(FILTROS_COBRO)
        self.filtro.currentIndexChanged.connect(self.mostrar)

        self.boton_factura = QPushButton("Registrar factura")
        self.boton_factura.setProperty("clase", "primario")
        self.boton_factura.clicked.connect(self.registrar_factura)
        self.boton_abono = QPushButton("Registrar abono")
        self.boton_abono.clicked.connect(self.registrar_abono)
        self.boton_anterior = QPushButton("Ingresar cuenta anterior")
        self.boton_anterior.clicked.connect(self.ingresar_anterior)
        self.boton_anular = QPushButton("Anular")
        self.boton_anular.setToolTip("Solo cuentas ingresadas a mano y sin abonos")
        self.boton_anular.clicked.connect(self.anular)

        self.tabla = con_aviso_vacio(
            crear_tabla(COLUMNAS_COBRO, ancha=1, orden=4, descendente=True,
                        numericas=(5, 6, 7, 8)),
            "No hay cuentas con este filtro.",
        )
        self.tabla.itemSelectionChanged.connect(self._al_seleccionar)
        # El supervisor ve el costo y no el margen. El administrador ve las dos
        # columnas si la ventana es ancha; si no (960 px, el mínimo) se apaga
        # el costo, que queda en el tooltip del margen: con las dos, el cliente
        # se leía en 73 px. Ver `_ajustar_columnas`.
        if not self.ve_margen:
            self.tabla.setColumnHidden(COLUMNAS_COBRO.index("Margen"), True)
        self._ajustar_columnas()

        layout = layout_de_pantalla(self)
        layout.setSpacing(ESPACIO_PANTALLA)
        layout.addWidget(self.cifras)
        layout.addLayout(barra(self.busqueda, self.filtro, self.boton_factura, self.boton_abono,
                               self.boton_anterior, self.boton_anular, estira=0))
        layout.addWidget(self.tabla, 1)
        self.recargar()
        self._al_seleccionar()

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        self.recargar()

    def recargar(self) -> None:
        with SessionLocal() as db:
            self._filas = finanzas.cuentas_por_cobrar(db)
        resumen = finanzas.resumen_por_cobrar(self._filas)
        self.cifras.fijar("por_cobrar", resumen["por_cobrar"])
        self.cifras.fijar("moroso", resumen["moroso"],
                          f"{resumen['morosas']} cuenta(s) morosa(s)" if resumen["morosas"] else "")
        self.cifras.fijar("sin_factura", resumen["sin_factura_monto"],
                          f"{resumen['sin_factura']} orden(es) sin factura"
                          if resumen["sin_factura"] else "")
        sin_dato = resumen["margen_mes_sin_dato"]
        self.cifras.fijar("margen_mes", resumen["margen_mes"],
                          f"{sin_dato} sin costo, no incluida(s)" if sin_dato else "")
        self.mostrar()

    def _visibles(self) -> list[finanzas.FilaCobro]:
        filtro = self.filtro.currentText()
        cumple = {
            "Vigentes": lambda f: f.estado in ("PENDIENTE_FACTURA", "POR_COBRAR"),
            "Morosas": lambda f: f.dias_mora > 0,
            "Por facturar": lambda f: f.estado == "PENDIENTE_FACTURA",
            "Pagadas": lambda f: f.estado == "PAGADA",
            "Anuladas": lambda f: f.estado == "ANULADA",
            "Todas": lambda f: True,
        }[filtro]
        texto = self.busqueda.text()
        return [f for f in self._filas
                if cumple(f) and _encontrado(texto, f.cliente, f.numero_oc, f.numero_factura)]

    def mostrar(self, *_) -> None:
        filas = self._visibles()
        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(filas))
        for numero, fila in enumerate(filas):
            self._llenar(numero, fila)
        reordenar(self.tabla)
        self._al_seleccionar()

    def _llenar(self, n: int, f: finanzas.FilaCobro) -> None:
        t = self.tabla
        etiqueta, insignia = ESTADOS_COBRO[f.estado]
        if f.dias_mora > 0:
            etiqueta, insignia = f"Morosa · {f.dias_mora} d", BADGE_ALERTA
        estado = QTableWidgetItem(etiqueta)
        estado.setData(ROL_INSIGNIA, insignia)
        estado.setData(Qt.UserRole, f.id)
        t.setItem(n, 0, estado)
        cliente = QTableWidgetItem(f.cliente)
        cliente.setToolTip(f.cliente)
        t.setItem(n, 1, cliente)
        oc = QTableWidgetItem(f.numero_oc)
        oc.setToolTip("Orden de compra o folio de Mercado Público")
        t.setItem(n, 2, oc)
        t.setItem(n, 3, QTableWidgetItem(f.numero_factura or SIN_DATO))
        emitida = ItemNumerico(_texto_fecha(f.fecha_factura),
                               f.fecha_factura.toordinal() if f.fecha_factura else 0)
        t.setItem(n, 4, emitida)
        _numero(t, n, 5, f.neto)
        _numero(t, n, 6, f.saldo)
        _numero(t, n, 7, f.costo)
        _numero(t, n, 8, f.margen)

        if f.estimado:
            _apagar(t, n, "Aún sin factura: las cifras salen de la orden y pueden cambiar.")
        elif f.estado in ("PAGADA", "ANULADA"):
            _apagar(t, n)
        t.item(n, 6).setToolTip(
            f"Total con IVA {'estimado ' if f.estimado else ''}{clp(f.monto)}"
            + ("" if f.estimado else f" · pagado {clp(f.pagado)}"))
        t.item(n, 8).setToolTip("Costo sin dato" if f.costo is None else f"Costo {clp(f.costo)}")

    # -- acciones ------------------------------------------------------

    def _elegida(self) -> finanzas.FilaCobro | None:
        fila = self.tabla.currentRow()
        if fila < 0 or not self.tabla.selectionModel().hasSelection():
            return None
        cuenta_id = self.tabla.item(fila, 0).data(Qt.UserRole)
        return next((f for f in self._filas if f.id == cuenta_id), None)

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        self._ajustar_columnas()

    def _ajustar_columnas(self) -> None:
        """Al administrador se le muestra el costo junto al margen cuando cabe
        (`ANCHO_PARA_COSTO_Y_MARGEN`); en una ventana angosta el costo pasa al
        tooltip del margen. Al supervisor, que no ve el margen, no se le toca."""
        if self.ve_margen:
            self.tabla.setColumnHidden(COLUMNAS_COBRO.index("Costo"),
                                       self.width() < ANCHO_PARA_COSTO_Y_MARGEN)

    def _al_seleccionar(self) -> None:
        f = self._elegida()
        self.boton_factura.setEnabled(f is not None and f.estado == "PENDIENTE_FACTURA")
        self.boton_abono.setEnabled(f is not None and f.estado == "POR_COBRAR")
        self.boton_anular.setEnabled(
            f is not None and f.estado == "POR_COBRAR" and f.orden_id is None and f.pagado == 0)

    def _guardar(self, accion, titulo: str = "No se pudo guardar") -> bool:
        """Corre `accion(db)` y confirma. Lo que la base o las reglas rechazan se
        avisa en vez de reventar."""
        with SessionLocal() as db:
            try:
                accion(db)
                db.commit()
            except (ValueError, IntegrityError) as e:
                db.rollback()
                mensaje = str(getattr(e, "orig", e))
                QMessageBox.warning(self, titulo, mensaje)
                return False
        self.recargar()
        return True

    def registrar_factura(self) -> None:
        f = self._elegida()
        if f is None or f.estado != "PENDIENTE_FACTURA" or not exigir_permiso("finanzas", self):
            return
        dialogo = DialogoFactura(
            f.cliente, f"Orden de compra {f.numero_oc} · neto {clp(f.neto)} · total {clp(f.monto)}", self)
        if dialogo.exec() != QDialog.Accepted:
            return
        self._guardar(lambda db: finanzas.registrar_factura(
            db, db.get(CuentaPorCobrar, f.id), dialogo.numero.text(),
            dialogo.fecha.date().toPython(), Sesion.usuario_id), "No se pudo facturar")

    def registrar_abono(self) -> None:
        f = self._elegida()
        if f is None or f.estado != "POR_COBRAR" or not exigir_permiso("finanzas", self):
            return
        dialogo = DialogoAbono("Registrar abono", f"{f.cliente} · factura {f.numero_factura}",
                               f.saldo, self)
        if dialogo.exec() != QDialog.Accepted:
            return
        self._guardar(lambda db: finanzas.registrar_pago_cobro(
            db, db.get(CuentaPorCobrar, f.id), dialogo.monto.value(),
            dialogo.fecha.date().toPython(), Sesion.usuario_id), "No se pudo abonar")

    def ingresar_anterior(self) -> None:
        if not exigir_permiso("finanzas", self):
            return
        dialogo = DialogoCuentaAnterior(self)
        if dialogo.exec() != QDialog.Accepted:
            return
        self._guardar(lambda db: finanzas.crear_cuenta_manual(
            db, cliente_nombre=dialogo.cliente.text(), numero_factura=dialogo.factura.text(),
            fecha_factura=dialogo.fecha.date().toPython(), venta_neto=dialogo.neto.value(),
            usuario_id=Sesion.usuario_id, numero_oc=dialogo.oc.text(),
            costo=dialogo.costo_o_none(), observaciones=dialogo.observaciones.text()),
            "No se pudo ingresar")

    def anular(self) -> None:
        f = self._elegida()
        if f is None or not exigir_permiso("finanzas", self):
            return
        if QMessageBox.question(
            self, "Anular la cuenta",
            f"Se anula la factura {f.numero_factura} de {f.cliente}. Queda en el "
            "listado como anulada; nada se borra.",
        ) != QMessageBox.Yes:
            return
        self._guardar(lambda db: finanzas.anular_cuenta_manual(
            db, db.get(CuentaPorCobrar, f.id)), "No se pudo anular")


# --- por pagar -----------------------------------------------------------------

class PorPagarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._filas: list[finanzas.FilaPagar] = []
        self.cifras = Cifras([("por_pagar", "Por pagar"), ("vencido", "Vencido")])

        self.busqueda = QLineEdit(placeholderText="Buscar por proveedor o factura…")
        self.busqueda.textChanged.connect(self.mostrar)
        self.filtro = QComboBox()
        self.filtro.addItems(FILTROS_PAGAR)
        self.filtro.currentIndexChanged.connect(self.mostrar)

        self.boton_nueva = QPushButton("Nueva factura")
        self.boton_nueva.setProperty("clase", "primario")
        self.boton_nueva.clicked.connect(self.nueva_factura)
        self.boton_pago = QPushButton("Registrar pago")
        self.boton_pago.clicked.connect(self.registrar_pago)
        self.boton_anular = QPushButton("Anular")
        self.boton_anular.setToolTip("Solo facturas pendientes y sin pagos")
        self.boton_anular.clicked.connect(self.anular)

        self.tabla = con_aviso_vacio(
            crear_tabla(COLUMNAS_PAGAR, ancha=1, orden=4, numericas=(5, 6, 7, 8)),
            "No hay facturas con este filtro.",
        )
        self.tabla.itemSelectionChanged.connect(self._al_seleccionar)

        layout = layout_de_pantalla(self)
        layout.setSpacing(ESPACIO_PANTALLA)
        layout.addWidget(self.cifras)
        layout.addLayout(barra(self.busqueda, self.filtro, self.boton_nueva, self.boton_pago,
                               self.boton_anular, estira=0))
        layout.addWidget(self.tabla, 1)
        self.recargar()
        self._al_seleccionar()

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        self.recargar()

    def recargar(self) -> None:
        with SessionLocal() as db:
            self._filas = finanzas.facturas_por_pagar(db)
        resumen = finanzas.resumen_por_pagar(self._filas)
        self.cifras.fijar("por_pagar", resumen["por_pagar"])
        self.cifras.fijar("vencido", resumen["vencido"],
                          f"{resumen['vencidas']} factura(s) vencida(s)" if resumen["vencidas"] else "")
        self.mostrar()

    def _visibles(self) -> list[finanzas.FilaPagar]:
        cumple = {
            "Pendientes": lambda f: f.estado == "PENDIENTE",
            "Vencidas": lambda f: f.dias_mora > 0,
            "Pagadas": lambda f: f.estado == "PAGADA",
            "Anuladas": lambda f: f.estado == "ANULADA",
            "Todas": lambda f: True,
        }[self.filtro.currentText()]
        texto = self.busqueda.text()
        return [f for f in self._filas if cumple(f) and _encontrado(texto, f.proveedor, f.numero_factura)]

    def mostrar(self, *_) -> None:
        filas = self._visibles()
        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(filas))
        for n, f in enumerate(filas):
            self._llenar(n, f)
        reordenar(self.tabla)
        self._al_seleccionar()

    def _llenar(self, n: int, f: finanzas.FilaPagar) -> None:
        t = self.tabla
        etiqueta, insignia = {"PENDIENTE": ("Pendiente", BADGE_ACENTO), "PAGADA": ("Pagada", BADGE_EXITO),
                              "ANULADA": ("Anulada", BADGE_NEUTRAL)}[f.estado]
        if f.dias_mora > 0:
            etiqueta, insignia = "Vencida", BADGE_ALERTA
        estado = QTableWidgetItem(etiqueta)
        estado.setData(ROL_INSIGNIA, insignia)
        estado.setData(Qt.UserRole, f.id)
        t.setItem(n, 0, estado)
        t.setItem(n, 1, QTableWidgetItem(f.proveedor))
        t.setItem(n, 2, QTableWidgetItem(f.numero_factura))
        t.setItem(n, 3, ItemNumerico(_texto_fecha(f.fecha_compra), f.fecha_compra.toordinal()))
        t.setItem(n, 4, ItemNumerico(_texto_fecha(f.fecha_vencimiento), f.fecha_vencimiento.toordinal()))
        _numero(t, n, 5, f.monto)
        _numero(t, n, 6, f.pagado)
        _numero(t, n, 7, f.saldo)
        t.setItem(n, 8, ItemNumerico(f"{f.dias_mora} d" if f.dias_mora else SIN_DATO, f.dias_mora))
        if f.estado != "PENDIENTE":
            _apagar(t, n)
        elif f.dias_mora:
            t.item(n, 8).setForeground(QColor(ALERTA))

    def _elegida(self) -> finanzas.FilaPagar | None:
        fila = self.tabla.currentRow()
        if fila < 0 or not self.tabla.selectionModel().hasSelection():
            return None
        factura_id = self.tabla.item(fila, 0).data(Qt.UserRole)
        return next((f for f in self._filas if f.id == factura_id), None)

    def _al_seleccionar(self) -> None:
        f = self._elegida()
        self.boton_pago.setEnabled(f is not None and f.estado == "PENDIENTE")
        self.boton_anular.setEnabled(f is not None and f.estado == "PENDIENTE" and f.pagado == 0)

    def _guardar(self, accion, titulo: str) -> bool:
        with SessionLocal() as db:
            try:
                accion(db)
                db.commit()
            except (ValueError, IntegrityError) as e:
                db.rollback()
                QMessageBox.warning(self, titulo, str(getattr(e, "orig", e)))
                return False
        self.recargar()
        return True

    def nueva_factura(self) -> None:
        if not exigir_permiso("finanzas", self):
            return
        dialogo = DialogoFacturaProveedor(self)
        if dialogo.exec() != QDialog.Accepted:
            return
        self._guardar(lambda db: finanzas.registrar_factura_proveedor(
            db, db.get(Proveedor, dialogo.proveedor.currentData()), dialogo.numero.text(),
            dialogo.compra.date().toPython(), dialogo.monto.value(), Sesion.usuario_id,
            fecha_vencimiento=dialogo.vence.date().toPython(),
            observaciones=dialogo.observaciones.text()), "No se pudo ingresar")

    def registrar_pago(self) -> None:
        f = self._elegida()
        if f is None or f.estado != "PENDIENTE" or not exigir_permiso("finanzas", self):
            return
        dialogo = DialogoAbono("Registrar pago", f"{f.proveedor} · factura {f.numero_factura}",
                               f.saldo, self)
        if dialogo.exec() != QDialog.Accepted:
            return
        self._guardar(lambda db: finanzas.registrar_pago_proveedor(
            db, db.get(FacturaProveedor, f.id), dialogo.monto.value(),
            dialogo.fecha.date().toPython(), Sesion.usuario_id), "No se pudo pagar")

    def anular(self) -> None:
        f = self._elegida()
        if f is None or not exigir_permiso("finanzas", self):
            return
        if QMessageBox.question(
            self, "Anular la factura",
            f"Se anula la factura {f.numero_factura} de {f.proveedor}. Queda en el "
            "listado como anulada; nada se borra.",
        ) != QMessageBox.Yes:
            return
        self._guardar(lambda db: finanzas.anular_factura_proveedor(
            db, db.get(FacturaProveedor, f.id)), "No se pudo anular")


class FinanzasWidget(QTabWidget):
    """Las dos secciones. Cada una se relee al mostrarse."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.por_cobrar = PorCobrarWidget(self)
        self.por_pagar = PorPagarWidget(self)
        self.addTab(self.por_cobrar, "Por cobrar")
        self.addTab(self.por_pagar, "Por pagar")
