"""Caja chica del día: cuánta plata debería haber en el cajón de la oficina.

La caja no se abre ni se cierra a mano —el día de una caja es su fecha, así que
abre y cierra sola—. Acá se anota el efectivo que se deja en la mañana y los
gastos del día; lo cobrado por ventas y abonos se suma solo, de donde ya está
guardado. Las cifras viven en `src/caja.py`, sin Qt.
"""
from datetime import date, datetime

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QColor, QImage, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import (
    QDateEdit, QDialog, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit, QMessageBox,
    QPushButton, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import caja
from ..auth import Sesion
from ..database import SessionLocal
from ..documentos import html_de_caja
from ..models import MovimientoCaja
from .comunes import (
    BADGE_ALERTA, BADGE_EXITO, BADGE_NEUTRAL, ROL_INSIGNIA, ItemNumerico, ajustar_columnas,
    barra, botonera, carpeta_de_documentos, clp, con_aviso_vacio, crear_tabla,
    layout_de_dialogo, layout_de_pantalla,
)
from .inventario import FormularioProducto
from .tema import ALERTA, ESPACIO_PANTALLA, EXITO, LOGO, TINTA_SUAVE

COLUMNAS = ["Hora", "Tipo", "Motivo", "Monto", "Registró"]
ROTULOS = [("agregado", "Agregado"), ("ingresos", "Ingresos"),
           ("egresos", "Egresos"), ("balance", "Balance")]


class MovimientoDialog(QDialog):
    """Agregar dinero o registrar un gasto. Nada se edita después: corregir es
    anular, que inserta la inversa."""

    def __init__(self, parent=None, tipo: str = "INGRESO", propuesta: int = 0, aviso: str = ""):
        super().__init__(parent)
        self.tipo = tipo
        es_ingreso = tipo == "INGRESO"
        self.setWindowTitle("Agregar dinero a la caja" if es_ingreso else "Registrar un gasto")
        self.setModal(True)

        self.monto = FormularioProducto._campo_pesos()
        self.monto.setValue(propuesta)
        self.motivo = QLineEdit()
        self.motivo.setMaxLength(200)
        self.motivo.setPlaceholderText(
            "Efectivo para vuelto" if es_ingreso else "Ej: bencina, almuerzo, flete")

        layout = layout_de_dialogo(self)
        if aviso:
            etiqueta = QLabel(aviso)
            etiqueta.setWordWrap(True)
            etiqueta.setProperty("clase", "resumen")
            layout.addWidget(etiqueta)
        layout.addLayout(barra(QLabel("Monto"), self.monto, estira=1))
        layout.addLayout(barra(QLabel("Motivo"), self.motivo, estira=1))
        layout.addWidget(botonera(self))
        self.monto.setFocus()

    def accept(self) -> None:
        if self.monto.value() <= 0:
            QMessageBox.warning(self, "Falta el monto", "El monto tiene que ser mayor que cero.")
            return
        if not self.motivo.text().strip():
            # Un gasto sin motivo no sirve para nada el día que hay que cuadrar.
            QMessageBox.warning(self, "Falta el motivo", "Escribe de qué se trata.")
            return
        super().accept()


class CajaWidget(QWidget):
    """La caja de un día: sus cifras, sus movimientos y el PDF para archivar."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.fecha = QDateEdit(QDate.currentDate())
        self.fecha.setCalendarPopup(True)
        self.fecha.setDisplayFormat("dd-MM-yyyy")
        # No hay caja del futuro: mirarla solo confunde.
        self.fecha.setMaximumDate(QDate.currentDate())
        self.fecha.calendarWidget().setFirstDayOfWeek(Qt.Monday)
        self.fecha.dateChanged.connect(self.recargar)

        self.cifras = QHBoxLayout()
        self.cifras.setSpacing(28)
        # Sin esto las cifras se encabalgan unas sobre otras al angostar.
        self.cifras.setSizeConstraint(QLayout.SetMinimumSize)
        marco = QFrame()
        marco.setProperty("clase", "total")
        marco.setLayout(self.cifras)
        self._etiquetas = {}
        for clave, rotulo in ROTULOS:
            bloque = QVBoxLayout()
            bloque.setSpacing(0)
            cifra = QLabel("$0")
            cifra.setProperty("clase", "total-cifra" if clave == "balance" else "total-cifra-menor")
            texto = QLabel(rotulo)
            texto.setProperty("clase", "total-rotulo")
            bloque.addWidget(cifra)
            bloque.addWidget(texto)
            contenedor = QWidget()
            contenedor.setLayout(bloque)
            self.cifras.addWidget(contenedor)
            self._etiquetas[clave] = cifra
        self.cifras.addStretch()

        self.tabla = con_aviso_vacio(
            crear_tabla(COLUMNAS, ancha=2, orden=0, numericas=(3,)),
            "Ningún movimiento a mano este día.",
        )
        self.tabla.itemSelectionChanged.connect(self._al_seleccionar)

        self.boton_dinero = QPushButton("Agregar dinero")
        self.boton_dinero.setProperty("clase", "primario")
        self.boton_dinero.clicked.connect(lambda: self.registrar("INGRESO"))
        self.boton_gasto = QPushButton("Agregar gasto")
        self.boton_gasto.clicked.connect(lambda: self.registrar("EGRESO"))
        self.boton_anular = QPushButton("Anular")
        self.boton_anular.setEnabled(False)
        self.boton_anular.setToolTip("Inserta el movimiento inverso: nada se borra")
        self.boton_anular.clicked.connect(self.anular)
        self.boton_pdf = QPushButton("Guardar caja en PDF")
        self.boton_pdf.clicked.connect(self.guardar_pdf)

        self.ayuda = QLabel(
            "Lo cobrado por ventas y por abonos de órdenes entra solo. Acá se anota "
            "el efectivo que se deja en el cajón y los gastos del día."
        )
        self.ayuda.setWordWrap(True)
        self.ayuda.setProperty("clase", "resumen")

        layout = layout_de_pantalla(self)
        layout.setSpacing(ESPACIO_PANTALLA)
        # El estirón va en un espaciador: con él en un botón, ese botón se come
        # el ancho de la ventana.
        layout.addLayout(barra(QLabel("Día"), self.fecha, QWidget(), self.boton_dinero,
                               self.boton_gasto, self.boton_anular, self.boton_pdf, estira=2))
        layout.addWidget(marco)
        layout.addWidget(self.ayuda)
        layout.addWidget(self.tabla, 1)
        self.recargar()

    # -- datos ---------------------------------------------------------

    def dia(self) -> date:
        return self.fecha.date().toPython()

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        self.recargar()

    def recargar(self) -> None:
        dia = self.dia()
        with SessionLocal() as db:
            cifras = caja.resumen(db, dia)
            filas = caja.movimientos(db, dia)

        for clave, _ in ROTULOS:
            self._etiquetas[clave].setText(clp(cifras[clave]))

        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(filas))
        for numero, fila in enumerate(filas):
            hora = ItemNumerico(fila.hora.strftime("%H:%M"), fila.hora.timestamp())
            hora.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            hora.setData(Qt.UserRole, fila.id)
            self.tabla.setItem(numero, 0, hora)

            tipo = QTableWidgetItem("Ingreso" if fila.tipo == "INGRESO" else "Gasto")
            tipo.setData(ROL_INSIGNIA,
                         BADGE_NEUTRAL if fila.anulado
                         else BADGE_EXITO if fila.tipo == "INGRESO" else BADGE_ALERTA)
            self.tabla.setItem(numero, 1, tipo)
            self.tabla.setItem(numero, 2, QTableWidgetItem(fila.motivo))

            monto = ItemNumerico(clp(fila.monto), fila.monto)
            if not fila.anulado:
                monto.setForeground(QColor(EXITO if fila.tipo == "INGRESO" else ALERTA))
            self.tabla.setItem(numero, 3, monto)
            self.tabla.setItem(numero, 4, QTableWidgetItem(fila.usuario))

            # Un par anulado sigue en la lista, apagado: la caja es de solo
            # agregado y borrar una fila sería justamente lo que no se hace.
            if fila.anulado:
                for columna in range(self.tabla.columnCount()):
                    celda = self.tabla.item(numero, columna)
                    celda.setForeground(QColor(TINTA_SUAVE))
                    celda.setToolTip("Anulado: no cuenta para las cifras del día")
        ajustar_columnas(self.tabla)
        self._al_seleccionar()

    def _al_seleccionar(self) -> None:
        self.boton_anular.setEnabled(
            self.tabla.selectionModel().hasSelection() and not self._anulado_seleccionado()
        )

    def _anulado_seleccionado(self) -> bool:
        fila = self.tabla.currentRow()
        return fila < 0 or bool(self.tabla.item(fila, 0).toolTip())

    # -- acciones ------------------------------------------------------

    def registrar(self, tipo: str) -> None:
        if not Sesion.activa():
            QMessageBox.critical(self, "Error", "No hay sesión activa.")
            return

        propuesta, aviso = 0, ""
        if tipo == "INGRESO":
            # Lo que quedó ayer en el cajón suele ser lo que se deja hoy;
            # retipearlo de memoria es la forma más fácil de descuadrar.
            with SessionLocal() as db:
                ayer = caja.balance_del_dia_anterior(db, self.dia())
            if ayer > 0:
                propuesta = ayer
                aviso = f"El día anterior con movimientos cerró con {clp(ayer)}."

        dialogo = MovimientoDialog(self, tipo, propuesta, aviso)
        if dialogo.exec() != QDialog.Accepted:
            return

        with SessionLocal() as db:
            db.add(MovimientoCaja(
                usuario_id=Sesion.usuario_id, tipo=tipo,
                monto=dialogo.monto.value(), motivo=dialogo.motivo.text().strip(),
                fecha=self._marca_de_tiempo(),
            ))
            db.commit()
        self.recargar()

    def _marca_de_tiempo(self) -> datetime:
        """Hoy se anota con la hora real; un día pasado, al mediodía: no se
        inventa una hora que nadie vio."""
        dia = self.dia()
        if dia == date.today():
            return datetime.now()
        return datetime(dia.year, dia.month, dia.day, 12, 0)

    def anular(self) -> None:
        fila = self.tabla.currentRow()
        if fila < 0 or not Sesion.activa():
            return
        movimiento_id = self.tabla.item(fila, 0).data(Qt.UserRole)
        motivo = self.tabla.item(fila, 2).text()
        if QMessageBox.question(
            self, "Anular movimiento",
            f"Se va a insertar el movimiento inverso de «{motivo}».\n"
            "La fila original no se borra: queda marcada como anulada.",
        ) != QMessageBox.Yes:
            return

        with SessionLocal() as db:
            caja.anular(db, movimiento_id, Sesion.usuario_id)
            db.commit()
        self.recargar()

    def guardar_pdf(self) -> None:
        dia = self.dia()
        with SessionLocal() as db:
            cifras = caja.resumen(db, dia)
            filas = caja.movimientos(db, dia)

        ruta = carpeta_de_documentos("Caja") / f"caja-{dia:%Y-%m-%d}.pdf"
        documento = QTextDocument()
        if LOGO.is_file():
            documento.addResource(QTextDocument.ImageResource, QUrl("logo"), QImage(str(LOGO)))
        documento.setHtml(html_de_caja(dia, cifras, filas))
        escritor = QPdfWriter(str(ruta))
        escritor.setPageSize(QPageSize(QPageSize.A4))
        documento.print_(escritor)
        QMessageBox.information(self, "Caja guardada", f"Se guardó en:\n{ruta}")
