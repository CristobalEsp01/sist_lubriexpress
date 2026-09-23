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
    Cliente, DetalleOrden, KardexMovimiento, Orden, PagoOrden, Producto, Servicio, Usuario,
    Vehiculo,
)
from src.ui.ordenes import COLUMNAS_HISTORIAL, TIPOS_DESCUENTO

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
                    # El detalle va primero: borrarlo dispara el trigger de
                    # devolución, que escribe kardex nuevo. Al revés, esas filas
                    # quedarían apuntando a una orden que ya no se puede borrar.
                    db.query(DetalleOrden).filter_by(orden_id=orden.id).delete()
                    db.flush()
                    db.query(KardexMovimiento).filter_by(orden_id=orden.id).delete()
                    db.query(PagoOrden).filter_by(orden_id=orden.id).delete()
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

    widget.setCurrentIndex(2)               # carga el historial
    widget.tabla_historial.selectRow(0)     # elegir una fila es lo que junta los connect
    widget.abrir_detalle_orden()

    assert widget.tabla_carrito.rowCount() == 1
    assert widget.spin_kilometraje.value() == 120000
    assert widget.texto_observaciones.toPlainText() == "Ingresa con raya en la puerta"


def test_lo_que_queda_en_el_carrito_es_lo_que_se_guarda(app, taller, sin_modales, tmp_path,
                                                        monkeypatch):
    """El camino del dinero, de punta a punta y por la pantalla.

    `test_triggers.py` ya prueba que insertar en detalle_ordenes descuenta y
    deja rastro; lo que falta cubrir es que la pantalla llegue hasta ahí: una
    sola transacción, el usuario de la sesión, y ni una escritura a
    `stock_actual` de por medio.

    Quitar va en la misma prueba porque es el mismo sujeto: lo que la tabla
    tiene al apretar Guardar es lo que termina en la base. Y el servicio
    también: se cobra en la misma orden, pero no toca el stock ni el Kardex.
    """
    from PySide6.QtWidgets import QInputDialog

    from src.ui import ordenes

    widget = ordenes.OrdenesWidget()
    widget._iniciar_nueva_orden(taller.vehiculo_id)
    widget.agregar_servicio_al_carrito(taller.servicio_id)
    widget.agregar_al_carrito(taller.producto_id, 5)  # cantidad equivocada
    widget.agregar_al_carrito(taller.producto_id, 1)  # el mismo otra vez: suma a su línea
    assert widget.tabla_carrito.rowCount() == 2

    # Ordenar antes de tocar una fila: así la visible deja de ser la de
    # inserción, que es exactamente como el ingreso de mercadería llegó a quitar
    # el producto equivocado. Acá los datos viajan en la fila, no en una lista
    # paralela, y por eso no se descalza.
    widget.tabla_carrito.sortItems(1, Qt.DescendingOrder)
    widget.tabla_carrito.selectRow(0)                 # la de 6
    monkeypatch.setattr(QInputDialog, "getInt", staticmethod(lambda *a, **k: (3, True)))
    widget.cambiar_cantidad()
    assert widget.totales.neto.text() == "$53.700"    # 3 x 12.900 + 15.000
    assert widget.total.text() == "$63.900"           # 63.903 con IVA, a la decena

    def fila_del_servicio():
        return next(f for f in range(widget.tabla_carrito.rowCount())
                    if "servicio_id" in widget.tabla_carrito.item(f, 0).data(Qt.UserRole))

    widget.tabla_carrito.selectRow(fila_del_servicio())
    assert widget.boton_quitar.isEnabled()
    widget.quitar_del_carrito()
    assert widget.tabla_carrito.rowCount() == 1
    assert widget.totales.neto.text() == "$38.700"    # quedó el aceite, y con 3
    # 46.053 con el 19 % de IVA; la ley de redondeo lo lleva a la decena.
    assert widget.total.text() == "$46.050"

    widget.agregar_servicio_al_carrito(taller.servicio_id)
    assert widget.tabla_carrito.rowCount() == 2
    assert widget.totales.neto.text() == "$53.700"    # + 15.000 de mano de obra

    # Descuento: un selector y un solo campo, así porcentaje y monto no pueden
    # coincidir (la base lo prohíbe). El IVA se calcula sobre lo descontado.
    widget.tipo_descuento.setCurrentIndex(2)          # monto
    widget.valor_descuento.setValue(5000)
    assert widget.total.text() == "$57.950"           # (53.700 - 5.000) x 1,19 = 57.953
    widget.tipo_descuento.setCurrentIndex(1)          # porcentaje: el campo se reinicia
    assert widget.valor_descuento.value() == 0
    widget.valor_descuento.setValue(10)
    assert widget.totales.descuento.text() == "- $5.370"
    assert widget.total.text() == "$57.510"           # 48.330 + 9.183 = 57.513
    widget.folio.setText("MP-2026-001")
    widget.pagada.setChecked(True)
    widget.combo_medio_pago.setCurrentText("Efectivo")

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
                int(orden.impuesto), int(orden.ajuste_redondeo), int(orden.total_final)
                ) == (53700, 10, 0, 9183, -3, 57510)
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

    assert ventana.pestanias.count() == 6  # Caja y Reportes también, para todos


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


def _fijar_telefono(vehiculo_id: int, telefono: str | None) -> None:
    with SessionLocal() as db:
        vehiculo = db.get(Vehiculo, vehiculo_id)
        db.get(Cliente, vehiculo.cliente_id).telefono = telefono
        db.commit()


def test_el_aviso_por_whatsapp_sale_de_la_orden_abierta(app, taller, monkeypatch):
    """El botón se mudó del mantenedor de Clientes a la orden en curso.

    Acá el mensaje puede decir de qué vehículo se habla, que es lo que el
    cliente necesita saber; en el mantenedor solo se sabía a quién escribirle.
    """
    from PySide6.QtCore import QUrl, QUrlQuery
    from PySide6.QtGui import QDesktopServices

    from src.ui import ordenes

    _fijar_telefono(taller.vehiculo_id, "9 5666 7509")

    widget = ordenes.OrdenesWidget()
    # En reposo no hay a quién escribirle: no hay orden abierta.
    assert not widget.boton_whatsapp.isEnabled()

    widget._iniciar_nueva_orden(taller.vehiculo_id)
    assert widget.boton_whatsapp.isEnabled()

    abiertos = []
    # Se guarda el QUrl tal cual, no su .toString(): Qt "embellece" la
    # representación en texto al convertirla —decodifica %20 pero deja %2C—,
    # así que comparar contra un string armado a mano queda a merced de un
    # detalle interno de QUrl que no tiene que ver con si el enlace es correcto.
    monkeypatch.setattr(
        QDesktopServices, "openUrl", staticmethod(lambda url: abiertos.append(url)),
    )

    dialogo = ordenes.DialogoWhatsApp(parent=widget, **widget.contacto_whatsapp)
    # El borrador ya viene escrito con el cliente y su vehículo.
    borrador = dialogo.texto.toPlainText()
    assert NOMBRE_CLIENTE in borrador and "Toyota Yaris" in borrador
    assert "listo para ser retirado" in borrador
    # Todavía no está guardada, así que no puede citar un número de OT.
    assert "Orden de trabajo" not in borrador

    # Editable antes de enviar: lo que se manda es lo que quedó en la caja.
    dialogo.texto.setPlainText("Su auto quedó listo, lo esperamos.")
    dialogo.abrir_whatsapp()
    assert len(abiertos) == 1
    url = abiertos[0]
    assert url.toString().startswith("https://wa.me/56956667509?text=")
    # Lo que importa es que el mensaje llegue completo al decodificarlo, no la
    # forma exacta en que Qt eligió representar los caracteres especiales.
    assert QUrlQuery(url).queryItemValue("text", QUrl.FullyDecoded) == (
        "Su auto quedó listo, lo esperamos."
    )

    # Cerrada la orden, no queda a quién escribirle.
    widget._volver_al_reposo()
    assert not widget.boton_whatsapp.isEnabled()
    assert widget.contacto_whatsapp is None


def test_sin_celular_registrado_el_boton_de_whatsapp_queda_apagado(app, taller):
    """Un cliente con solo teléfono fijo —o sin teléfono— no puede recibir el
    aviso: el botón se apaga en vez de abrir un chat que no existe."""
    from src.ui import ordenes

    _fijar_telefono(taller.vehiculo_id, "63 222 2333")  # fijo de Valdivia
    widget = ordenes.OrdenesWidget()
    widget._iniciar_nueva_orden(taller.vehiculo_id)
    assert not widget.boton_whatsapp.isEnabled()
    assert "no tiene registrado un celular" in widget.boton_whatsapp.toolTip()

    _fijar_telefono(taller.vehiculo_id, None)
    widget._iniciar_nueva_orden(taller.vehiculo_id)
    assert not widget.boton_whatsapp.isEnabled()


def test_la_orden_se_cierra_con_un_abono_y_el_saldo_se_cobra_despues(app, taller, sin_modales,
                                                                    monkeypatch):
    """El cliente deja un abono al cerrar la orden y paga el resto al retirar.

    Las dos mitades viven en pantallas distintas a propósito: el abono en el
    formulario, mientras la orden se arma, y el saldo en el detalle del
    historial, que es donde se busca una orden que ya se guardó.
    """
    from PySide6.QtWidgets import QDialog

    from src.ui import ordenes

    widget = ordenes.OrdenesWidget()
    widget._iniciar_nueva_orden(taller.vehiculo_id)
    widget.agregar_al_carrito(taller.producto_id, 1)   # 12.900 + IVA
    widget.spin_kilometraje.setValue(120000)
    # Sin nada que cobrar el medio de pago no importa y se ve apagado.
    assert not widget.combo_medio_pago.isEnabled()
    # Nadie abona más de lo que vale la orden, y la orden cambia mientras se arma.
    assert widget.abono.maximum() == 15350             # 15.351, redondeado
    widget.abono.setValue(10000)
    assert widget.combo_medio_pago.isEnabled()
    # Con un abono, el medio se elige: la caja cuenta el efectivo por él.
    widget.guardar_orden()
    assert sin_modales[-1] == "Falta el medio de pago"
    widget.combo_medio_pago.setCurrentText("Efectivo")
    widget.guardar_orden()

    with SessionLocal() as db:
        orden = db.scalar(select(Orden).where(Orden.vehiculo_id == taller.vehiculo_id))
        # Lo decide el trigger con la suma de los abonos, no la pantalla.
        assert not orden.estado_pago
        assert (orden.monto_pagado, orden.saldo) == (10000, 5350)
        orden_id = orden.id

    # En el historial no es ni "Pagada" ni "No pagada": el mesón tiene que ver
    # cuáles quedaron a medio cobrar.
    widget.setCurrentIndex(2)
    estado = widget.tabla_historial.item(0, COLUMNAS_HISTORIAL.index("Pago"))
    assert estado.text() == "Abonada"
    assert "saldo $5.350" in estado.toolTip()

    dialogo = ordenes.DialogoDetalleOrden(orden_id, widget)
    assert dialogo.saldo == 5350 and dialogo.boton_pago.isEnabled()
    assert "Abonada $10.000 · saldo $5.350" in dialogo.info.text()

    # Monto y medio en una sola ventana, y el medio sin elegir no pasa.
    pago = ordenes.DialogoPago(5350)
    pago.accept()
    assert sin_modales[-1] == "Falta el medio de pago"

    # El tope del abono es el saldo, no el total: un pago se suma, no corrige.
    argumentos = {}

    def pagar_con_tarjeta(self):
        argumentos.update(valor=self.monto.value(), minimo=self.monto.minimum(),
                          maximo=self.monto.maximum())
        self.medio.setCurrentText("Tarjeta")
        return QDialog.Accepted

    monkeypatch.setattr(ordenes.DialogoPago, "exec", pagar_con_tarjeta)
    dialogo.registrar_pago()
    assert (argumentos["valor"], argumentos["minimo"], argumentos["maximo"]) == (5350, 1, 5350)
    assert dialogo.saldo == 0 and not dialogo.boton_pago.isEnabled()
    assert "Pagada" in dialogo.info.text()

    with SessionLocal() as db:
        orden = db.get(Orden, orden_id)
        assert orden.estado_pago and orden.monto_pagado == 15350
        assert [p.medio_pago for p in orden.pagos] == ["EFECTIVO", "TARJETA"]


def test_desde_el_historial_el_aviso_por_whatsapp_cita_el_numero_de_la_orden(app, taller,
                                                                            monkeypatch):
    """"Listo para retiro" se manda con el auto terminado, o sea con la orden ya
    guardada: es el único momento en que hay un número de OT que citar."""
    from src.ui import ordenes

    _fijar_telefono(taller.vehiculo_id, "9 5666 7509")
    with SessionLocal() as db:
        orden = Orden(vehiculo_id=taller.vehiculo_id, usuario_id=taller.usuario_id,
                      kilometraje_ingreso=98000, subtotal=0, total_final=0)
        db.add(orden)
        db.commit()
        orden_id = orden.id

    avisos = []
    monkeypatch.setattr(ordenes.DialogoWhatsApp, "exec", lambda self: avisos.append(self) or 0)

    dialogo = ordenes.DialogoDetalleOrden(orden_id, None)
    assert dialogo.boton_whatsapp.isEnabled()
    dialogo.avisar_por_whatsapp()
    borrador = avisos[0].texto.toPlainText()
    assert f"Orden de trabajo N° {orden_id}." in borrador
    assert "Toyota Yaris" in borrador

    _fijar_telefono(taller.vehiculo_id, None)
    assert not ordenes.DialogoDetalleOrden(orden_id, None).boton_whatsapp.isEnabled()


def test_el_detalle_deja_ver_las_lineas_de_la_orden(app, taller):
    """Fabián abrió una orden y la tabla de insumos medía menos de una fila: el
    pie de totales ganó la fila del redondeo y se comió el alto que quedaba."""
    from PySide6.QtWidgets import QTableWidget

    from src.ui import ordenes
    from src.ui.tema import ALTO_FILA

    with SessionLocal() as db:
        orden = Orden(vehiculo_id=taller.vehiculo_id, usuario_id=taller.usuario_id,
                      subtotal=0, total_final=0)
        db.add(orden)
        db.commit()
        orden_id = orden.id

    dialogo = ordenes.DialogoDetalleOrden(orden_id, None)
    dialogo.show()
    app.processEvents()
    assert dialogo.findChild(QTableWidget).viewport().height() >= 3 * ALTO_FILA
    dialogo.close()


def test_el_catalogo_se_filtra_tecleando_y_enter_agrega_a_la_orden(app, taller, sin_modales,
                                                                   monkeypatch):
    """Productos y servicios en un solo buscador, con marca, stock, repisa y
    precio a la vista. Enter agrega; si ya estaba, suma a la misma línea."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    from src.ui import catalogo as modulo_catalogo
    from src.ui import ordenes
    from src.ui.catalogo import COLUMNAS

    widget = ordenes.OrdenesWidget()
    widget._iniciar_nueva_orden(taller.vehiculo_id)
    catalogo = widget.catalogo

    # Filtrar no vuelve a la base: era ir a buscar y rearmar la tabla en cada
    # tecla lo que trababa la pantalla.
    def sin_base():
        raise AssertionError("filtrar no consulta la base")
    monkeypatch.setattr(modulo_catalogo, "SessionLocal", sin_base)

    catalogo.busqueda.setText("qa castrol 10w40")         # palabras sueltas, en desorden
    (fila,) = catalogo.visibles()
    celdas = {COLUMNAS[c]: catalogo.tabla.item(fila, c).text() for c in range(len(COLUMNAS))}
    assert (celdas["Nombre"], celdas["Marca"]) == (NOMBRE_PRODUCTO, "Castrol")
    assert celdas["Stock"] == "10"
    assert celdas["Precio neto"] == "$12.900"

    catalogo.busqueda.returnPressed.emit()                  # uno solo: Enter lo agrega
    catalogo.busqueda.returnPressed.emit()                  # otra vez: suma, no duplica
    assert widget.tabla_carrito.rowCount() == 1
    assert widget.tabla_carrito.item(0, 1).text() == "2"

    # Dos resultados y nada elegido: Enter no adivina. La flecha elige sin
    # sacar el cursor del campo, y ahí Enter agrega.
    catalogo.busqueda.setText("qa aceite")                 # el producto y el servicio
    assert len(catalogo.visibles()) == 2
    catalogo.busqueda.returnPressed.emit()
    assert widget.tabla_carrito.rowCount() == 1
    for _ in range(2):                                      # el aceite, y después el servicio
        catalogo.eventFilter(catalogo.busqueda,
                             QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier))
    assert catalogo.seleccionado() == {"servicio_id": taller.servicio_id}
    catalogo.busqueda.returnPressed.emit()
    assert widget.tabla_carrito.rowCount() == 2

    catalogo.busqueda.setText("zzz nada se llama así zzz")
    assert catalogo.visibles() == [] and catalogo.tabla.aviso.isVisibleTo(catalogo.tabla)


def test_las_pestanas_y_la_categoria_filtran_junto_con_lo_escrito(app, taller):
    """Todo / Productos / Servicios y la categoría acotan lo que deja la
    búsqueda; no la reemplazan. Y el catálogo de la orden no pasa de su alto:
    lo importante de la pantalla es lo que lleva la orden."""
    from src.ui import ordenes
    from src.ui.catalogo import TODAS
    from src.ui.tema import ALTO_FILA

    with SessionLocal() as db:
        db.get(Producto, taller.producto_id).categoria = "QA Aceites"
        db.get(Servicio, taller.servicio_id).categoria = "QA Mano de obra"
        db.commit()

    widget = ordenes.OrdenesWidget()
    widget._iniciar_nueva_orden(taller.vehiculo_id)
    catalogo = widget.catalogo

    def elegidos():
        return [catalogo.tabla.item(f, 0).data(Qt.UserRole) for f in catalogo.visibles()]

    def categorias():
        return [catalogo.categoria.itemText(i) for i in range(catalogo.categoria.count())]

    catalogo.busqueda.setText("qa aceite")                    # el producto y el servicio
    assert len(elegidos()) == 2
    catalogo.pestanas.setCurrentIndex(2)                      # Servicios
    assert elegidos() == [{"servicio_id": taller.servicio_id}]
    assert "QA Mano de obra" in categorias() and "QA Aceites" not in categorias()

    catalogo.pestanas.setCurrentIndex(0)                      # Todo
    catalogo.categoria.setCurrentText("QA Aceites")
    assert elegidos() == [{"producto_id": taller.producto_id}]
    # Una categoría que la pestaña no tiene se suelta, en vez de dejar la
    # lista vacía sin que se entienda por qué.
    catalogo.pestanas.setCurrentIndex(2)
    assert catalogo.categoria.currentText() == TODAS

    assert catalogo.tabla.maximumHeight() < 7 * ALTO_FILA


def test_en_la_ventana_minima_el_total_no_queda_tapado(taller):
    """En el portátil del taller (1366×768) la ventana sin maximizar tapaba el
    total con los botones. Se prueba en el mínimo de la ventana, 960×640, en
    otro proceso y con el tema aplicado, que es lo que decide las alturas."""
    import subprocess
    import sys

    from conftest import RAIZ

    script = f"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
app = QApplication([])
from src.ui import tema
tema.aplicar(app)
from src.auth import Sesion
Sesion.iniciar(SimpleNamespace(id={taller.usuario_id}, nombre="QA", rol="ADMINISTRADOR"))
from src.ui import VentanaPrincipal
v = VentanaPrincipal()
v.resize(960, 640)
v.show()
v.pestanias.setCurrentWidget(v.ordenes)
v.ordenes._iniciar_nueva_orden({taller.vehiculo_id})
app.processEvents()
total, boton = v.ordenes.totales.total, v.ordenes.boton_guardar
print(total.mapTo(v, total.rect().bottomLeft()).y(), boton.mapTo(v, boton.rect().topLeft()).y())
"""
    salida = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                            cwd=RAIZ, timeout=60)
    total_abajo, botones_arriba = map(int, salida.stdout.split()[-2:])
    assert total_abajo < botones_arriba, salida.stderr


def test_una_orden_se_deja_abierta_se_retoma_y_se_entrega(app, taller, sin_modales, monkeypatch):
    """El auto se queda en el taller: la orden se guarda abierta, se le agrega
    lo que falte y se entrega después. Lo que ya estaba cargado no se descuenta
    dos veces, y lo que se le saca vuelve a la bodega."""
    from PySide6.QtWidgets import QMessageBox

    from src.ui import ordenes
    from src.ui.ordenes import ROL_DETALLE

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    widget = ordenes.OrdenesWidget()
    widget._iniciar_nueva_orden(taller.vehiculo_id)
    widget.agregar_al_carrito(taller.producto_id, 2)
    widget.spin_kilometraje.setValue(50000)
    widget.guardar_orden("ABIERTA")

    with SessionLocal() as db:
        orden = db.scalar(select(Orden).where(Orden.vehiculo_id == taller.vehiculo_id))
        assert orden.estado == "ABIERTA"
        # El stock ya salió: el mecánico sacó el aceite de la repisa.
        assert db.get(Producto, taller.producto_id).stock_actual == 8
        orden_id = orden.id

    widget.setCurrentIndex(1)
    filas = [widget.tabla_abiertas.item(f, 0).text() for f in range(widget.tabla_abiertas.rowCount())]
    widget.tabla_abiertas.selectRow(filas.index(str(orden_id)))
    assert widget.boton_retomar.isEnabled()
    widget.retomar_orden()

    # Vuelve con su línea, marcada como ya guardada, y en la mesa de trabajo.
    assert widget.currentIndex() == 0
    assert widget.orden_abierta_id == orden_id
    assert widget.tabla_carrito.rowCount() == 1
    assert widget.tabla_carrito.item(0, 0).data(ROL_DETALLE) is not None

    widget.agregar_servicio_al_carrito(taller.servicio_id)
    widget.guardar_orden("ENTREGADA")

    with SessionLocal() as db:
        orden = db.get(Orden, orden_id)
        assert orden.estado == "ENTREGADA"
        # La línea vieja no se duplicó y la nueva entró.
        assert len(orden.detalles) == 2
        # Y el producto se descontó una sola vez en todo el recorrido.
        assert db.get(Producto, taller.producto_id).stock_actual == 8


def test_el_flyer_descuenta_aceite_y_filtros_y_sirve_una_vez(app, taller, sin_modales, monkeypatch):
    """Flyer 10 % y gremio 15 %, solo sobre los productos de su convenio: el
    servicio va incluido en el precio del bidón y no se descuenta. El flyer
    viene foliado del 0001 al 1000 y cada papel se usa una vez."""
    from PySide6.QtWidgets import QMessageBox

    from src.ui import ordenes

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    with SessionLocal() as db:
        db.get(Producto, taller.producto_id).categoria = "Aceite motor"
        db.commit()
        usados = set(db.scalars(select(Orden.folio_flyer).where(Orden.folio_flyer.isnot(None))))
    folio = max(set(range(1, 1001)) - usados)

    widget = ordenes.OrdenesWidget()
    widget._iniciar_nueva_orden(taller.vehiculo_id)
    widget.agregar_al_carrito(taller.producto_id, 1)          # 12.900, entra
    widget.agregar_servicio_al_carrito(taller.servicio_id)    # 15.000, no entra
    widget.spin_kilometraje.setValue(50000)
    widget.tipo_descuento.setCurrentIndex(TIPOS_DESCUENTO.index("Flyer (10 %)"))
    assert widget.totales.descuento.text() == "- $1.290"

    widget.guardar_orden("ABIERTA")
    assert sin_modales[-1] == "Falta el folio del flyer"
    widget.valor_descuento.setValue(folio)

    # Sin nada que descontar, el folio no se gasta.
    fila_aceite = next(f for f in range(widget.tabla_carrito.rowCount())
                       if "producto_id" in widget.tabla_carrito.item(f, 0).data(Qt.UserRole))
    widget.tabla_carrito.selectRow(fila_aceite)
    widget.quitar_del_carrito()
    widget.guardar_orden("ABIERTA")
    assert sin_modales[-1] == "El flyer no descuenta nada"
    widget.agregar_al_carrito(taller.producto_id, 1)
    widget.guardar_orden("ABIERTA")

    with SessionLocal() as db:
        orden = db.scalar(select(Orden).where(Orden.vehiculo_id == taller.vehiculo_id))
        assert (orden.convenio, orden.folio_flyer) == ("FLYER", folio)
        assert orden.descuento_aplicado == 1290
        orden_id = orden.id

    # Retomada, vuelve con su flyer, y el descuento sigue a las líneas nuevas.
    widget.setCurrentIndex(1)
    filas = [widget.tabla_abiertas.item(f, 0).text() for f in range(widget.tabla_abiertas.rowCount())]
    widget.tabla_abiertas.selectRow(filas.index(str(orden_id)))
    widget.retomar_orden()
    assert widget.valor_descuento.value() == folio
    widget.agregar_al_carrito(taller.producto_id, 1)
    assert widget.totales.descuento.text() == "- $2.580"
    widget.guardar_orden("ENTREGADA")
    with SessionLocal() as db:
        assert db.get(Orden, orden_id).descuento_aplicado == 2580

    # El mismo papel no sirve para otra orden.
    widget._iniciar_nueva_orden(taller.vehiculo_id)
    widget.agregar_al_carrito(taller.producto_id, 1)
    widget.spin_kilometraje.setValue(60000)
    widget.tipo_descuento.setCurrentIndex(TIPOS_DESCUENTO.index("Flyer (10 %)"))
    widget.valor_descuento.setValue(folio)
    widget.guardar_orden()
    assert sin_modales[-1] == "Flyer ya usado"

    widget.tipo_descuento.setCurrentIndex(TIPOS_DESCUENTO.index("Gremio/Sindicato (15 %)"))
    assert not widget.valor_descuento.isEnabled()
    assert widget.totales.descuento.text() == "- $1.935"
    widget.guardar_orden()
    with SessionLocal() as db:
        gremio = db.scalar(select(Orden).where(Orden.vehiculo_id == taller.vehiculo_id,
                                               Orden.id != orden_id))
        assert (gremio.convenio, gremio.folio_flyer) == ("GREMIO", None)
        assert gremio.descuento_aplicado == 1935


def test_anular_una_orden_abierta_devuelve_todo_a_la_bodega(app, taller, sin_modales, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from src.ui import ordenes

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    widget = ordenes.OrdenesWidget()
    widget._iniciar_nueva_orden(taller.vehiculo_id)
    widget.agregar_al_carrito(taller.producto_id, 3)
    widget.spin_kilometraje.setValue(50000)
    widget.guardar_orden("ABIERTA")

    with SessionLocal() as db:
        orden_id = db.scalar(select(Orden).where(Orden.vehiculo_id == taller.vehiculo_id)).id
        assert db.get(Producto, taller.producto_id).stock_actual == 7

    widget.setCurrentIndex(1)
    filas = [widget.tabla_abiertas.item(f, 0).text() for f in range(widget.tabla_abiertas.rowCount())]
    widget.tabla_abiertas.selectRow(filas.index(str(orden_id)))
    widget.anular_orden_abierta()

    with SessionLocal() as db:
        orden = db.get(Orden, orden_id)
        assert (orden.estado, len(orden.detalles)) == ("ANULADA", 0)
        assert db.get(Producto, taller.producto_id).stock_actual == 10
        # Con su rastro: el Kardex dice de qué orden volvió.
        devolucion = db.query(KardexMovimiento).filter_by(
            orden_id=orden_id, tipo_movimiento="DEVOLUCION_ORDEN").one()
        assert devolucion.cantidad_movida == 3
