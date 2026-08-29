"""Piezas compartidas de la interfaz, sin pantalla ni base de datos."""
import pytest
from PySide6.QtWidgets import QComboBox

from src.ui.comunes import hacer_buscable

OPCIONES = [
    ("Venta sin cliente registrado", None),
    ("12.345.678-5 — Juan Pérez", 1),
    ("76.543.210-K — Transportes Sur SpA", 2),
    ("9.876.543-3 — María González", 3),
    ("12.345.999-9 — Pedro Núñez", 4),
]


def combo_de_prueba() -> QComboBox:
    combo = QComboBox()
    for etiqueta, dato in OPCIONES:
        combo.addItem(etiqueta, dato)
    return hacer_buscable(combo)


def sugerencias(combo: QComboBox, tecleado: str) -> list[str]:
    """Lo que vería el usuario en el desplegable al teclear `tecleado`."""
    combo.lineEdit().setText(tecleado)
    combo.lineEdit().textEdited.emit(tecleado)  # setText no lo emite solo
    modelo = combo.completer().model()
    return [modelo.index(f, 0).data() for f in range(modelo.rowCount())]


@pytest.mark.parametrize("tecleado, esperado", [
    ("12345678",     ["12.345.678-5 — Juan Pérez"]),          # RUT sin puntos
    ("perez",        ["12.345.678-5 — Juan Pérez"]),          # sin tilde
    ("nunez",        ["12.345.999-9 — Pedro Núñez"]),         # la ñ tampoco se teclea
    ("transportes",  ["76.543.210-K — Transportes Sur SpA"]),  # por el medio, no el prefijo
    ("juan perez",   ["12.345.678-5 — Juan Pérez"]),          # dos palabras con el RUT en medio
    ("perez juan",   ["12.345.678-5 — Juan Pérez"]),          # en cualquier orden
    ("12.345",       ["12.345.678-5 — Juan Pérez",
                      "12.345.999-9 — Pedro Núñez"]),         # ambiguo: ofrece los dos
    ("juan gonzalez", []),
])
def test_el_desplegable_se_filtra_tecleando(app, tecleado, esperado):
    assert sugerencias(combo_de_prueba(), tecleado) == esperado


def test_lo_tecleado_que_no_calza_no_cambia_lo_elegido(app):
    """La trampa del combo editable: si el campo se queda con basura, la venta
    se cobraría al cliente anterior sin que la pantalla lo diga."""
    combo = combo_de_prueba()
    combo.setCurrentIndex(1)

    combo.lineEdit().setText("Cliente inventado")
    combo.lineEdit().editingFinished.emit()

    assert combo.currentText() == "12.345.678-5 — Juan Pérez"
    assert combo.currentData() == 1
    assert combo.count() == len(OPCIONES)  # tampoco lo agregó a la lista

    # Vaciarlo a propósito sí cuenta: es la forma de volver a "ninguno", y si
    # rebotara al anterior la venta se cobraría a un cliente ya descartado.
    combo.lineEdit().clear()
    combo.lineEdit().editingFinished.emit()
    assert combo.currentText() == ""
    assert combo.currentData() is None


def test_el_combo_libre_conserva_lo_tecleado(app):
    """La ubicación de un producto se crea escribiéndola: ahí el texto nuevo es
    el dato, no un error de tipeo que haya que descartar."""
    combo = hacer_buscable(QComboBox(), libre=True)
    combo.addItems(["Pasillo 1 - Repisa A", "Pasillo 2 - Repisa B"])

    combo.setCurrentText("Bodega del fondo")
    combo.lineEdit().editingFinished.emit()

    assert combo.currentText() == "Bodega del fondo"
