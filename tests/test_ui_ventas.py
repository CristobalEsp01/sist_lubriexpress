"""Interfaz del módulo de Ventas de Mostrador, sin pantalla.

PuntoVentaWidget escribe con su propia SessionLocal() en cada operación (no con
el fixture `db`, que revierte todo al terminar), así que los datos de apoyo
se crean con commits reales y se limpian explícitamente al final — igual que
en test_ui_inventario.py.
"""
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from conftest import rut_de_prueba
from src.auth import Sesion
from src.database import SessionLocal
from src.models import Cliente, DetalleVenta, KardexMovimiento, Producto, Usuario, Venta

NOMBRE_PRODUCTO = "QA Filtro de aceite"
NOMBRE_CLIENTE = "QA Cliente de mostrador"


@pytest.fixture
def limpiar():
    yield
    with SessionLocal() as db:
        producto = db.scalar(select(Producto).where(Producto.nombre == NOMBRE_PRODUCTO))
        if producto:
            db.query(KardexMovimiento).filter(KardexMovimiento.producto_id == producto.id).delete()
            db.query(DetalleVenta).filter(DetalleVenta.producto_id == producto.id).delete()
        for venta in db.scalars(select(Venta).where(Venta.numero_boleta.like("QA-%"))):
            db.query(DetalleVenta).filter(DetalleVenta.venta_id == venta.id).delete()
            db.query(KardexMovimiento).filter(KardexMovimiento.venta_id == venta.id).delete()
            db.delete(venta)
        if producto:
            db.delete(producto)
        for cliente in db.scalars(
            select(Cliente).where(Cliente.nombre_completo == NOMBRE_CLIENTE)
        ):
            db.delete(cliente)
        for usuario in db.scalars(select(Usuario).where(Usuario.username.like("qa_cajera_%"))):
            db.delete(usuario)
        db.commit()


@pytest.fixture
def usuario_qa(limpiar):
    """Deja una sesión iniciada con un usuario real y comiteado, como la
    dejaría LoginDialog. Se cierra sola al terminar la prueba."""
    with SessionLocal() as db:
        usuario = Usuario(
            nombre="Cajera QA", username=f"qa_cajera_{rut_de_prueba()}",
            password_hash="hash-de-prueba", rol="USUARIO_NORMAL",
        )
        db.add(usuario)
        db.commit()
        usuario_id, nombre, rol = usuario.id, usuario.nombre, usuario.rol

    Sesion.iniciar(SimpleNamespace(id=usuario_id, nombre=nombre, rol=rol))
    yield usuario_id
    Sesion.cerrar()


@pytest.fixture
def producto_qa(limpiar):
    with SessionLocal() as db:
        producto = Producto(
            nombre=NOMBRE_PRODUCTO, precio_costo=3000, precio_venta=6000,
            stock_actual=10, stock_minimo=2,
        )
        db.add(producto)
        db.commit()
        producto_id = producto.id
    yield producto_id


@pytest.fixture
def sin_modales(monkeypatch):
    """Los avisos son QMessageBox reales: sin silenciarlos, el modal nunca se
    cierra solo y la prueba queda colgada. Devuelve los títulos mostrados."""
    from PySide6.QtWidgets import QMessageBox

    titulos = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: titulos.append(a[1]))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    return titulos


def test_el_carrito_se_llena_por_teclado_y_no_pasa_del_stock(app, producto_qa, sin_modales):
    from src.ui.ventas import PuntoVentaWidget

    widget = PuntoVentaWidget()

    # Escribir hasta que quede un producto y apretar Enter es el camino más
    # corto para quien cobra sin soltar el teclado.
    widget.busqueda.setText(NOMBRE_PRODUCTO)
    assert len(widget.catalogo.visibles()) == 1
    widget.busqueda.returnPressed.emit()
    assert [e["producto_id"] for e in widget.carrito] == [producto_qa]

    widget.agregar_producto(producto_qa, cantidad=20)  # se pasa del stock (10)
    assert len(widget.carrito) == 1
    assert widget.carrito[0]["cantidad"] == 10  # se topa en el máximo disponible

    with SessionLocal() as db:
        db.get(Producto, producto_qa).stock_actual = 0
        db.commit()

    otro = PuntoVentaWidget()
    otro.agregar_producto(producto_qa)
    assert otro.carrito == []


def test_el_cobro_exige_boleta_registra_la_venta_y_no_la_duplica(
    app, usuario_qa, producto_qa, sin_modales
):
    from src.ui.ventas import PuntoVentaWidget

    widget = PuntoVentaWidget()
    # El campo de cliente nace vacío: la venta de mostrador sin cliente es el
    # caso normal y no ocupa el campo con una opción que parezca alguien.
    assert widget.cliente.currentText() == ""
    assert widget.cliente.currentData() is None

    widget.agregar_producto(producto_qa, cantidad=3)

    widget.boleta.clear()
    assert not widget.boton_cobrar.isEnabled()  # el botón lo dice apagándose
    widget.generar_venta()  # y si igual se llama, avisa y no guarda
    assert sin_modales == ["Falta la boleta"]

    widget.boleta.setText("QA-0001")
    # El medio de pago nace sin elegir: la caja cuenta como plata del cajón
    # lo que se cobra en efectivo, y un "Efectivo" por defecto convertía una
    # venta con tarjeta en plata que el cajón no tiene.
    assert widget.combo_medio_pago.currentIndex() == -1
    assert not widget.boton_cobrar.isEnabled()
    widget.generar_venta()
    assert sin_modales[-1] == "Falta el medio de pago"
    widget.combo_medio_pago.setCurrentText("Tarjeta")
    assert widget.boton_cobrar.isEnabled()
    widget.generar_venta()

    with SessionLocal() as db:
        venta = db.scalar(select(Venta).where(Venta.numero_boleta == "QA-0001"))
        assert venta.usuario_id == usuario_qa
        assert venta.cliente_id is None  # se cobró sin cliente, como se pidió
        assert (int(venta.impuesto), int(venta.total_final)) == (3420, 21420)  # 18.000 + 19 %
        assert venta.medio_pago == "TARJETA"

        detalle = db.scalars(select(DetalleVenta).where(DetalleVenta.venta_id == venta.id)).all()
        assert len(detalle) == 1 and detalle[0].cantidad == 3

        assert db.get(Producto, producto_qa).stock_actual == 7  # 10 - 3

        mov = db.scalar(select(KardexMovimiento).where(KardexMovimiento.venta_id == venta.id))
        assert (mov.tipo_movimiento, mov.cantidad_movida, mov.stock_resultante) == (
            "SALIDA_VENTA", -3, 7
        )
        assert mov.usuario_id == usuario_qa

    # Queda listo para la siguiente: carrito vacío, la boleta ya sugerida y el
    # medio otra vez sin elegir.
    assert widget.carrito == []
    assert widget.boleta.text() == "QA-0002"
    assert widget.combo_medio_pago.currentIndex() == -1

    # Repetir el número no puede duplicar la venta: lo ataja el UNIQUE.
    repetida = PuntoVentaWidget()
    repetida.agregar_producto(producto_qa, cantidad=1)
    repetida.boleta.setText("QA-0001")
    repetida.combo_medio_pago.setCurrentText("Efectivo")
    repetida.generar_venta()

    with SessionLocal() as db:
        ventas = db.scalars(select(Venta).where(Venta.numero_boleta == "QA-0001")).all()
        assert len(ventas) == 1
    assert sin_modales[-1] == "Boleta repetida"


@pytest.mark.parametrize("ultima, esperada", [
    ("B-1042", "B-1043"),      # conserva el prefijo del talonario
    ("000123", "000124"),      # y los ceros a la izquierda
    ("B-999", "B-1000"),       # crece de largo cuando toca
    ("12345", "12346"),
    ("SIN NUMERO", ""),        # no hay de dónde deducirlo: se deja en blanco
    (None, ""),                # primera venta del sistema
])
def test_siguiente_boleta(ultima, esperada):
    from src.ui.ventas import siguiente_boleta

    assert siguiente_boleta(ultima) == esperada


def test_el_historial_ordena_por_la_fecha_real_y_no_por_su_texto(app, usuario_qa):
    """Regresión: la fecha se mostraba en un QTableWidgetItem con el texto
    "%d-%m-%Y %H:%M", así que la tabla ordenaba por el día del mes."""
    from src.ui.ventas import HistorialVentasWidget

    # Dos fechas cuyo orden cronológico es el contrario al de su texto:
    # como cadena, "31-01-2026" queda después de "01-02-2026".
    with SessionLocal() as db:
        db.add_all([
            Venta(usuario_id=usuario_qa, numero_boleta="QA-ENERO", total_final=1000,
                  fecha_venta=datetime(2026, 1, 31, 18, 0)),
            Venta(usuario_id=usuario_qa, numero_boleta="QA-FEBRERO", total_final=2000,
                  fecha_venta=datetime(2026, 2, 1, 9, 0)),
        ])
        db.commit()

    widget = HistorialVentasWidget()
    widget.cargar_ventas()

    filas = {widget.tabla.item(f, 1).text(): f for f in range(widget.tabla.rowCount())}
    assert filas["QA-FEBRERO"] < filas["QA-ENERO"]  # la más reciente arriba


def test_al_cliente_recien_creado_se_llega_tecleando_su_rut(app, limpiar):
    """El caso que motivó la pasada de UX: se registra un cliente en su
    mantenedor, se vuelve a la venta y se lo ubica escribiendo el RUT sin
    puntos, en vez de recorrer el desplegable a ojo."""
    from src.ui.ventas import PuntoVentaWidget

    rut = rut_de_prueba()
    widget = PuntoVentaWidget()

    with SessionLocal() as db:
        db.add(Cliente(rut=rut, nombre_completo=NOMBRE_CLIENTE))
        db.commit()

    widget.show()  # showEvent recarga el combo

    filtro = widget.cliente.completer().model()
    filtro.filtrar(rut.replace(".", "").replace("-", ""))
    sugeridos = [filtro.index(f, 0).data() for f in range(filtro.rowCount())]

    assert sugeridos == [f"{rut} — {NOMBRE_CLIENTE}"]


def test_no_se_cobra_un_producto_desactivado_despues_de_agregarlo(
    app, usuario_qa, producto_qa, sin_modales
):
    """Agregar ya revisaba que el producto estuviera activo; cobrar no.

    Un producto dado de baja en Inventario mientras el carrito estaba armado se
    vendía igual, y el Kardex quedaba con una salida de algo que el catálogo ya
    no ofrece. La revalidación previa al cobro ahora mira las dos cosas.
    """
    from src.ui.ventas import PuntoVentaWidget

    widget = PuntoVentaWidget()
    widget.agregar_producto(producto_qa, cantidad=2)
    widget.boleta.setText("QA-0009")
    widget.combo_medio_pago.setCurrentText("Efectivo")

    with SessionLocal() as db:
        db.get(Producto, producto_qa).activo = False
        db.commit()

    widget.generar_venta()

    assert sin_modales[-1] == "Producto no disponible"
    with SessionLocal() as db:
        assert db.scalar(select(Venta).where(Venta.numero_boleta == "QA-0009")) is None
        assert db.get(Producto, producto_qa).stock_actual == 10  # intacto


def test_la_venta_guarda_el_descuento_y_el_total_lo_refleja(app, usuario_qa, producto_qa,
                                                            sin_modales):
    from src.ui.ventas import DetalleVentaDialog, PuntoVentaWidget

    widget = PuntoVentaWidget()
    widget.agregar_producto(producto_qa, cantidad=2)              # 12.000 neto
    assert not widget.valor_descuento.isEnabled()                 # sin descuento, apagado
    widget.tipo_descuento.setCurrentIndex(1)                      # porcentaje
    widget.valor_descuento.setValue(10)
    assert widget.totales.descuento.text() == "- $1.200"
    assert widget.total.text() == "$12.850"                       # 10.800 + 2.052 = 12.852

    widget.boleta.setText("QA-0100")
    widget.combo_medio_pago.setCurrentText("Efectivo")
    widget.generar_venta()

    with SessionLocal() as db:
        venta = db.scalar(select(Venta).where(Venta.numero_boleta == "QA-0100"))
        assert (int(venta.subtotal), int(venta.descuento_porcentaje), int(venta.descuento_monto),
                int(venta.impuesto), int(venta.ajuste_redondeo), int(venta.total_final)
                ) == (12000, 10, 0, 2052, -2, 12850)
        venta_id = venta.id
    assert widget.tipo_descuento.currentIndex() == 0              # la siguiente parte sin descuento

    detalle = DetalleVentaDialog(venta_id, "QA-0100")
    assert detalle.totales.neto.text() == "$12.000"
    assert detalle.totales.descuento.text() == "- $1.200"


def test_quitar_productos_topa_el_monto_al_nuevo_neto(app, usuario_qa, producto_qa, sin_modales,
                                                      monkeypatch):
    """Un monto fijado con dos unidades no puede quedar mayor que la venta
    cuando se baja a una: se ajusta y se avisa."""
    from PySide6.QtWidgets import QInputDialog

    from src.ui.ventas import PuntoVentaWidget

    widget = PuntoVentaWidget()
    widget.agregar_producto(producto_qa, cantidad=2)              # 12.000 neto
    widget.tipo_descuento.setCurrentIndex(2)                      # monto
    widget.valor_descuento.setValue(10000)
    assert widget.total.text() == "$2.380"
    assert widget.aviso_descuento.isHidden()

    widget.tabla_carrito.selectRow(0)
    monkeypatch.setattr(QInputDialog, "getInt", staticmethod(lambda *a, **k: (1, True)))
    widget.cambiar_cantidad()                                     # 6.000 neto

    assert widget.valor_descuento.value() == 6000
    assert not widget.aviso_descuento.isHidden()
    assert widget.total.text() == "$0"


def test_el_descuento_cabe_en_la_ventana_minima(app, usuario_qa):
    """Con el selector de descuento, el carrito tiene que seguir mostrando
    filas y el total entero a 960×640."""
    from src.ui import VentanaPrincipal

    ventana = VentanaPrincipal()
    ventana.resize(ventana.minimumSize())
    ventana.show()
    ventana.pestanias.setCurrentWidget(ventana.ventas)
    punto = ventana.ventas.punto_venta
    app.processEvents()

    cifra = punto.totales.total
    assert cifra.height() >= cifra.sizeHint().height()
    tabla = punto.tabla_carrito
    assert tabla.viewport().height() >= 3 * tabla.verticalHeader().defaultSectionSize()
    ventana.close()


def test_ver_foto_solo_se_enciende_con_un_producto_con_foto(app, usuario_qa, producto_qa,
                                                            monkeypatch):
    """En el mesón la foto se revisa a pedido: al pasar el mouse o con "Ver
    foto". Sin foto el botón se apaga, en vez de abrir un recuadro vacío."""
    from PySide6.QtGui import QImage

    from src.fotos import guardar, preparar
    from src.ui import catalogo as modulo
    from src.ui.ventas import PuntoVentaWidget

    widget = PuntoVentaWidget()
    catalogo = widget.catalogo

    def fila_del_producto() -> int:
        catalogo.busqueda.setText(NOMBRE_PRODUCTO)
        fila, = catalogo.visibles()
        catalogo.tabla.selectRow(fila)
        return fila

    fila = fila_del_producto()
    assert not catalogo.boton_foto.isEnabled()
    assert catalogo._tooltip_foto(fila) is None

    with SessionLocal() as db:
        guardar(db, producto_qa, preparar(QImage(300, 200, QImage.Format_RGB32)))
        db.commit()
    catalogo.cargar()
    fila = fila_del_producto()
    assert catalogo.boton_foto.isEnabled()
    assert "data:image/jpeg;base64," in catalogo._tooltip_foto(fila)

    vistas = []
    monkeypatch.setattr(modulo, "ver_foto", lambda producto_id, parent: vistas.append(producto_id))
    catalogo.boton_foto.click()
    assert vistas == [producto_qa]
