"""Interfaz del mantenedor de Inventario, sin pantalla.

Verifica el camino que de verdad puede romperse: el formulario escribiendo en
la base y el listado leyéndola de vuelta.
"""
import pytest
from sqlalchemy import select

from conftest import rut_de_prueba
from src.database import SessionLocal
from src.models import DetalleVenta, KardexMovimiento, Producto, Ubicacion, Usuario, Venta

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


def test_origen_de_identifica_la_procedencia_del_movimiento():
    from src.ui.inventario import origen_de

    assert origen_de(12, None, None) == "Orden #12"
    assert origen_de(None, "B-001", 5) == "Boleta B-001"
    assert origen_de(None, None, 5) == "Venta #5"      # venta sin boleta emitida
    assert origen_de(None, None, None) == "—"          # entrada o ajuste manual


def test_el_historial_lista_los_movimientos_del_mas_nuevo_al_mas_viejo(db):
    from src.ui.inventario import movimientos_de

    usuario = Usuario(nombre="Bastián QA", username=f"qa_{rut_de_prueba()}",
                      password_hash="x", rol="ADMINISTRADOR")
    producto = Producto(nombre=NOMBRE, precio_costo=3000, precio_venta=6500,
                        stock_actual=4, stock_minimo=10)
    db.add_all([usuario, producto])
    db.flush()

    db.add(KardexMovimiento(producto=producto, usuario=usuario,
                            tipo_movimiento="ENTRADA", cantidad_movida=12))
    db.flush()

    venta = Venta(usuario=usuario, numero_boleta=f"QA-{producto.id}", total_final=13000)
    db.add(venta)
    db.flush()
    db.add(DetalleVenta(venta=venta, producto=producto, cantidad=2,
                        precio_unitario_cobrado=6500))
    db.flush()

    movimientos = movimientos_de(db, producto.id)
    assert len(movimientos) == 2

    # Dentro de una misma transacción CURRENT_TIMESTAMP es idéntico para ambos,
    # así que el orden lo decide el desempate por id: la venta es posterior.
    _, tipo, cantidad, saldo, quien, origen = movimientos[0]
    assert (tipo, cantidad, saldo) == ("Salida por venta", -2, 14)
    assert quien == "Bastián QA"
    assert origen == f"Boleta QA-{producto.id}"

    _, tipo, cantidad, saldo, _, origen = movimientos[1]
    assert (tipo, cantidad, saldo, origen) == ("Entrada", 12, 16, "—")


def test_el_panel_pide_elegir_producto_cuando_no_hay_seleccion(app):
    from src.ui import InventarioWidget

    widget = InventarioWidget()
    widget.busqueda.setText("zzz producto que no existe zzz")

    assert widget.tabla.rowCount() == 0
    assert widget.tabla_kardex.rowCount() == 0
    assert "selecciona un producto" in widget.titulo_kardex.text()
