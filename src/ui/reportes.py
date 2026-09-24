"""Pestaña Reportes.

El orden de la pantalla es el orden en que se pregunta: primero de cuándo a
cuándo (con los rangos de siempre a un clic), después qué se quiere mirar, y
recién ahí las cifras. El resumen arriba responde la pregunta gruesa —cuánto
entró— sin leer la tabla; la tabla trae el detalle y el gráfico la forma.

Los números los calcula src/reportes.py; acá solo se muestran.
"""
from datetime import date, timedelta

from PySide6.QtCharts import (
    QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QHorizontalBarSeries, QValueAxis,
)
from PySide6.QtCore import QDate, QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QFrame, QHBoxLayout, QLabel, QLayout, QListWidget, QMessageBox,
    QHeaderView, QPushButton, QSplitter, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import reportes
from ..database import SessionLocal
from ..permisos import puede
from ..xlsx import escribir_xlsx
from .comunes import (
    ItemNumerico, barra, carpeta_de_documentos, clp, con_aviso_vacio, crear_tabla,
    layout_de_pantalla, reordenar,
)
from .tema import ACENTO, CANAL_PANEL, ESPACIO_PANTALLA, TINTA_SUAVE

CARPETA = "Reportes"
MAX_BARRAS = 12  # más barras que eso no se leen; el detalle está en la tabla


class Definicion:
    """Un reporte: cómo se llama, qué columnas tiene, cuál resume y cómo se
    grafica. `fechas` dice si el cálculo depende del período elegido, y
    `grafico` si tiene uno: una lista de órdenes no tiene forma que mirar."""

    def __init__(self, titulo, ayuda, columnas, pesos, numericas, orden, graficada,
                 funcion, fechas=True, horizontal=False, grafico=True):
        self.titulo, self.ayuda, self.columnas = titulo, ayuda, columnas
        self.pesos, self.numericas, self.orden = pesos, numericas, orden
        self.graficada, self.funcion = graficada, funcion
        self.fechas, self.horizontal, self.grafico = fechas, horizontal, grafico


REPORTES = [
    Definicion(
        "Ingresos por período", "Ventas de mostrador y órdenes de trabajo, día por día.",
        reportes.COLUMNAS_INGRESOS, {2, 4, 5, 6, 7, 8}, (1, 2, 3, 4, 5, 6, 7, 8), 0, 8,
        reportes.ingresos_por_periodo),
    Definicion(
        "Ventas por producto", "Qué se vendió y por cuánto, sumando mostrador y órdenes.",
        reportes.COLUMNAS_PRODUCTOS, {3}, (2, 3), 3, 3,
        reportes.ventas_por_producto, horizontal=True),
    Definicion(
        "Por usuario", "Cuánto movió cada persona en el período.",
        reportes.COLUMNAS_USUARIOS, {2, 4, 5}, (1, 2, 3, 4, 5), 5, 5,
        reportes.por_usuario, horizontal=True),
    Definicion(
        "Órdenes con descuento", "Toda orden con descuento general, flyer o gremio, y quién la ingresó.",
        reportes.COLUMNAS_DESCUENTOS, {6, 7}, (0, 6, 7), 0, 6,
        reportes.descuentos, grafico=False),
    Definicion(
        "Reabastecimiento", "Productos en su stock mínimo o por debajo. No depende del período.",
        reportes.COLUMNAS_REABASTECIMIENTO, set(), (3, 4, 5), 5, 5,
        reportes.reabastecimiento, fechas=False, horizontal=True),
]


def rangos(hoy: date) -> list[tuple[str, date, date]]:
    """Los períodos que se piden siempre, calculados sobre `hoy`."""
    primero = hoy.replace(day=1)
    mes_pasado_fin = primero - timedelta(days=1)
    return [
        ("Hoy", hoy, hoy),
        ("Últimos 7 días", hoy - timedelta(days=6), hoy),
        ("Últimos 30 días", hoy - timedelta(days=29), hoy),
        ("Este mes", primero, hoy),
        ("Mes pasado", mes_pasado_fin.replace(day=1), mes_pasado_fin),
        ("Este año", hoy.replace(month=1, day=1), hoy),
    ]


class ReportesWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Las cifras de plata son del administrador; el resto ve solo la lista
        # de compras (permisos.py).
        self.definiciones = [d for d in REPORTES
                             if puede("reportes") or d.funcion is reportes.reabastecimiento]
        self.hoy = date.today()
        self.filas: list[list] = []
        self.por_mes = False

        # --- Período -----------------------------------------------------
        self.rango = QComboBox()
        for nombre, _, _ in rangos(self.hoy):
            self.rango.addItem(nombre)
        self.rango.addItem("Personalizado")
        self.rango.setCurrentText("Este mes")
        self.rango.currentIndexChanged.connect(self._cambiar_rango)

        self.desde = self._campo_fecha(self.hoy.replace(day=1))
        self.hasta = self._campo_fecha(self.hoy)
        self.etiqueta_desde, self.etiqueta_hasta = QLabel("del"), QLabel("al")

        boton_exportar = QPushButton("Exportar a Excel")
        boton_exportar.setProperty("clase", "primario")
        boton_exportar.clicked.connect(self.exportar)
        boton_carpeta = QPushButton("Abrir carpeta")
        boton_carpeta.setToolTip(str(carpeta_de_documentos(CARPETA)))
        boton_carpeta.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(carpeta_de_documentos(CARPETA))))
        )

        # --- Qué reporte -------------------------------------------------
        # Una lista y no pestañas dentro de otra pestaña: se ven todos de una
        # vez y cuál está elegido, sin dos filas de solapas apiladas.
        self.lista = QListWidget()
        self.lista.addItems([d.titulo for d in self.definiciones])
        self.lista.setCurrentRow(0)
        self.lista.setFixedWidth(190)
        self.lista.currentRowChanged.connect(self._cambiar_reporte)

        # --- Resumen, tabla y gráfico ------------------------------------
        self.ayuda = QLabel()
        self.ayuda.setProperty("clase", "resumen")
        self.ayuda.setWordWrap(True)
        self.resumen = QHBoxLayout()
        self.resumen.setSpacing(28)
        # Las cifras no se encogen: sin esto se encabalgan unas sobre otras.
        self.resumen.setSizeConstraint(QLayout.SetMinimumSize)
        marco_resumen = QFrame()
        marco_resumen.setProperty("clase", "total")
        marco_resumen.setLayout(self.resumen)

        self.tabla = con_aviso_vacio(
            crear_tabla(self.definiciones[0].columnas, ancha=0, orden=0,
                        numericas=self.definiciones[0].numericas),
            "Sin datos en el período elegido.")
        self.grafico = QChartView()
        self.grafico.setRenderHint(QPainter.Antialiasing)
        self.grafico.setMinimumHeight(150)

        division = QSplitter(Qt.Vertical)
        division.setHandleWidth(1)
        division.addWidget(self.tabla)
        division.addWidget(self.grafico)
        division.setSizes([420, 220])
        division.setStretchFactor(0, 1)

        derecha = QWidget()
        columna = QVBoxLayout(derecha)
        columna.setContentsMargins(CANAL_PANEL, 0, 0, 0)
        columna.setSpacing(ESPACIO_PANTALLA)
        columna.addWidget(self.ayuda)
        columna.addWidget(marco_resumen)
        columna.addWidget(division, 1)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(0)
        cuerpo.addWidget(self.lista)
        cuerpo.addWidget(derecha, 1)

        layout = layout_de_pantalla(self)
        # El hueco que estira va entre las fechas y los botones: si estirara un
        # botón, "Abrir carpeta" ocuparía media pantalla.
        layout.addLayout(barra(
            QLabel("Período"), self.rango, self.etiqueta_desde, self.desde,
            self.etiqueta_hasta, self.hasta, QWidget(), boton_carpeta, boton_exportar,
            estira=6,
        ))
        layout.addLayout(cuerpo, 1)

        self._cambiar_rango()
        # El primero puede no depender del período (sin permiso, es el único).
        self._cambiar_reporte()
        self._conectar_fechas(True)

    @staticmethod
    def _campo_fecha(valor: date) -> QDateEdit:
        campo = QDateEdit(QDate(valor), calendarPopup=True)
        campo.setDisplayFormat("dd-MM-yyyy")
        # Sin esto el calendario abre en una semana que empieza en domingo.
        campo.calendarWidget().setFirstDayOfWeek(Qt.Monday)
        campo.setMaximumDate(QDate(date.today()))
        return campo

    # ------------------------------------------------------------------
    # Período
    # ------------------------------------------------------------------
    def _cambiar_rango(self) -> None:
        """Los rangos de siempre llenan las fechas; 'Personalizado' las libera."""
        elegido = self.rango.currentText()
        personalizado = elegido == "Personalizado"
        for campo in (self.desde, self.hasta, self.etiqueta_desde, self.etiqueta_hasta):
            campo.setEnabled(personalizado)
        if not personalizado:
            desde, hasta = next((d, h) for n, d, h in rangos(self.hoy) if n == elegido)
            for campo, valor in ((self.desde, desde), (self.hasta, hasta)):
                campo.blockSignals(True)
                campo.setDate(QDate(valor))
                campo.blockSignals(False)
        self.recargar()

    def _conectar_fechas(self, conectar: bool) -> None:
        for campo in (self.desde, self.hasta):
            (campo.dateChanged.connect if conectar else campo.dateChanged.disconnect)(self.recargar)

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        self.recargar()

    def _fechas(self) -> tuple[date, date]:
        desde, hasta = self.desde.date().toPython(), self.hasta.date().toPython()
        return (hasta, desde) if desde > hasta else (desde, hasta)

    def _cambiar_reporte(self) -> None:
        definicion = self.definicion()
        for campo in (self.rango, self.desde, self.hasta,
                      self.etiqueta_desde, self.etiqueta_hasta):
            campo.setEnabled(definicion.fechas and (
                campo is self.rango or self.rango.currentText() == "Personalizado"))
        self.tabla.setColumnCount(len(definicion.columnas))
        self.tabla.setHorizontalHeaderLabels(definicion.columnas)
        self._ajustar_cabecera(definicion)
        self.recargar()

    def _ajustar_cabecera(self, definicion: Definicion) -> None:
        """Cada columna a su contenido y el sobrante a la última.

        Estas tablas son de ocho columnas de cifras: con una columna en
        `Stretch`, el sobrante sale de ella y la fecha terminaba mostrando
        "19-0…". Acá ninguna se queda sin su ancho; si no caben, la tabla se
        desplaza, que es lo que hace cualquier planilla.
        """
        cabecera = self.tabla.horizontalHeader()
        for columna in range(self.tabla.columnCount()):
            cabecera.setSectionResizeMode(columna, QHeaderView.Interactive)
            alineacion = (Qt.AlignRight if columna in definicion.numericas else Qt.AlignLeft)
            self.tabla.horizontalHeaderItem(columna).setTextAlignment(
                alineacion | Qt.AlignVCenter)
        cabecera.setStretchLastSection(True)

    def definicion(self) -> Definicion:
        return self.definiciones[max(self.lista.currentRow(), 0)]

    # ------------------------------------------------------------------
    # Datos
    # ------------------------------------------------------------------
    def recargar(self) -> None:
        definicion = self.definicion()
        desde, hasta = self._fechas()
        with SessionLocal() as db:
            if not definicion.fechas:
                self.filas, self.por_mes = definicion.funcion(db), False
            elif definicion.funcion is reportes.ingresos_por_periodo:
                self.filas, self.por_mes = definicion.funcion(db, desde, hasta)
            else:
                self.filas, self.por_mes = definicion.funcion(db, desde, hasta), False

        self.ayuda.setText(definicion.ayuda)
        self._llenar_tabla(definicion)
        self._llenar_resumen(definicion)
        self.grafico.setVisible(definicion.grafico)
        if definicion.grafico:
            self._dibujar_grafico(definicion)

    def _texto(self, definicion: Definicion, columna: int, valor) -> str:
        if isinstance(valor, date):
            return reportes.rotulo_de_fecha(valor, self.por_mes)
        if isinstance(valor, (int, float)) and columna in definicion.pesos:
            return clp(valor)
        return str(valor)

    def _llenar_tabla(self, definicion: Definicion) -> None:
        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(self.filas))
        for f, fila in enumerate(self.filas):
            for c, valor in enumerate(fila):
                texto = self._texto(definicion, c, valor)
                if isinstance(valor, date):
                    # Ordenable por el día real: como texto, "01-10" queda antes
                    # que "02-09" y el período sale desordenado.
                    celda = ItemNumerico(texto, valor.toordinal())
                    celda.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                elif isinstance(valor, (int, float)):
                    celda = ItemNumerico(texto, valor)
                else:
                    celda = QTableWidgetItem(texto)
                self.tabla.setItem(f, c, celda)
        descendente = definicion.orden != 0
        self.tabla.sortItems(definicion.orden,
                             Qt.DescendingOrder if descendente else Qt.AscendingOrder)
        reordenar(self.tabla)

    def _llenar_resumen(self, definicion: Definicion) -> None:
        """Las tres cifras que responden el reporte sin leer la tabla."""
        while self.resumen.count():
            # El estirón del final no es un widget: takeAt devuelve un espaciador.
            anterior = self.resumen.takeAt(0).widget()
            if anterior is not None:
                # setParent(None) antes de deleteLater: borrar es diferido, y
                # hasta que ocurra el widget sigue pintándose encima del nuevo.
                anterior.setParent(None)
                anterior.deleteLater()

        graficada = definicion.graficada
        total = sum(fila[graficada] for fila in self.filas)
        cifras = [(f"{len(self.filas)}", "filas")]
        if definicion.funcion is reportes.ingresos_por_periodo:
            cifras = [(clp(total), "total del período"),
                      (clp(sum(f[6] for f in self.filas)), "IVA"),
                      (f"{sum(f[1] + f[3] for f in self.filas)}", "documentos")]
        elif definicion.funcion is reportes.descuentos:
            cifras = [(clp(total), "descontado"),
                      (f"{len(self.filas)}", "órdenes con descuento")]
        elif definicion.funcion is reportes.reabastecimiento:
            cifras = [(f"{len(self.filas)}", "productos bajo el mínimo"),
                      (f"{total}", "unidades que faltan")]
        else:
            cifras = [(clp(total), "total del período"),
                      (f"{len(self.filas)}", "con movimiento")]

        for valor, rotulo in cifras:
            bloque = QVBoxLayout()
            bloque.setSpacing(0)
            cifra = QLabel(valor)
            cifra.setProperty("clase", "total-cifra-menor")
            etiqueta = QLabel(rotulo)
            etiqueta.setProperty("clase", "total-rotulo")
            bloque.addWidget(cifra)
            bloque.addWidget(etiqueta)
            contenedor = QWidget()
            contenedor.setLayout(bloque)
            self.resumen.addWidget(contenedor)
        self.resumen.addStretch()

    def _dibujar_grafico(self, definicion: Definicion) -> None:
        """Barras horizontales cuando la categoría es un nombre —caben enteros—
        y verticales cuando es una fecha, que es como se lee una serie."""
        filas = self.filas[:MAX_BARRAS]
        if definicion.horizontal:
            filas = sorted(filas, key=lambda f: f[definicion.graficada])

        barras = QBarSet(definicion.columnas[definicion.graficada])
        barras.setColor(QColor(ACENTO))
        for fila in filas:
            barras.append(float(fila[definicion.graficada]))
        serie = QHorizontalBarSeries() if definicion.horizontal else QBarSeries()
        serie.append(barras)

        chart = QChart()
        chart.addSeries(serie)
        chart.legend().hide()
        chart.setBackgroundVisible(False)
        chart.setMargins(chart.margins().__class__(0, 0, 0, 0))
        if len(self.filas) > MAX_BARRAS:
            chart.setTitle(f"Los {MAX_BARRAS} mayores de {len(self.filas)}")

        # En el eje la fecha va sin año: con doce categorías, "19-08-2026" se
        # corta en "19-…" y no dice nada.
        def etiqueta(valor):
            if isinstance(valor, date):
                return valor.strftime("%m-%Y" if self.por_mes else "%d-%m")
            return str(valor)[:28]

        categorias = QBarCategoryAxis()
        categorias.append([etiqueta(fila[0]) for fila in filas] or ["—"])
        categorias.setLabelsColor(QColor(TINTA_SUAVE))
        valores = QValueAxis()
        valores.setLabelFormat("$%'.0f" if definicion.graficada in definicion.pesos else "%.0f")
        valores.setLabelsColor(QColor(TINTA_SUAVE))
        for eje, lado in ((categorias, Qt.AlignLeft if definicion.horizontal else Qt.AlignBottom),
                          (valores, Qt.AlignBottom if definicion.horizontal else Qt.AlignLeft)):
            eje.setLabelsFont(QFont("", 8))
            chart.addAxis(eje, lado)
            serie.attachAxis(eje)
        self.grafico.setChart(chart)

    # ------------------------------------------------------------------
    # Exportar
    # ------------------------------------------------------------------
    def exportar(self) -> None:
        ruta = self.exportar_a_carpeta()
        QMessageBox.information(self, "Reporte exportado", f"Quedó en:\n{ruta}")

    def exportar_a_carpeta(self, carpeta=None):
        """Guarda lo que está a la vista como .xlsx y devuelve la ruta. Las
        fechas se escriben formateadas, no como objetos."""
        definicion = self.definicion()
        desde, hasta = self._fechas()
        nombre = f"{definicion.titulo.lower().replace(' ', '_')}_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx"
        ruta = (carpeta or carpeta_de_documentos(CARPETA)) / nombre
        escribir_xlsx(ruta, definicion.columnas, [
            [self._texto(definicion, c, v) if isinstance(v, date) else v for c, v in enumerate(fila)]
            for fila in self.filas
        ])
        return ruta
