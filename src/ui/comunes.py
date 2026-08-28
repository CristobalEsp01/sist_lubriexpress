"""Piezas compartidas por los mantenedores: formato de moneda, insignias, tablas
y combos que se buscan tecleando."""
from PySide6.QtCore import (
    QEvent, QModelIndex, QObject, QRectF, QSortFilterProxyModel, Qt, QTimer,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QCompleter, QDialog, QDialogButtonBox, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from shiboken6 import isValid

from ..texto import normalizar
from .tema import (
    ACENTO_FONDO, ACENTO_OSCURO, ALERTA, ALERTA_FONDO, ALTERNA, ALTO_FILA,
    ESPACIO_BARRA, ESPACIO_DIALOGO, ESPACIO_PANTALLA, EXITO, EXITO_FONDO, INSIGNIA_PT,
    INFO, INFO_FONDO, MARGEN_DIALOGO, MARGEN_PANTALLA, NEUTRAL_FONDO,
    NEUTRAL_TEXTO, SUPERFICIE, fuente_tabular,
)

ROL_INSIGNIA = Qt.UserRole + 10

BADGE_ALERTA = (ALERTA_FONDO, ALERTA)
BADGE_EXITO = (EXITO_FONDO, EXITO)
BADGE_INFO = (INFO_FONDO, INFO)
BADGE_ACENTO = (ACENTO_FONDO, ACENTO_OSCURO)
BADGE_NEUTRAL = (NEUTRAL_FONDO, NEUTRAL_TEXTO)


class InsigniaDelegate(QStyledItemDelegate):
    """Dibuja insignias (pills) redondeadas y legibles en celdas marcadas."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        insignia = index.data(ROL_INSIGNIA)
        if not insignia or not index.data(Qt.DisplayRole):
            super().paint(painter, option, index)
            return

        painter.save()
        try:
            painter.setRenderHint(QPainter.Antialiasing)

            # Respetar fondo de selección o alternancia
            if option.state & QStyle.State_Selected:
                painter.fillRect(option.rect, QColor(ACENTO_FONDO))
            elif index.row() % 2 == 1:
                painter.fillRect(option.rect, QColor(ALTERNA))
            else:
                painter.fillRect(option.rect, QColor(SUPERFICIE))

            fondo_hex, texto_hex = insignia
            texto = str(index.data(Qt.DisplayRole))

            fuente = option.font
            fuente.setPointSize(INSIGNIA_PT)
            fuente.setBold(True)
            painter.setFont(fuente)

            metricas = painter.fontMetrics()
            ancho_texto = metricas.horizontalAdvance(texto)
            alto_texto = metricas.height()

            ancho_badge = ancho_texto + 16
            alto_badge = max(22, alto_texto + 4)

            rect_celda = option.rect
            alineacion = index.data(Qt.TextAlignmentRole) or (Qt.AlignLeft | Qt.AlignVCenter)

            if alineacion & Qt.AlignRight:
                x = rect_celda.right() - ancho_badge - 8
            elif alineacion & Qt.AlignHCenter:
                x = rect_celda.left() + (rect_celda.width() - ancho_badge) / 2
            else:
                x = rect_celda.left() + 8

            y = rect_celda.top() + (rect_celda.height() - alto_badge) / 2
            rect_badge = QRectF(x, y, ancho_badge, alto_badge)

            # Pastilla redondeada
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(fondo_hex))
            painter.drawRoundedRect(rect_badge, alto_badge / 2, alto_badge / 2)

            # Texto de la pastilla
            painter.setPen(QColor(texto_hex))
            painter.drawText(rect_badge, Qt.AlignCenter, texto)
        finally:
            painter.restore()


def clp(valor) -> str:
    """20000.00 -> '$20.000'. En Chile no se usan decimales en caja."""
    return f"${int(valor):,}".replace(",", ".")


class ItemNumerico(QTableWidgetItem):
    """Ordena por el valor real: como texto, '$3.500' quedaría antes que '$20.000'."""

    def __init__(self, texto: str, valor):
        super().__init__(texto)
        self.valor = valor
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setFont(fuente_tabular())

    def __lt__(self, otro):
        return self.valor < getattr(otro, "valor", 0)


def crear_tabla(columnas: list[str], ancha: int, orden: int, descendente: bool = False,
                numericas: tuple[int, ...] = ()) -> QTableWidget:
    """Tabla de solo lectura, ordenable, con una columna que se estira e insignias.

    `ancha` es la columna que absorbe el espacio sobrante, `orden` la que
    ordena por defecto y `numericas` las que van alineadas a la derecha, para
    que el encabezado quede sobre sus propios dígitos.
    """
    tabla = QTableWidget(0, len(columnas))
    tabla.setHorizontalHeaderLabels(columnas)
    for columna in range(len(columnas)):
        lado = Qt.AlignRight if columna in numericas else Qt.AlignLeft
        tabla.horizontalHeaderItem(columna).setTextAlignment(lado | Qt.AlignVCenter)
    tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
    tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
    tabla.setSelectionMode(QAbstractItemView.SingleSelection)
    tabla.verticalHeader().setVisible(False)
    tabla.verticalHeader().setDefaultSectionSize(ALTO_FILA)
    tabla.setAlternatingRowColors(True)
    tabla.setShowGrid(False)
    tabla.setWordWrap(False)
    tabla.setSortingEnabled(True)
    tabla.setItemDelegate(InsigniaDelegate(tabla))
    tabla.horizontalHeader().setSectionResizeMode(ancha, QHeaderView.Stretch)
    # Sin fijarlo, Qt ordena al revés de lo que muestra la flecha del encabezado.
    sentido = Qt.DescendingOrder if descendente else Qt.AscendingOrder
    tabla.horizontalHeader().setSortIndicator(orden, sentido)
    return tabla


def reordenar(tabla: QTableWidget) -> None:
    """Reaplica el orden vigente tras repoblar la tabla y ajusta los anchos."""
    encabezado = tabla.horizontalHeader()
    tabla.setSortingEnabled(True)
    tabla.sortItems(encabezado.sortIndicatorSection(), encabezado.sortIndicatorOrder())
    tabla.resizeColumnsToContents()


class _FiltroNormalizado(QSortFilterProxyModel):
    """Deja pasar las filas que contienen todas las palabras tecleadas.

    El filtro de serie compara las cadenas tal cual: con él, "perez" no
    encuentra a "Pérez" ni "12345678" a "12.345.678-5". Las palabras se exigen
    por separado, igual que en `filtro_busqueda()`, para que normalizar no se
    coma los espacios de una consulta de dos palabras.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._agujas: list[str] = []

    def filtrar(self, texto: str) -> None:
        self._agujas = [normalizar(palabra) for palabra in texto.split()]
        self.invalidate()  # invalidateFilter() está deprecado en PySide6

    def filterAcceptsRow(self, fila: int, padre: QModelIndex) -> bool:
        if not self._agujas:
            return True
        objetivo = normalizar(self.sourceModel().index(fila, 0, padre).data())
        return all(aguja in objetivo for aguja in self._agujas)


class _AlEnfocar(QObject):
    """Al entrar al campo: selecciona lo que dice y suelta el filtro anterior.

    Sin esto hay que borrar a mano lo que el combo ya mostraba antes de poder
    escribir lo que se busca. Seleccionado, teclear lo reemplaza; si no se
    teclea nada, el texto queda igual que estaba.
    """

    def __init__(self, combo: QComboBox, filtro: _FiltroNormalizado):
        super().__init__(combo)
        self._filtro = filtro

    def eventFilter(self, objeto, evento) -> bool:
        if evento.type() == QEvent.FocusIn:
            self._filtro.filtrar("")
            # Qt reposiciona el cursor después de este evento; sin diferirlo,
            # la selección se pierde apenas se entrega el foco.
            QTimer.singleShot(0, objeto.selectAll)
        return False


def hacer_buscable(combo: QComboBox, *, libre: bool = False) -> QComboBox:
    """Convierte un combo en uno que se filtra tecleando cualquier parte.

    Recorrer una lista larga a ojo para dar con un RUT no es una interacción:
    es una búsqueda hecha a mano. Acá se teclea "perez" o "12345678" y el
    desplegable se reduce, igual que la búsqueda de los listados.

    Por defecto el combo solo deja elegir de la lista: teclear no inventa
    opciones y un texto que no calza con nada se descarta, porque si no el campo
    quedaría mintiendo sobre lo que está realmente elegido. Con `libre=True` se
    levantan las dos defensas, para los combos donde escribir algo nuevo es
    justamente la forma de crearlo (la ubicación de un producto).
    """
    combo.setEditable(True)

    filtro = _FiltroNormalizado(combo)
    filtro.setSourceModel(combo.model())

    completador = QCompleter(filtro, combo)
    completador.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
    completador.setCaseSensitivity(Qt.CaseInsensitive)
    combo.setCompleter(completador)
    combo.lineEdit().textEdited.connect(filtro.filtrar)
    combo.lineEdit().installEventFilter(_AlEnfocar(combo, filtro))

    if not libre:
        combo.setInsertPolicy(QComboBox.NoInsert)

        def confirmar_seleccion() -> None:
            if not combo.currentText().strip():
                # Vaciar el campo es una elección: deja el combo sin nada
                # seleccionado. Sin esto no habría forma de volver atrás una vez
                # elegida una opción.
                combo.setCurrentIndex(-1)
            elif combo.findText(combo.currentText()) < 0:
                # Lo tecleado no calza con nada: se descarta y vuelve a
                # mostrarse lo que de verdad está elegido.
                combo.setEditText(combo.itemText(combo.currentIndex()))

        combo.lineEdit().editingFinished.connect(confirmar_seleccion)
    return combo


class _AvisoVacio(QObject):
    """Mantiene un aviso centrado en el viewport, visible solo si no hay filas.

    Es un QObject hijo de la tabla a propósito: así Qt corta las conexiones al
    destruirla. Con una función suelta conectada a las señales del modelo, el
    aviso sobrevive a la tabla y termina llamando a un objeto ya borrado.
    """

    def __init__(self, tabla: QTableWidget, mensaje: str):
        super().__init__(tabla)
        self._tabla = tabla
        self.etiqueta = QLabel(mensaje, tabla.viewport())
        self.etiqueta.setProperty("clase", "aviso-vacio")
        self.etiqueta.setAlignment(Qt.AlignCenter)
        self.etiqueta.setWordWrap(True)

        tabla.viewport().installEventFilter(self)
        modelo = tabla.model()
        for senal in (modelo.rowsInserted, modelo.rowsRemoved,
                      modelo.modelReset, modelo.layoutChanged):
            senal.connect(self.acomodar)
        self.acomodar()

    def acomodar(self) -> None:
        # El modelo de Qt sobrevive un instante al widget y alcanza a emitir
        # rowsRemoved mientras la tabla ya se está destruyendo.
        if not isValid(self._tabla):
            return
        self.etiqueta.setGeometry(self._tabla.viewport().rect())
        self.etiqueta.setVisible(self._tabla.rowCount() == 0)

    def eventFilter(self, objeto, evento) -> bool:
        if evento.type() == QEvent.Resize:
            self.acomodar()
        return False


def layout_de_pantalla(widget: QWidget) -> QVBoxLayout:
    """Márgenes y espaciado de una pestaña. Estaban copiados en cada mantenedor
    y las pantallas nuevas se quedaron con el margen por defecto de Qt."""
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(*MARGEN_PANTALLA)
    layout.setSpacing(ESPACIO_PANTALLA)
    return layout


def layout_de_dialogo(dialogo: QDialog) -> QVBoxLayout:
    """Lo mismo para una ventana modal, que respira un poco más."""
    layout = QVBoxLayout(dialogo)
    layout.setContentsMargins(*MARGEN_DIALOGO)
    layout.setSpacing(ESPACIO_DIALOGO)
    return layout


def barra(*widgets, estira: int = 0) -> QHBoxLayout:
    """Fila de controles con el espaciado del sistema.

    `estira` es el índice del widget que absorbe el ancho sobrante, casi
    siempre la caja de búsqueda.
    """
    fila = QHBoxLayout()
    fila.setSpacing(ESPACIO_BARRA)
    for indice, widget in enumerate(widgets):
        fila.addWidget(widget, 1 if indice == estira else 0)
    return fila


def con_aviso_vacio(tabla: QTableWidget, mensaje: str) -> QTableWidget:
    """Una tabla sin filas tiene que decir por qué está vacía.

    Sin esto, buscar algo que no existe deja un rectángulo blanco mudo y no hay
    forma de distinguir "no hay nada registrado" de "la búsqueda no encontró
    nada". El aviso vive dentro del viewport, así que no ocupa lugar en el
    layout ni empuja nada al aparecer; el mensaje se cambia con
    `tabla.aviso.setText(...)` cuando la razón es otra.
    """
    tabla.aviso = _AvisoVacio(tabla, mensaje).etiqueta
    return tabla


def bloque_total(rotulo: str = "Total", menor: bool = False) -> tuple[QFrame, QLabel]:
    """El pie de una pantalla de cobro: rótulo a la izquierda, cifra a la derecha.

    Va sobre su propia superficie y separado por una línea porque es el
    resultado de la pantalla, no un campo más del formulario. Devuelve el marco,
    para meterlo en el layout, y la etiqueta de la cifra, que es la que cambia.
    """
    marco = QFrame()
    marco.setProperty("clase", "total")

    etiqueta = QLabel(rotulo)
    etiqueta.setProperty("clase", "total-rotulo")
    cifra = QLabel(clp(0))
    cifra.setProperty("clase", "total-cifra-menor" if menor else "total-cifra")
    cifra.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

    fila = QHBoxLayout(marco)
    fila.setContentsMargins(2, 10, 2, 0)
    fila.addWidget(etiqueta)
    fila.addStretch()
    fila.addWidget(cifra)
    return marco, cifra


def botonera(dialogo: QDialog) -> QDialogButtonBox:
    """Guardar y Cancelar, con el guardar destacado.

    Los rótulos los pone Qt según el idioma; ver el traductor en tema.aplicar().
    """
    botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    botones.button(QDialogButtonBox.Save).setProperty("clase", "primario")
    botones.accepted.connect(dialogo.accept)
    botones.rejected.connect(dialogo.reject)
    return botones
