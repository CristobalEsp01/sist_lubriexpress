"""Pestaña Reportes: un rango de fechas, cuatro tablas y Exportar a Excel.
Los números los calcula src/reportes.py; acá solo se muestran."""
from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit, QFileDialog, QLabel, QMessageBox, QPushButton, QTableWidgetItem, QTabWidget, QWidget,
)

from .. import reportes
from ..database import SessionLocal
from ..xlsx import escribir_xlsx
from .comunes import ItemNumerico, barra, clp, con_aviso_vacio, crear_tabla, layout_de_pantalla, reordenar

# (título, columnas, columnas en pesos, columnas numéricas, función(db, desde, hasta) o función(db))
DEFINICIONES = [
    ("Ingresos por período", reportes.COLUMNAS_INGRESOS, {2, 4, 5, 6, 7}, (1, 2, 3, 4, 5, 6, 7),
     reportes.ingresos_por_periodo),
    ("Ventas por producto", reportes.COLUMNAS_PRODUCTOS, {3}, (2, 3), reportes.ventas_por_producto),
    ("Por usuario", reportes.COLUMNAS_USUARIOS, {2, 4, 5}, (1, 2, 3, 4, 5), reportes.por_usuario),
    ("Reabastecimiento", reportes.COLUMNAS_REABASTECIMIENTO, set(), (3, 4, 5), reportes.reabastecimiento),
]


class ReportesWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        hoy = date.today()
        self.desde = QDateEdit(QDate(hoy.year, hoy.month, 1), calendarPopup=True)
        self.hasta = QDateEdit(QDate(hoy), calendarPopup=True)
        for campo in (self.desde, self.hasta):
            campo.setDisplayFormat("dd-MM-yyyy")
            campo.dateChanged.connect(self.recargar)
        boton_exportar = QPushButton("Exportar a Excel…")
        boton_exportar.clicked.connect(self.exportar)

        self.pestanas = QTabWidget()
        self.tablas = []
        for titulo, columnas, _, numericas, _ in DEFINICIONES:
            tabla = con_aviso_vacio(
                crear_tabla(columnas, ancha=0, orden=0, numericas=numericas),
                "Sin datos en el período.",
            )
            self.tablas.append(tabla)
            self.pestanas.addTab(tabla, titulo)
        aviso = QLabel("Las órdenes migradas del sistema antiguo no traen líneas: "
                       "\"Ventas por producto\" parte con el sistema nuevo. El neto es total menos IVA guardado.")
        aviso.setProperty("clase", "resumen")
        aviso.setWordWrap(True)

        layout = layout_de_pantalla(self)
        layout.addLayout(barra(QLabel("Desde"), self.desde, QLabel("Hasta"), self.hasta,
                               boton_exportar, estira=5))
        layout.addWidget(self.pestanas, 1)
        layout.addWidget(aviso)
        self.recargar()

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        self.recargar()

    def _fechas(self) -> tuple[date, date]:
        return self.desde.date().toPython(), self.hasta.date().toPython()

    def recargar(self) -> None:
        desde, hasta = self._fechas()
        with SessionLocal() as db:
            self.filas = [
                funcion(db) if funcion is reportes.reabastecimiento else funcion(db, desde, hasta)
                for *_, funcion in DEFINICIONES
            ]
        for tabla, filas, (_, _, pesos, _, _) in zip(self.tablas, self.filas, DEFINICIONES):
            tabla.setSortingEnabled(False)
            tabla.setRowCount(len(filas))
            for f, fila in enumerate(filas):
                for c, valor in enumerate(fila):
                    if isinstance(valor, (int, float)):
                        tabla.setItem(f, c, ItemNumerico(clp(valor) if c in pesos else str(valor), valor))
                    else:
                        tabla.setItem(f, c, QTableWidgetItem(valor))
            reordenar(tabla)

    def exportar(self) -> None:
        indice = self.pestanas.currentIndex()
        titulo, columnas, *_ = DEFINICIONES[indice]
        desde, hasta = self._fechas()
        sugerido = f"{titulo.lower().replace(' ', '_')}_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx"
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar reporte", sugerido, "Excel (*.xlsx)")
        if ruta:
            self.exportar_a(indice, ruta)
            QMessageBox.information(self, "Reporte exportado", f"Quedó en:\n{ruta}")

    def exportar_a(self, indice: int, ruta) -> None:
        escribir_xlsx(ruta, DEFINICIONES[indice][1], self.filas[indice])
