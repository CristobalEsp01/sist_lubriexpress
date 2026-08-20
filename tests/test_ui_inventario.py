"""Interfaz del mantenedor de Inventario, sin pantalla.

Verifica el camino que de verdad puede romperse: el formulario escribiendo en
la base y el listado leyéndola de vuelta.
"""
import pytest
from sqlalchemy import select

from src.database import SessionLocal
from src.models import Producto, Ubicacion

NOMBRE = "QA Aceite de prueba"


@pytest.fixture
def limpiar():
    yield
    with SessionLocal() as db:
        for p in db.scalars(select(Producto).where(Producto.nombre == NOMBRE)):
            db.delete(p)
        for u in db.scalars(select(Ubicacion).where(Ubicacion.descripcion == "QA Repisa")):
            db.delete(u)
        db.commit()


def test_el_formulario_crea_el_producto_y_la_ubicacion(app, limpiar):
    from src.ui import FormularioProducto

    form = FormularioProducto()
    form.nombre.setText(NOMBRE)
    form.marca.setText("Mobil")
    form.categoria.setText("Aceite Motor")
    form.ubicacion.setCurrentText("QA Repisa")  # no existe: debe crearse
    form.precio_costo.setValue(20000)
    form.precio_venta.setValue(35000)
    form.stock_actual.setValue(12)
    form.stock_minimo.setValue(5)
    form.accept()

    with SessionLocal() as db:
        p = db.scalar(select(Producto).where(Producto.nombre == NOMBRE))
        assert p is not None
        assert p.stock_actual == 12
        assert p.ubicacion.descripcion == "QA Repisa"
        assert not p.stock_critico


def test_editar_no_puede_mover_el_stock(app, limpiar):
    from src.ui import FormularioProducto

    alta = FormularioProducto()
    alta.nombre.setText(NOMBRE)
    alta.precio_costo.setValue(1000)
    alta.precio_venta.setValue(2000)
    alta.stock_actual.setValue(7)
    alta.accept()

    edicion = FormularioProducto(producto_id=alta.producto_id)
    assert not edicion.stock_actual.isEnabled()
    edicion.stock_actual.setValue(999)
    edicion.precio_venta.setValue(2500)
    edicion.accept()

    with SessionLocal() as db:
        p = db.get(Producto, alta.producto_id)
        assert p.stock_actual == 7  # el stock solo se mueve por el kardex
        assert int(p.precio_venta) == 2500


def test_el_listado_muestra_el_producto_y_marca_lo_critico(app, limpiar):
    from src.ui import FormularioProducto, InventarioWidget

    alta = FormularioProducto()
    alta.nombre.setText(NOMBRE)
    alta.precio_costo.setValue(1000)
    alta.precio_venta.setValue(2000)
    alta.stock_actual.setValue(2)
    alta.stock_minimo.setValue(10)
    alta.accept()

    widget = InventarioWidget()
    widget.busqueda.setText(NOMBRE)
    nombres = [widget.tabla.item(f, 0).text() for f in range(widget.tabla.rowCount())]
    assert nombres == [NOMBRE]
    assert "1 bajo stock mínimo" in widget.resumen.text()
