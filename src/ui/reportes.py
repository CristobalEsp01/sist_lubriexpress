"""Pestaña Reportes: un rango de fechas, cuatro reportes con su gráfico y su
tabla, y exportación a Excel en una carpeta fija. Los números los calcula
src/reportes.py; acá solo se muestran."""
from datetime import date

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QValueAxis
from PySide6.QtCore import QDate, QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices, QPainter
from PySide6.QtWidgets import (
    QDateEdit, QLabel, QMessageBox, QPushButton, QSplitter, QTableWidgetItem, QTabWidget, QWidget,
)

from .. import reportes
from ..database import SessionLocal
from ..xlsx import escribir_xlsx
from .comunes import (
    ItemNumerico, barra, carpeta_de_documentos, clp, con_aviso_vacio, crear_tabla,
    layout_de_pantalla, reordenar,
)
from .tema import ACENTO, TINTA_SUAVE

# (título, columnas, columnas en pesos, numéricas, columna graficada, función)
DEFINICIONES = [
    ("Ingresos por período", reportes.COLUMNAS_INGRESOS, {2, 4, 5, 6, 7}, (1, 2, 3, 4, 5, 6, 7), 7,
     reportes.ingresos_por_periodo),
    ("Ventas por producto", reportes.COLUMNAS_PRODUCTOS, {3}, (2, 3), 3, reportes.ventas_por_producto),
    ("Por usuario", reportes.COLUMNAS_USUARIOS, {2, 4, 5}, (1, 2, 3, 4, 5), 5, reportes.por_usuario),
    ("Reabastecimiento", reportes.COLUMNAS_REABASTECIMIENTO, set(), (3, 4, 5), 5, reportes.reabastecimiento),
]
MAX_BARRAS = 15  # más que eso no se lee; la tabla de abajo tiene el resto
CARPETA = "Reportes"


class ReportesWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        hoy = date.today()
        self.desde = QDateEdit(QDate(hoy.year, hoy.month, 1), calendarPopup=True)
        self.hasta = QDateEdit(QDate(hoy), calendarPopup=True)
        for campo in (self.desde, self.hasta):
            campo.setDisplayFormat("dd-MM-yyyy")
            campo.dateChanged.connect(self.recargar)
        boton_exportar = QPushButton("Exportar a Excel")
        boton_exportar.setProperty("clase", "primario")
        boton_exportar.clicked.connect(self.exportar)
        boton_carpeta = QPushButton("Abrir carpeta de reportes")
        boton_carpeta.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(carpeta_de_documentos(CARPETA))))
        )

        self.pestanas = QTabWidget()
        self.tablas, self.graficos = [], []
        for titulo, columnas, _, numericas, _, _ in DEFINICIONES:
            tabla = con_aviso_vacio(
                crear_tabla(columnas, ancha=0, orden=0, numericas=numericas), "Sin datos en el período."
            )
            grafico = QChartView()
            grafico.setRenderHint(QPainter.Antialiasing)
            grafico.setMinimumHeight(180)
            panel = QSplitter(Qt.Vertical)
            panel.setHandleWidth(1)
            panel.addWidget(grafico)
            panel.addWidget(tabla)
            panel.setSizes([240, 300])
            self.tablas.append(tabla)
            self.graficos.append(grafico)
            self.pestanas.addTab(panel, titulo)
        aviso = QLabel("Las órdenes migradas del sistema antiguo no traen líneas: "
                       "\"Ventas por producto\" parte con el sistema nuevo. El neto es total menos IVA guardado.")
        aviso.setProperty("clase", "resumen")
        aviso.setWordWrap(True)

        layout = layout_de_pantalla(self)
        layout.addLayout(barra(QLabel("Desde"), self.desde, QLabel("Hasta"), self.hasta,
                               boton_carpeta, boton_exportar, estira=6))
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
        for tabla, grafico, filas, (titulo, columnas, pesos, _, graficada, _) in zip(
            self.tablas, self.graficos, self.filas, DEFINICIONES
        ):
            tabla.setSortingEnabled(False)
            tabla.setRowCount(len(filas))
            for f, fila in enumerate(filas):
                for c, valor in enumerate(fila):
                    if isinstance(valor, (int, float)):
                        tabla.setItem(f, c, ItemNumerico(clp(valor) if c in pesos else str(valor), valor))
                    else:
                        tabla.setItem(f, c, QTableWidgetItem(valor))
            reordenar(tabla)
            grafico.setChart(self._grafico(titulo, columnas[graficada], filas[:MAX_BARRAS], graficada,
                                           graficada in pesos))

    @staticmethod
    def _grafico(titulo: str, rotulo: str, filas: list[tuple], columna: int, en_pesos: bool) -> QChart:
        """Barras: una por fila, con la columna que resume el reporte."""
        barras = QBarSet(rotulo)
        barras.setColor(QColor(ACENTO))
        for fila in filas:
            barras.append(float(fila[columna]))
        serie = QBarSeries()
        serie.append(barras)
        chart = QChart()
        chart.addSeries(serie)
        chart.setTitle(f"{titulo} — {rotulo}" + (" (primeras %d)" % MAX_BARRAS if len(filas) == MAX_BARRAS else ""))
        chart.legend().hide()
        eje_x = QBarCategoryAxis()
        eje_x.append([str(fila[0])[:18] for fila in filas] or ["—"])
        eje_x.setLabelsColor(QColor(TINTA_SUAVE))
        eje_y = QValueAxis()
        eje_y.setLabelFormat("$%'.0f" if en_pesos else "%.0f")
        eje_y.setLabelsColor(QColor(TINTA_SUAVE))
        chart.addAxis(eje_x, Qt.AlignBottom)
        chart.addAxis(eje_y, Qt.AlignLeft)
        serie.attachAxis(eje_x)
        serie.attachAxis(eje_y)
        chart.setBackgroundVisible(False)
        return chart

    def exportar(self) -> None:
        ruta = self.exportar_a_carpeta(self.pestanas.currentIndex())
        QMessageBox.information(self, "Reporte exportado", f"Quedó en:\n{ruta}")

    def exportar_a_carpeta(self, indice: int, carpeta=None):
        """Guarda el reporte elegido como .xlsx en Documentos/Lubri-Express/Reportes
        (o en `carpeta`) y devuelve la ruta."""
        titulo, columnas, *_ = DEFINICIONES[indice]
        desde, hasta = self._fechas()
        nombre = f"{titulo.lower().replace(' ', '_')}_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx"
        ruta = (carpeta or carpeta_de_documentos(CARPETA)) / nombre
        escribir_xlsx(ruta, columnas, self.filas[indice])
        return ruta
