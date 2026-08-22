"""Piezas compartidas por los mantenedores: formato de moneda, insignias y tablas."""
from PySide6.QtCore import QModelIndex, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QStyle,
    QStyledItemDelegate, QStyleOptionViewItem, QTableWidget, QTableWidgetItem,
)

from .tema import (
    ACENTO_FONDO, ACENTO_HOVER, ALERTA, ALERTA_FONDO, ALTO_FILA,
    EXITO, EXITO_FONDO, INFO, INFO_FONDO, NEUTRAL_FONDO, NEUTRAL_TEXTO,
    fuente_tabular,
)

ROL_INSIGNIA = Qt.UserRole + 10

BADGE_ALERTA = (ALERTA_FONDO, ALERTA)
BADGE_EXITO = (EXITO_FONDO, EXITO)
BADGE_INFO = (INFO_FONDO, INFO)
BADGE_ACENTO = (ACENTO_FONDO, ACENTO_HOVER)
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
                painter.fillRect(option.rect, QColor("#FAFAFA"))
            else:
                painter.fillRect(option.rect, QColor("#FFFFFF"))

            fondo_hex, texto_hex = insignia
            texto = str(index.data(Qt.DisplayRole))

            fuente = option.font
            fuente.setPointSize(9)
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


def botonera(dialogo: QDialog) -> QDialogButtonBox:
    """Guardar y Cancelar, con el guardar destacado.

    Los rótulos los pone Qt según el idioma; ver el traductor en tema.aplicar().
    """
    botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    botones.button(QDialogButtonBox.Save).setProperty("clase", "primario")
    botones.accepted.connect(dialogo.accept)
    botones.rejected.connect(dialogo.reject)
    return botones
