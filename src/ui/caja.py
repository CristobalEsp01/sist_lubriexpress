"""Pestaña de Caja. En la mañana se anota la apertura, lo cobrado en efectivo
entra solo, se anota lo que se saca, y arriba se lee la cuadratura. Las cifras
viven en `src/caja.py`.
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
    BADGE_ACENTO, BADGE_ALERTA, BADGE_EXITO, BADGE_NEUTRAL, ROL_INSIGNIA, ItemNumerico,
    ajustar_columnas, barra, botonera, carpeta_de_documentos, clp, con_aviso_vacio,
    crear_tabla, layout_de_dialogo, layout_de_pantalla,
)
from .inventario import FormularioProducto
from .tema import ALERTA, ESPACIO_PANTALLA, EXITO, LOGO, TINTA_SUAVE

COLUMNAS = ["Hora", "Tipo", "Detalle", "Monto", "Registró"]
# La cuenta con sus signos: 40 + 20 − 10 = 50.
CUENTA = [("apertura", "Apertura"), ("+", ""), ("entradas", "Entradas en efectivo"),
          ("−", ""), ("salidas", "Salidas"), ("=", ""), ("balance", "Debe haber en caja")]
# Título, motivo propuesto y ejemplo de cada diálogo.
DIALOGOS = {
    "APERTURA": ("Apertura de caja", "Apertura de caja", ""),
    "INGRESO": ("Agregar dinero a la caja", "", "Ej: sencillo que trajo el dueño"),
    "EGRESO": ("Sacar dinero de la caja", "", "Ej: flete, bencina, retiro para depósito"),
}
# Pasó en las pruebas: anotar el vuelto como egreso lo descuenta dos veces.
SIN_VUELTO = "El vuelto de una venta no se anota: la venta ya entra por lo que costó."


class MovimientoDialog(QDialog):
    """La apertura, o dinero que se agrega o se saca. Nada se edita después:
    corregir es anular, que inserta la inversa."""

    def __init__(self, parent=None, tipo: str = "INGRESO", propuesta: int = 0, aviso: str = ""):
        super().__init__(parent)
        self.tipo = tipo
        titulo, motivo, ejemplo = DIALOGOS[tipo]
        self.setWindowTitle(titulo)
        self.setModal(True)

        self.monto = FormularioProducto._campo_pesos()
        self.monto.setValue(propuesta)
        self.motivo = QLineEdit(motivo)
        self.motivo.setMaxLength(200)
        self.motivo.setPlaceholderText(ejemplo)

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
        self.monto.selectAll()

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
    """La caja de un día: su cuadratura, lo que pasó por ella y el PDF."""

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
        self.cifras.setSpacing(18)
        # Sin esto las cifras se encabalgan unas sobre otras al angostar.
        self.cifras.setSizeConstraint(QLayout.SetMinimumSize)
        marco = QFrame()
        marco.setProperty("clase", "total")
        marco.setLayout(self.cifras)
        self._etiquetas = {}
        for clave, rotulo in CUENTA:
            if not rotulo:     # un signo de la cuenta
                signo = QLabel(clave)
                signo.setProperty("clase", "total-cifra-menor")
                self.cifras.addWidget(signo, 0, Qt.AlignTop)
                continue
            self._etiquetas[clave] = self._cifra(
                rotulo, "total-cifra" if clave == "balance" else "total-cifra-menor")
        self.cifras.addStretch()
        # Aparte y en chico: se cobró, pero está en el banco.
        self._etiquetas["otros_medios"] = self._cifra(
            "Tarjeta y transferencia\nno entra al cajón", "total-cifra-desglose")

        self.aviso_apertura = QLabel(
            "Falta registrar la apertura de hoy. Sin ella, «Debe haber en caja» no "
            "cuenta la plata con que partió el cajón."
        )
        self.aviso_apertura.setProperty("clase", "aviso")
        self.aviso_apertura.setWordWrap(True)

        self.tabla = con_aviso_vacio(
            crear_tabla(COLUMNAS, ancha=2, orden=0, numericas=(3,)),
            "Nada pasó por la caja este día.",
        )
        self.tabla.itemSelectionChanged.connect(self._al_seleccionar)

        self.boton_apertura = QPushButton("Registrar apertura")
        self.boton_apertura.setProperty("clase", "primario")
        self.boton_apertura.clicked.connect(lambda: self.registrar("APERTURA"))
        self.boton_dinero = QPushButton("Agregar dinero")
        self.boton_dinero.clicked.connect(lambda: self.registrar("INGRESO"))
        self.boton_gasto = QPushButton("Sacar dinero")
        self.boton_gasto.clicked.connect(lambda: self.registrar("EGRESO"))
        self.boton_anular = QPushButton("Anular")
        self.boton_anular.setEnabled(False)
        self.boton_anular.setToolTip("Inserta el movimiento inverso: nada se borra")
        self.boton_anular.clicked.connect(self.anular)
        self.boton_pdf = QPushButton("Guardar caja en PDF")
        self.boton_pdf.clicked.connect(self.guardar_pdf)

        layout = layout_de_pantalla(self)
        layout.setSpacing(ESPACIO_PANTALLA)
        # El estirón va en un espaciador: con él en un botón, ese botón se come
        # el ancho de la ventana.
        layout.addLayout(barra(QLabel("Día"), self.fecha, QWidget(), self.boton_apertura,
                               self.boton_dinero, self.boton_gasto, self.boton_anular,
                               self.boton_pdf, estira=2))
        layout.addWidget(self.aviso_apertura)
        layout.addWidget(marco)
        layout.addWidget(self.tabla, 1)
        self.recargar()

    def _cifra(self, rotulo: str, clase: str) -> QLabel:
        bloque = QVBoxLayout()
        bloque.setSpacing(0)
        cifra = QLabel("$0")
        cifra.setProperty("clase", clase)
        texto = QLabel(rotulo)
        texto.setProperty("clase", "total-rotulo")
        bloque.addWidget(cifra)
        bloque.addWidget(texto)
        contenedor = QWidget()
        contenedor.setLayout(bloque)
        self.cifras.addWidget(contenedor)
        return cifra

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
            abierta = caja.tiene_apertura(db, dia)

        for clave, cifra in self._etiquetas.items():
            cifra.setText(clp(cifras[clave]))

        # Un día pasado se mira y se anula, pero no se le anota nada nuevo.
        hoy = dia == date.today()
        self.boton_apertura.setEnabled(hoy and not abierta)
        self.boton_dinero.setEnabled(hoy)
        self.boton_gasto.setEnabled(hoy)
        self.aviso_apertura.setVisible(hoy and not abierta)

        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(filas))
        for numero, fila in enumerate(filas):
            self._llenar(numero, fila)
        ajustar_columnas(self.tabla)
        self._al_seleccionar()

    def _llenar(self, numero: int, fila: caja.Fila) -> None:
        hora = ItemNumerico(fila.hora.strftime("%H:%M"), fila.hora.timestamp())
        hora.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # Solo lo anotado a mano y vigente se anula acá.
        hora.setData(Qt.UserRole, None if fila.anulado else fila.id)
        self.tabla.setItem(numero, 0, hora)

        apagada = fila.anulado or not fila.en_cajon
        tipo = QTableWidgetItem(caja.NOMBRES[fila.tipo])
        tipo.setData(ROL_INSIGNIA,
                     BADGE_NEUTRAL if apagada
                     else BADGE_ALERTA if fila.tipo == "EGRESO"
                     else BADGE_ACENTO if fila.tipo == "APERTURA" else BADGE_EXITO)
        self.tabla.setItem(numero, 1, tipo)
        self.tabla.setItem(numero, 2, QTableWidgetItem(fila.motivo))

        monto = ItemNumerico(clp(fila.monto), fila.monto)
        if not apagada:
            monto.setForeground(QColor(ALERTA if fila.tipo == "EGRESO" else EXITO))
        self.tabla.setItem(numero, 3, monto)
        self.tabla.setItem(numero, 4, QTableWidgetItem(fila.usuario))

        # Apagado: lo anulado (nada se borra) y lo cobrado con tarjeta.
        if apagada:
            motivo = ("Anulado: no cuenta para las cifras del día" if fila.anulado
                      else "Pagado con tarjeta o transferencia: no entra al cajón")
            for columna in range(self.tabla.columnCount()):
                celda = self.tabla.item(numero, columna)
                celda.setForeground(QColor(TINTA_SUAVE))
                celda.setToolTip(motivo)

    def _anulable(self) -> int | None:
        fila = self.tabla.currentRow()
        if fila < 0 or not self.tabla.selectionModel().hasSelection():
            return None
        return self.tabla.item(fila, 0).data(Qt.UserRole)

    def _al_seleccionar(self) -> None:
        self.boton_anular.setEnabled(self._anulable() is not None)

    # -- acciones ------------------------------------------------------

    def registrar(self, tipo: str) -> None:
        if not Sesion.activa():
            QMessageBox.critical(self, "Error", "No hay sesión activa.")
            return
        if self.dia() != date.today():
            return  # los botones están apagados; queda el atajo y las pruebas

        propuesta, aviso = 0, SIN_VUELTO if tipo == "EGRESO" else ""
        if tipo == "APERTURA":
            # Si el conteo calza con el cierre anterior, la apertura es un Enter.
            with SessionLocal() as db:
                ayer = caja.balance_del_dia_anterior(db, self.dia())
            if ayer > 0:
                propuesta = ayer
                aviso = (f"El día anterior con movimientos debía cerrar con {clp(ayer)}. "
                         "Cuenta el cajón y corrige el monto si no es eso.")

        dialogo = MovimientoDialog(self, tipo, propuesta, aviso)
        if dialogo.exec() != QDialog.Accepted:
            return

        with SessionLocal() as db:
            db.add(MovimientoCaja(
                usuario_id=Sesion.usuario_id, tipo=tipo,
                monto=dialogo.monto.value(), motivo=dialogo.motivo.text().strip(),
                fecha=datetime.now(),
            ))
            db.commit()
        self.recargar()

    def anular(self) -> None:
        movimiento_id = self._anulable()
        if movimiento_id is None or not Sesion.activa():
            return
        motivo = self.tabla.item(self.tabla.currentRow(), 2).text()
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
