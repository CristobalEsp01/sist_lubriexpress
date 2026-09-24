"""Interfaz del mantenedor de Inventario, sin pantalla.

Verifica el camino que de verdad puede romperse: el formulario escribiendo en
la base y el listado leyéndola de vuelta.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from conftest import rut_de_prueba
from src.database import SessionLocal
from src.models import (
    CambioPrecio, DetalleVenta, KardexMovimiento, Producto, Ubicacion, Usuario, Venta,
)

NOMBRE = "QA Aceite de prueba"
NOMBRE_INGRESO = "QA Filtro ingreso"
UBICACION_INGRESO = "QA Repisa del ingreso"


@pytest.fixture
def limpiar():
    yield
    with SessionLocal() as db:
        for p in db.scalars(select(Producto).where(Producto.nombre == NOMBRE)):
            db.query(CambioPrecio).filter_by(producto_id=p.id).delete()
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
        db.query(CambioPrecio).filter(CambioPrecio.usuario_id == usuario_id).delete()
        for p in db.scalars(select(Producto).where(Producto.nombre.startswith(NOMBRE_INGRESO))):
            db.delete(p)
        for u in db.scalars(select(Ubicacion).where(Ubicacion.descripcion == UBICACION_INGRESO)):
            db.delete(u)
        usuario = db.get(Usuario, usuario_id)
        if usuario:
            db.delete(usuario)
        db.commit()


def test_el_formulario_crea_el_producto_y_no_deja_mover_el_stock_al_editar(app, limpiar,
                                                                          bodeguero_qa):
    from src.ui import FormularioProducto, InventarioWidget
    from src.ui.inventario import movimientos_de

    alta = FormularioProducto()
    alta.nombre.setText(NOMBRE)
    alta.marca.setText("Mobil")
    alta.categoria.setCurrentText("Aceite Motor")
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

    # El cambio de precio deja rastro: de cuánto a cuánto y quién. Crear el
    # producto no es un cambio, y guardarlo sin tocar el precio tampoco.
    FormularioProducto(producto_id=alta.producto_id).accept()
    with SessionLocal() as db:
        cambios = db.scalars(select(CambioPrecio).where(CambioPrecio.producto_id == alta.producto_id))
        assert [(int(c.precio_anterior), int(c.precio_nuevo), c.usuario_id) for c in cambios] == [
            (35000, 40000, bodeguero_qa)]
        _, tipo, cantidad, _, _, quien, detalle = movimientos_de(db, alta.producto_id)[0]
        assert (tipo, cantidad, quien, detalle) == (
            "Cambio de precio", None, "Bodeguero QA", "Venta neto $35.000 → $40.000")

    # Y se ve en los movimientos del producto, sin cantidad ni saldo.
    inventario = InventarioWidget()
    inventario.busqueda.setText(NOMBRE)
    inventario.tabla.selectRow(0)
    assert inventario.tabla_kardex.item(0, 1).text() == "Cambio de precio"
    assert inventario.tabla_kardex.item(0, 2).text() == ""


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
    _, tipo, cantidad, saldo, costo, quien, origen = movimientos[0]
    # Una salida no compra nada: no trae costo.
    assert (tipo, cantidad, saldo, costo) == ("Salida por venta", -2, 14, None)
    assert quien == "Bastián QA"
    assert origen == f"Boleta QA-{producto.id}"

    _, tipo, cantidad, saldo, _, _, origen = movimientos[1]
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
        {"producto_id": 1, "nombre": "ZZ Agregado primero", "stock_actual": 0,
         "cantidad": 1, "costo": 100, "venta": 150, "ubicacion": ""},
        {"producto_id": 2, "nombre": "AA Agregado después", "stock_actual": 0,
         "cantidad": 2, "costo": 200, "venta": 300, "ubicacion": "M4-C"},
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


def test_el_resumen_valoriza_a_costo_lo_que_muestra_la_tabla(app, limpiar, bodeguero_qa):
    """La cifra sigue el filtro: con uno puesto dice cuánto vale eso que quedó
    listado, y sin filtro, la bodega entera.

    Va a precio costo —plata inmovilizada, no venta futura— así que la ve quien
    ve la columna de costo: el dueño. El supervisor maneja la bodega sin verla.
    """
    from src.auth import Sesion
    from src.ui import InventarioWidget

    with SessionLocal() as db:
        db.add(Producto(nombre=NOMBRE, precio_costo=1000, precio_venta=2000,
                        stock_actual=3, stock_minimo=1))
        db.commit()

    supervisor = InventarioWidget()
    supervisor.busqueda.setText(NOMBRE)
    assert supervisor.tabla.rowCount() == 1 and supervisor.boton_ingreso.isEnabled()
    assert "a precio costo" not in supervisor.resumen.text()
    assert supervisor.tabla.isColumnHidden(6)

    Sesion.iniciar(SimpleNamespace(id=bodeguero_qa, nombre="Dueño QA", rol="ADMINISTRADOR"))
    widget = InventarioWidget()
    widget.busqueda.setText(NOMBRE)
    assert widget.tabla.rowCount() == 1
    assert "$3.000 a precio costo" in widget.resumen.text()   # 3 x 1.000

    widget.busqueda.setText("zzz producto que no existe zzz")
    assert "$0 a precio costo" in widget.resumen.text()

    Sesion.iniciar(SimpleNamespace(id=bodeguero_qa, nombre="Mecánico QA", rol="USUARIO_NORMAL"))
    mecanico = InventarioWidget()
    mecanico.busqueda.setText(NOMBRE)
    assert mecanico.tabla.rowCount() == 1
    assert "a precio costo" not in mecanico.resumen.text()
    assert mecanico.tabla.isColumnHidden(6)   # la columna de costo, tampoco


def test_la_categoria_se_elige_de_las_que_ya_existen(app, limpiar, bodeguero_qa):
    """Tecleada libre, la categoría se fragmenta: así el sistema antiguo llegó a
    tener cuatro repisas distintas para el filtro de aire."""
    from src.ui import FormularioProducto

    with SessionLocal() as db:
        db.add(Producto(nombre=NOMBRE, categoria="QA Filtro aire", precio_costo=1000,
                        precio_venta=2000, stock_actual=1, stock_minimo=1))
        db.commit()

    alta = FormularioProducto()
    opciones = [alta.categoria.itemText(i) for i in range(alta.categoria.count())]
    assert "QA Filtro aire" in opciones

    # Escrita de otra forma, gana la que ya existe: no nacen dos repisas.
    alta.categoria.setCurrentText("qa  FILTRO AIRE")
    assert alta._categoria_elegida() == "QA Filtro aire"

    # Y una categoría nueva sigue siendo posible: el combo no es una cárcel.
    alta.categoria.setCurrentText("QA Ampolletas")
    assert alta._categoria_elegida() == "QA Ampolletas"


def test_el_ingreso_registra_el_costo_de_esa_compra(app, bodeguero_qa, monkeypatch):
    """La mercadería llega con precios distintos cada vez. El costo del ingreso
    pasa a ser el del producto y queda guardado en el movimiento, que es la
    única forma de saber después a cuánto se compró en marzo."""
    from PySide6.QtWidgets import QMessageBox

    from src.ui.inventario import IngresoMercaderiaDialog

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)

    with SessionLocal() as db:
        producto = Producto(nombre=NOMBRE_INGRESO, precio_costo=1000, precio_venta=2000,
                            stock_actual=4, stock_minimo=1)
        db.add(producto)
        db.commit()
        producto_id = producto.id

    dialogo = IngresoMercaderiaDialog()
    dialogo.combo_productos.setCurrentIndex(dialogo.combo_productos.findText(NOMBRE_INGRESO))
    # Elegir el producto propone su costo actual: la mayoría de las veces no
    # cambió, y tener que retipearlo invita a dejarlo en cero.
    assert dialogo.spin_costo.value() == 1000

    dialogo.spin_cantidad.setValue(3)
    dialogo.spin_costo.setValue(1350)
    dialogo.agregar_a_lista()
    dialogo.confirmar_ingreso()

    with SessionLocal() as db:
        producto = db.get(Producto, producto_id)
        assert producto.stock_actual == 7
        assert producto.precio_costo == 1350
        movimiento = db.scalar(
            select(KardexMovimiento).where(KardexMovimiento.producto_id == producto_id)
        )
        assert (movimiento.cantidad_movida, movimiento.costo_unitario) == (3, 1350)
        # El precio de venta propuesto no se tocó: no es un cambio.
        assert db.query(CambioPrecio).filter_by(producto_id=producto_id).count() == 0
        # Y se puede consultar después, que es para lo que se guarda.
        from src.ui.inventario import movimientos_de
        assert movimientos_de(db, producto_id)[0][4] == 1350


def test_el_ingreso_fija_el_precio_de_venta_y_la_ubicacion(app, bodeguero_qa, monkeypatch):
    """Recibir la mercadería es cuando alguien la pone en la repisa: el momento
    de anotar dónde quedó (casi todo lo migrado no tiene ubicación) y de subir
    el precio si la compra subió. El precio es neto, así que se ve con IVA."""
    from PySide6.QtWidgets import QMessageBox

    from src.ui.inventario import IngresoMercaderiaDialog

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    with SessionLocal() as db:
        filtro = Producto(nombre=f"{NOMBRE_INGRESO} aire", precio_costo=1000, precio_venta=2000,
                          stock_actual=4, stock_minimo=1)
        aceite = Producto(nombre=f"{NOMBRE_INGRESO} aceite", precio_costo=3000, precio_venta=5000,
                          stock_actual=2, stock_minimo=1)
        db.add_all([filtro, aceite])
        db.commit()
        filtro_id, aceite_id = filtro.id, aceite.id

    dialogo = IngresoMercaderiaDialog()
    dialogo.combo_productos.setCurrentIndex(dialogo.combo_productos.findText(filtro.nombre))
    # Propone lo que el producto tiene hoy, igual que el costo.
    assert (dialogo.spin_venta.value(), dialogo.venta_con_iva.text()) == (2000, "con IVA $2.380")
    assert dialogo.combo_ubicacion.currentText() == ""

    dialogo.spin_costo.setValue(1350)
    dialogo.spin_venta.setValue(2500)
    dialogo.combo_ubicacion.setCurrentText(UBICACION_INGRESO)
    dialogo.agregar_a_lista()
    assert dialogo.tabla.item(0, 5).text() == "$2.500"
    assert dialogo.tabla.item(0, 6).text() == UBICACION_INGRESO

    # Vender bajo el costo se pregunta, igual que en el formulario del producto.
    dialogo.combo_productos.setCurrentIndex(dialogo.combo_productos.findText(aceite.nombre))
    dialogo.spin_costo.setValue(6000)
    dialogo.combo_ubicacion.setCurrentText(UBICACION_INGRESO)   # la misma repisa, nueva
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    dialogo.agregar_a_lista()
    assert len(dialogo.lista_ingreso) == 1
    dialogo.spin_venta.setValue(7000)
    dialogo.agregar_a_lista()
    dialogo.confirmar_ingreso()

    with SessionLocal() as db:
        filtro, aceite = db.get(Producto, filtro_id), db.get(Producto, aceite_id)
        assert (filtro.precio_costo, filtro.precio_venta) == (1350, 2500)
        assert (aceite.precio_costo, aceite.precio_venta) == (6000, 7000)
        assert filtro.ubicacion.descripcion == aceite.ubicacion.descripcion == UBICACION_INGRESO
        # Dos productos a una repisa nueva en el mismo ingreso: una sola repisa.
        assert db.query(Ubicacion).filter_by(descripcion=UBICACION_INGRESO).count() == 1
        cambios = db.scalars(select(CambioPrecio).where(
            CambioPrecio.producto_id.in_([filtro_id, aceite_id])).order_by(CambioPrecio.id))
        assert [(c.producto_id, int(c.precio_anterior), int(c.precio_nuevo)) for c in cambios] == [
            (filtro_id, 2000, 2500), (aceite_id, 5000, 7000)]
