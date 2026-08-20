"""Piezas compartidas por los mantenedores: formato de moneda y tablas."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem,
)


def clp(valor) -> str:
    """20000.00 -> '$20.000'. En Chile no se usan decimales en caja."""
    return f"${int(valor):,}".replace(",", ".")


class ItemNumerico(QTableWidgetItem):
    """Ordena por el valor real: como texto, '$3.500' quedaría antes que '$20.000'."""

    def __init__(self, texto: str, valor):
        super().__init__(texto)
        self.valor = valor
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, otro):
        return self.valor < getattr(otro, "valor", 0)


def crear_tabla(columnas: list[str], ancha: int, orden: int) -> QTableWidget:
    """Tabla de solo lectura, ordenable, con una columna que se estira.

    `ancha` es la columna que absorbe el espacio sobrante y `orden` la que
    ordena por defecto.
    """
    tabla = QTableWidget(0, len(columnas))
    tabla.setHorizontalHeaderLabels(columnas)
    tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
    tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
    tabla.setSelectionMode(QAbstractItemView.SingleSelection)
    tabla.verticalHeader().setVisible(False)
    tabla.setWordWrap(False)
    tabla.setSortingEnabled(True)
    tabla.horizontalHeader().setSectionResizeMode(ancha, QHeaderView.Stretch)
    # Sin fijarlo, Qt ordena al revés de lo que muestra la flecha del encabezado.
    tabla.horizontalHeader().setSortIndicator(orden, Qt.AscendingOrder)
    return tabla


def reordenar(tabla: QTableWidget) -> None:
    """Reaplica el orden vigente tras repoblar la tabla y ajusta los anchos."""
    encabezado = tabla.horizontalHeader()
    tabla.setSortingEnabled(True)
    tabla.sortItems(encabezado.sortIndicatorSection(), encabezado.sortIndicatorOrder())
    tabla.resizeColumnsToContents()
