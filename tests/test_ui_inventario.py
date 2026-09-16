"""Interfaz del mantenedor de Inventario, sin pantalla.

Verifica el camino que de verdad puede romperse: el formulario escribiendo en
la base y el listado leyéndola de vuelta.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from conftest import rut_de_prueba
from src.database import SessionLocal
from src.models import DetalleVenta, KardexMovimiento, Producto, Ubicacion, Usuario, Venta

NOMBRE = "QA Aceite de prueba"
NOMBRE_INGRESO = "QA Filtro ingreso"


@pytest.fixture
def limpiar():
    yield
    with SessionLocal() as db:
        for p in db.scalars(select(Producto).where(Producto.nombre == NOMBRE)):
            db.delete(p)
        for u in db.scalars(select(Ubicacion).where(Ubicacion.descripcion == "QA Repisa")):
            db.delete(u)
        db.commit()


@pytest.fixture
def bodeguero_qa():
    """Sesión iniciada con un usuario comiteado, y limpieza del producto y los
    movimientos que deja la prueba de ingreso."""
    from src.auth import Sesion

    with SessionLocal() as db:
        usuario = Usuario(
            nombre="Bodeguero QA", username=f"qa_bodega_{rut_de_prueba()}",
            password_hash="hash-de-prueba", rol="SUPERVISOR",
        )
        db.add(usuario)
        db.commit()
        usuario_id = usuario.id

    Sesion.iniciar(SimpleNamespace(id=usuario_id, nombre="Bodeguero QA", rol="SUPERVISOR"))
    yield usuario_id
    Sesion.cerrar()
    with SessionLocal() as db:
        db.query(KardexMovimiento).filter(KardexMovimiento.usuario_id == usuario_id).delete()
        for p in db.scalars(select(Producto).where(Producto.nombre == NOMBRE_INGRESO)):
            db.delete(p)
        usuario = db.get(Usuario, usuario_id)
        if usuario:
            db.delete(usuario)
        db.commit()


def test_el_formulario_crea_el_producto_y_no_deja_mover_el_stock_al_editar(app, limpiar):
    from src.ui import FormularioProducto

    alta = FormularioProducto()
    alta.nombre.setText(NOMBRE)
    alta.marca.setText("Mobil")
    alta.categoria.setText("Aceite Motor")
    alta.ubicacion.setCurrentText("QA Repisa")  # no existe: debe crearse
    alta.precio_costo.setValue(20000)
    alta.precio_venta.setValue(35000)
    assert alta.precio_con_iva.text() == "$41.650"  # el neto se teclea, el bruto se ve
    alta.stock_actual.setValue(12)
    alta.stock_minimo.setValue(5)
    alta.accept()

    with SessionLocal() as db:
        p = db.scalar(select(Producto).where(Producto.nombre == NOMBRE))
        assert p.stock_actual == 12
        assert p.ubicacion.descripcion == "QA Repisa"
        assert not p.stock_critico

    edicion = FormularioProducto(producto_id=alta.producto_id)
    assert not edicion.stock_actual.isEnabled()
    edicion.stock_actual.setValue(999)
    edicion.precio_venta.setValue(40000)
    edicion.accept()

    with SessionLocal() as db:
        p = db.get(Producto, alta.producto_id)
        assert p.stock_actual == 12  # el stock solo se mueve por el kardex
        assert int(p.precio_venta) == 40000


def test_el_listado_marca_lo_critico_sin_esconder_los_inactivos(app, limpiar, bodeguero_qa):
    """Reportado: un producto crítico desaparecía al marcar "Solo stock
    crítico" porque el filtro exigía además activo=TRUE, mientras el resumen
    sin el tick sí lo contaba entre los críticos.

    Con sesión de supervisor: Editar exige rol además de fila."""
    from src.ui import InventarioWidget

    with SessionLocal() as db:
        db.add(Producto(nombre=NOMBRE, precio_costo=1000, precio_venta=2000,
                        stock_actual=3, stock_minimo=6, activo=False))
        db.commit()

    widget = InventarioWidget()
    widget.busqueda.setText("zzz producto que no existe zzz")
    assert widget.tabla.rowCount() == 0
    assert widget.tabla_kardex.rowCount() == 0
    # Una tabla vacía dice por qué lo está, en vez de quedar en blanco.
    # isVisible() sería False igual: el widget nunca se muestra en las pruebas.
    assert not widget.tabla.aviso.isHidden()
    assert "coincide con la búsqueda" in widget.tabla.aviso.text()
    assert "Elige un producto" in widget.tabla_kardex.aviso.text()
    # Los botones que necesitan una fila se apagan juntos.
    assert not widget.boton_vender.isEnabled()
    assert not widget.boton_editar.isEnabled()

    widget.busqueda.setText(NOMBRE)
    assert [widget.tabla.item(f, 0).text() for f in range(widget.tabla.rowCount())] == [NOMBRE]
    assert "1 bajo stock mínimo" in widget.resumen.text()

    # Elegir una fila es lo primero que hace cualquiera al abrir la pantalla, y
    # hasta ahora ninguna prueba lo hacía: un `connect` mal puesto en recargar()
    # reventaba en este punto y la batería seguía en verde.
    widget.tabla.selectRow(0)
    assert widget.boton_editar.isEnabled()
    assert widget.boton_vender.isEnabled()
    assert NOMBRE in widget.titulo_kardex.text()

    widget.solo_criticos.setChecked(True)
    assert [widget.tabla.item(f, 0).text() for f in range(widget.tabla.rowCount())] == [NOMBRE]


def test_el_historial_de_kardex_ordena_y_dice_de_dónde_viene(db):
    from src.ui.inventario import movimientos_de, origen_de

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

    # Los dos orígenes que este escenario no produce.
    assert origen_de(12, None, None) == "Orden #12"
    assert origen_de(None, None, 5) == "Venta #5"  # venta sin boleta emitida


def test_el_ingreso_de_mercaderia_suma_el_stock_una_sola_vez(app, bodeguero_qa, monkeypatch):
    """Regresión: la primera versión hacía producto.stock_actual += cantidad
    además de insertar el kardex, y el trigger volvía a sumar (doble conteo)."""
    from PySide6.QtWidgets import QMessageBox

    from src.ui.inventario import IngresoMercaderiaDialog

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)

    with SessionLocal() as db:
        producto = Producto(nombre=NOMBRE_INGRESO, precio_costo=1000, precio_venta=2000,
                            stock_actual=10, stock_minimo=2)
        db.add(producto)
        db.commit()
        producto_id = producto.id

    dialogo = IngresoMercaderiaDialog()
    # El combo abría con el primer producto del catálogo ya elegido, así que
    # "Añadir a la lista" sin mirar le sumaba stock al producto equivocado, y
    # eso se descubre recién cuando no cuadra el inventario.
    assert dialogo.combo_productos.count() > 0  # si no, lo de abajo no prueba nada
    assert dialogo.combo_productos.currentIndex() == -1
    assert not dialogo.boton_agregar.isEnabled()

    dialogo.combo_productos.setCurrentIndex(dialogo.combo_productos.findText(NOMBRE_INGRESO))
    assert dialogo.boton_agregar.isEnabled()
    # El combo es editable para poder filtrar: si el nombre saliera de
    # currentText(), este filtro a medio escribir quedaría guardado como nombre.
    dialogo.combo_productos.lineEdit().setText("qa fil")
    dialogo.spin_cantidad.setValue(6)
    dialogo.agregar_a_lista()
    assert dialogo.lista_ingreso[0]["nombre"] == NOMBRE_INGRESO

    dialogo.confirmar_ingreso()

    with SessionLocal() as db:
        assert db.get(Producto, producto_id).stock_actual == 16  # 10 + 6, una sola vez
        mov = db.scalar(
            select(KardexMovimiento).where(KardexMovimiento.producto_id == producto_id)
        )
        assert (mov.tipo_movimiento, mov.cantidad_movida) == ("ENTRADA", 6)
        assert mov.stock_resultante == 16  # lo calcula el trigger, no la aplicación


def test_el_ajuste_de_stock_registra_la_diferencia_por_kardex(app, bodeguero_qa, monkeypatch):
    """Recuento físico: lo que se teclea es el stock real, y lo que entra al
    Kardex es la diferencia, con signo. Un recuento igual al sistema no deja
    rastro, y es el mismo trigger el que mueve el stock."""
    from PySide6.QtWidgets import QMessageBox

    from src.ui.inventario import AjusteStockDialog

    avisos = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: avisos.append(a[1]))

    with SessionLocal() as db:
        producto = Producto(nombre=NOMBRE_INGRESO, precio_costo=1000, precio_venta=2000,
                            stock_actual=10, stock_minimo=2)
        db.add(producto)
        db.commit()
        producto_id = producto.id

    igual = AjusteStockDialog(producto_id=producto_id)
    assert igual.diferencia.text() == "sin cambios"
    igual.accept()
    assert avisos == ["Sin cambios"]

    recuento = AjusteStockDialog(producto_id=producto_id)
    recuento.contado.setValue(7)
    assert recuento.diferencia.text() == "-3"
    recuento.accept()

    with SessionLocal() as db:
        assert db.get(Producto, producto_id).stock_actual == 7
        (mov,) = db.scalars(
            select(KardexMovimiento).where(KardexMovimiento.producto_id == producto_id)
        ).all()
        assert (mov.tipo_movimiento, mov.cantidad_movida, mov.stock_resultante) == (
            "AJUSTE_MANUAL", -3, 7
        )
        assert mov.usuario_id == bodeguero_qa


def test_la_lista_de_ingreso_respeta_el_orden_en_que_se_agrego(app):
    # La tabla no ordena: quitar_seleccionado indexa la lista por fila visible,
    # y con ordenamiento activo borraría un producto distinto al elegido.
    from src.ui.inventario import IngresoMercaderiaDialog

    dialogo = IngresoMercaderiaDialog()
    # Regresión aparte: confirmar con la lista vacía mostraba "Éxito" y cerraba.
    assert not dialogo.boton_confirmar.isEnabled()

    dialogo.lista_ingreso = [
        {"producto_id": 1, "nombre": "ZZ Agregado primero", "stock_actual": 0, "cantidad": 1},
        {"producto_id": 2, "nombre": "AA Agregado después", "stock_actual": 0, "cantidad": 2},
    ]
    dialogo._redibujar_tabla()
    assert dialogo.tabla.item(0, 0).text() == "ZZ Agregado primero"
    assert dialogo.boton_confirmar.isEnabled()

    dialogo.tabla.setCurrentCell(0, 0)
    dialogo.quitar_seleccionado()
    assert [item["nombre"] for item in dialogo.lista_ingreso] == ["AA Agregado después"]


def test_el_minimo_por_categoria_alcanza_solo_a_su_categoria(app, bodeguero_qa):
    """Propuesta 3.2 pide configurar el mínimo por categoría; el dato sigue
    viviendo en cada producto (es lo que lee vw_stock_critico) y esto solo
    evita teclearlo 2.372 veces. No toca el stock ni pasa por Kardex."""
    from src.ui.inventario import MinimoPorCategoriaDialog

    categoria = f"QA Categoría {rut_de_prueba()}"
    with SessionLocal() as db:
        db.add_all([
            Producto(nombre=f"{NOMBRE_INGRESO} 1", categoria=categoria,
                     precio_costo=1, precio_venta=2, stock_actual=5),
            Producto(nombre=f"{NOMBRE_INGRESO} 2", categoria=categoria,
                     precio_costo=1, precio_venta=2, stock_actual=5, stock_minimo=99),
            Producto(nombre=f"{NOMBRE_INGRESO} 3", categoria="QA Otra",
                     precio_costo=1, precio_venta=2, stock_actual=5, stock_minimo=7),
        ])
        db.commit()

    dialogo = MinimoPorCategoriaDialog()
    dialogo.categoria.setCurrentIndex(dialogo.categoria.findText(categoria))
    assert "2 producto(s)" in dialogo.cuantos.text()
    dialogo.minimo.setValue(4)
    dialogo.accept()

    with SessionLocal() as db:
        de_la_categoria = db.scalars(
            select(Producto).where(Producto.categoria == categoria)
        ).all()
        assert [p.stock_minimo for p in de_la_categoria] == [4, 4]
        assert [p.stock_actual for p in de_la_categoria] == [5, 5]  # el stock no se toca
        otra = db.scalar(select(Producto).where(Producto.categoria == "QA Otra"))
        assert otra.stock_minimo == 7

    with SessionLocal() as db:  # limpieza: los deja el fixture bodeguero_qa por nombre
        for p in db.scalars(select(Producto).where(Producto.nombre.like(f"{NOMBRE_INGRESO}%"))):
            db.delete(p)
        db.commit()
