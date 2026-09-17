"""Interfaz del módulo de Órdenes de Trabajo, sin pantalla.

OrdenesWidget escribe con su propia SessionLocal() en cada operación (no con el
fixture `db`, que revierte todo al terminar), así que los datos de apoyo se
crean con commits reales y se limpian explícitamente al final — igual que en
test_ui_ventas.py.
"""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from sqlalchemy import select

from conftest import patente_de_prueba, rut_de_prueba
from src.auth import Sesion
from src.database import SessionLocal
from src.models import (
    Cliente, DetalleOrden, KardexMovimiento, Orden, Producto, Servicio, Usuario, Vehiculo,
)
from src.ui.ordenes import COLUMNAS_HISTORIAL

NOMBRE_PRODUCTO = "QA Aceite de motor 10W40"
NOMBRE_SERVICIO = "QA Cambio de aceite"
NOMBRE_CLIENTE = "QA Dueño del taller"


@pytest.fixture
def limpiar():
    yield
    with SessionLocal() as db:
        cliente = db.scalar(select(Cliente).where(Cliente.nombre_completo == NOMBRE_CLIENTE))
        if cliente:
            for vehiculo in db.scalars(select(Vehiculo).where(Vehiculo.cliente_id == cliente.id)):
                for orden in db.scalars(select(Orden).where(Orden.vehiculo_id == vehiculo.id)):
                    db.query(KardexMovimiento).filter_by(orden_id=orden.id).delete()
                    db.query(DetalleOrden).filter_by(orden_id=orden.id).delete()
                    db.delete(orden)
                db.delete(vehiculo)
            db.delete(cliente)
        producto = db.scalar(select(Producto).where(Producto.nombre == NOMBRE_PRODUCTO))
        if producto:
            db.query(KardexMovimiento).filter_by(producto_id=producto.id).delete()
            db.delete(producto)
        db.query(Servicio).filter_by(nombre=NOMBRE_SERVICIO).delete()
        for usuario in db.scalars(select(Usuario).where(Usuario.username.like("qa_mecanico_%"))):
            db.delete(usuario)
        db.commit()


@pytest.fixture
def taller(limpiar):
    """Mecánico con sesión iniciada, un producto con 10 unidades, un servicio
    y un vehículo."""
    with SessionLocal() as db:
        usuario = Usuario(
            nombre="Mecánico QA", username=f"qa_mecanico_{rut_de_prueba()}",
            password_hash="hash-de-prueba", rol="USUARIO_NORMAL",
        )
        producto = Producto(
            nombre=NOMBRE_PRODUCTO, marca="Castrol", precio_costo=6000,
            precio_venta=12900, stock_actual=10, stock_minimo=2,
        )
        servicio = Servicio(nombre=NOMBRE_SERVICIO, precio_venta=15000)
        cliente = Cliente(rut=rut_de_prueba(), nombre_completo=NOMBRE_CLIENTE)
        vehiculo = Vehiculo(cliente=cliente, patente=patente_de_prueba(),
                            marca="Toyota", modelo="Yaris")
        db.add_all([usuario, producto, servicio, vehiculo])
        db.commit()
        datos = SimpleNamespace(
            usuario_id=usuario.id, producto_id=producto.id, servicio_id=servicio.id,
            vehiculo_id=vehiculo.id,
        )
        Sesion.iniciar(SimpleNamespace(id=usuario.id, nombre=usuario.nombre, rol=usuario.rol))

    yield datos
    Sesion.cerrar()


@pytest.fixture
def sin_modales(monkeypatch):
    """Los avisos son QMessageBox reales: sin silenciarlos el modal nunca se
    cierra solo y la prueba queda colgada. Devuelve los títulos mostrados."""
    from PySide6.QtWidgets import QMessageBox

    titulos = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: titulos.append(a[1]))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: titulos.append(a[1]))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    return titulos


def test_mirar_el_historial_no_descarta_la_orden_en_progreso(app, taller, sin_modales, monkeypatch):
    """Regresión: abrir_detalle_orden limpiaba el formulario de la pestaña 1.

    Estaba copiado de _iniciar_nueva_orden, así que abrir una orden vieja del
    historial para consultarla borraba la que se estaba armando: carrito,
    kilometraje y observaciones. Mirar no puede escribir.
    """
    from src.ui import ordenes

    with SessionLocal() as db:
        db.add(Orden(vehiculo_id=taller.vehiculo_id, usuario_id=taller.usuario_id,
                     kilometraje_ingreso=98000, subtotal=0, total_final=0))
        db.commit()

    monkeypatch.setattr(ordenes.DialogoDetalleOrden, "exec", lambda self: 0)

    widget = ordenes.OrdenesWidget()
    widget._iniciar_nueva_orden(taller.vehiculo_id)
    # La tarjeta dice contra qué se compara el kilometraje de hoy.
    assert not widget.tarjeta.isHidden()
    assert "98.000 km" in widget.label_servicio.text()
    assert widget.label_vehiculo.text() == "Toyota Yaris"
    widget.agregar_al_carrito(taller.producto_id, 2)

    # Menos kilómetros que el servicio anterior: se pregunta; con No, no se guarda.
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    widget.spin_kilometraje.setValue(50000)
    widget.guardar_orden()
    with SessionLocal() as db:
        assert db.query(Orden).filter_by(vehiculo_id=taller.vehiculo_id).count() == 1

    widget.spin_kilometraje.setValue(120000)
    widget.texto_observaciones.setPlainText("Ingresa con raya en la puerta")

    widget.setCurrentIndex(1)               # carga el historial
    widget.tabla_historial.selectRow(0)     # elegir una fila es lo que junta los connect
    widget.abrir_detalle_orden()

    assert widget.tabla_carrito.rowCount() == 1
    assert widget.spin_kilometraje.value() == 120000
    assert widget.texto_observaciones.toPlainText() == "Ingresa con raya en la puerta"


def test_lo_que_queda_en_el_carrito_es_lo_que_se_guarda(app, taller, sin_modales, tmp_path):
    """El camino del dinero, de punta a punta y por la pantalla.

    `test_triggers.py` ya prueba que insertar en detalle_ordenes descuenta y
    deja rastro; lo que falta cubrir es que la pantalla llegue hasta ahí: una
    sola transacción, el usuario de la sesión, y ni una escritura a
    `stock_actual` de por medio.

    Quitar va en la misma prueba porque es el mismo sujeto: lo que la tabla
    tiene al apretar Guardar es lo que termina en la base. Y el servicio
    también: se cobra en la misma orden, pero no toca el stock ni el Kardex.
    """
    from src.ui import ordenes

    widget = ordenes.OrdenesWidget()
    widget._iniciar_nueva_orden(taller.vehiculo_id)
    widget.agregar_al_carrito(taller.producto_id, 5)  # cantidad equivocada
    widget.agregar_al_carrito(taller.producto_id, 3)

    # Ordenar antes de quitar: así la fila visible deja de ser la de inserción,
    # que es exactamente como el ingreso de mercadería llegó a quitar el
    # producto equivocado. Acá los datos viajan en la fila, no en una lista
    # paralela, y por eso no se descalza.
    widget.tabla_carrito.sortItems(1, Qt.DescendingOrder)
    widget.tabla_carrito.selectRow(0)                 # la de 5
    assert widget.boton_quitar.isEnabled()
    widget.quitar_del_carrito()
    assert widget.tabla_carrito.rowCount() == 1
    assert widget.totales.neto.text() == "$38.700"    # 3 x 12.900, no 5
    assert widget.total.text() == "$46.053"           # con el 19 % de IVA

    widget.agregar_servicio_al_carrito(taller.servicio_id)
    assert widget.tabla_carrito.rowCount() == 2
    assert widget.totales.neto.text() == "$53.700"    # + 15.000 de mano de obra

    # Descuento: un selector y un solo campo, así porcentaje y monto no pueden
    # coincidir (la base lo prohíbe). El IVA se calcula sobre lo descontado.
    widget.tipo_descuento.setCurrentIndex(2)          # monto
    widget.valor_descuento.setValue(5000)
    assert widget.total.text() == "$57.953"           # (53.700 - 5.000) x 1,19
    widget.tipo_descuento.setCurrentIndex(1)          # porcentaje: el campo se reinicia
    assert widget.valor_descuento.value() == 0
    widget.valor_descuento.setValue(10)
    assert widget.totales.descuento.text() == "- $5.370"
    assert widget.total.text() == "$57.513"           # 48.330 + 9.183
    widget.folio.setText("MP-2026-001")
    widget.pagada.setChecked(True)

    # Soltar la selección apaga el botón. Qt conserva la celda actual, así que
    # preguntar por currentRow() lo dejaba encendido sobre una fila que ya no
    # se ve elegida — y Quitar sacaba esa.
    widget.tabla_carrito.clearSelection()
    assert not widget.boton_quitar.isEnabled()

    # El kilometraje se promete obligatorio con un asterisco y nace en 0, que
    # parece un valor escrito. Sin él la OT no sirve: es el dato con que se
    # calcula el próximo servicio.
    assert widget.spin_kilometraje.value() == 0
    assert widget.spin_kilometraje.text() == "Sin registrar"   # no "0 km"
    assert not widget.boton_guardar.isEnabled()
    widget.guardar_orden()
    assert sin_modales[-1] == "Falta el kilometraje"

    widget.spin_kilometraje.setValue(120000)
    assert widget.boton_guardar.isEnabled()
    widget.guardar_orden()

    with SessionLocal() as db:
        orden = db.scalar(select(Orden).where(Orden.vehiculo_id == taller.vehiculo_id))
        assert orden.usuario_id == taller.usuario_id
        assert orden.kilometraje_ingreso == 120000
        # El IVA se calcula al cobrar y queda en la orden, no se re-deriva.
        assert (int(orden.subtotal), int(orden.descuento_porcentaje), int(orden.descuento_monto),
                int(orden.impuesto), int(orden.total_final)) == (53700, 10, 0, 9183, 57513)
        assert orden.descuento_aplicado == 5370
        assert (orden.folio_mercado_publico, orden.estado_pago) == ("MP-2026-001", True)

        detalles = db.scalars(
            select(DetalleOrden).where(DetalleOrden.orden_id == orden.id).order_by(DetalleOrden.id)
        ).all()
        assert [(d.producto_id, d.servicio_id, d.cantidad) for d in detalles] == [
            (taller.producto_id, None, 3), (None, taller.servicio_id, 1),
        ]

        assert db.get(Producto, taller.producto_id).stock_actual == 7  # 10 - 3

        # El PDF para el cliente sale de lo guardado, con el servicio incluido.
        ordenes.guardar_pdf_de_orden(orden.id, tmp_path / "ot.pdf")
        assert (tmp_path / "ot.pdf").read_bytes()[:4] == b"%PDF"

        # Un solo movimiento: el del producto. El servicio no deja rastro en el Kardex.
        mov = db.scalar(select(KardexMovimiento).where(KardexMovimiento.orden_id == orden.id))
        assert (mov.tipo_movimiento, mov.cantidad_movida, mov.stock_resultante) == (
            "SALIDA_ORDEN", -3, 7
        )
        assert mov.usuario_id == taller.usuario_id

    # La pantalla vuelve al reposo: sin esto la orden siguiente arrastraría la anterior.
    assert not widget.panel_trabajo.isEnabled()
    assert widget.boton_nueva_orden.isEnabled()
    assert widget.tipo_descuento.currentIndex() == 0 and widget.folio.text() == ""

    # El historial separa lo institucional (con folio) de los clientes.
    widget.setCurrentIndex(1)
    widget.busqueda_historial.setText(NOMBRE_CLIENTE)
    columna = COLUMNAS_HISTORIAL.index("Folio MP")
    widget.filtro_historial.setCurrentText("Mercado Público")
    assert [widget.tabla_historial.item(f, columna).text()
            for f in range(widget.tabla_historial.rowCount())] == ["MP-2026-001"]
    widget.filtro_historial.setCurrentText("Clientes")
    assert widget.tabla_historial.rowCount() == 0


def test_la_ventana_recorre_sus_cuatro_pestanas_sin_reventar(app, taller, sin_modales):
    """Smoke de arranque: abrir cada pestaña y elegir una fila en cada tabla.

    Qt no propaga lo que revienta dentro de un slot; el hookwrapper de
    `conftest.py` lo convierte en fallo, pero solo si alguien dispara las
    señales. Recorrer las pestañas y seleccionar es lo primero que hace
    cualquiera al abrir la aplicación, y es donde se juntan los `connect`.
    """
    from PySide6.QtWidgets import QTableWidget, QTabWidget

    from src.ui import VentanaPrincipal

    ventana = VentanaPrincipal()
    for pestanas in ventana.findChildren(QTabWidget):
        for indice in range(pestanas.count()):
            pestanas.setCurrentIndex(indice)

    for tabla in ventana.findChildren(QTableWidget):
        if tabla.rowCount():
            tabla.selectRow(0)

    assert ventana.pestanias.count() == 5  # Reportes también, para todos


def test_la_cifra_del_total_no_se_corta_en_la_ventana_mas_chica(app, taller):
    """La orden es la pantalla más densa: al mínimo declarado de la ventana,
    el total —el resultado de la pantalla— tiene que caber entero. Ya se cortó
    a 13 px de los 35 que mide, y el bloque de totales cedía alto antes que el
    campo de observaciones."""
    from src.ui import VentanaPrincipal

    ventana = VentanaPrincipal()
    ventana.resize(ventana.minimumSize())
    ventana.show()
    ventana.pestanias.setCurrentWidget(ventana.ordenes)
    ventana.ordenes._iniciar_nueva_orden(taller.vehiculo_id)

    cifra = ventana.ordenes.totales.total
    assert cifra.height() >= cifra.sizeHint().height()
    ventana.close()
