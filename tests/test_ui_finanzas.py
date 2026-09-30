"""Pestaña Finanzas, sin pantalla.

Los widgets escriben con su propia SessionLocal(), así que los datos de apoyo se
crean con commits reales y se limpian al final, como en test_ui_ordenes.py. Los
diálogos son modales: se reemplaza su `exec` por una respuesta.
"""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from conftest import patente_de_prueba, rut_de_prueba
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox
from sqlalchemy import select

from src import permisos
from src.auth import Sesion
from src.database import SessionLocal
from src.models import (
    Cliente, CuentaPorCobrar, FacturaProveedor, Orden, PagoCobro, PagoProveedor, Proveedor,
    Usuario, Vehiculo,
)
from src.ui import finanzas as ui

CLIENTE = "QA Finanzas Organismo"
PROVEEDOR = "QA Finanzas Proveedor"
MANUAL = "QA Finanzas Cuenta Antigua"


@pytest.fixture
def limpiar():
    yield
    with SessionLocal() as db:
        for cuenta in db.scalars(select(CuentaPorCobrar).where(
                CuentaPorCobrar.cliente_nombre == MANUAL)):
            db.query(PagoCobro).filter_by(cuenta_id=cuenta.id).delete()
            db.delete(cuenta)
        cliente = db.scalar(select(Cliente).where(Cliente.nombre_completo == CLIENTE))
        if cliente:
            for vehiculo in db.scalars(select(Vehiculo).where(Vehiculo.cliente_id == cliente.id)):
                for orden in db.scalars(select(Orden).where(Orden.vehiculo_id == vehiculo.id)):
                    for cuenta in db.scalars(select(CuentaPorCobrar).where(
                            CuentaPorCobrar.orden_id == orden.id)):
                        db.query(PagoCobro).filter_by(cuenta_id=cuenta.id).delete()
                        db.delete(cuenta)
                    db.flush()
                    db.delete(orden)
                db.delete(vehiculo)
            db.delete(cliente)
        for proveedor in db.scalars(select(Proveedor).where(Proveedor.nombre.like(f"{PROVEEDOR}%"))):
            for factura in db.scalars(select(FacturaProveedor).where(
                    FacturaProveedor.proveedor_id == proveedor.id)):
                db.query(PagoProveedor).filter_by(factura_id=factura.id).delete()
                db.delete(factura)
            db.delete(proveedor)
        for usuario in db.scalars(select(Usuario).where(Usuario.username.like("qa_fin_%"))):
            db.delete(usuario)
        db.commit()


@pytest.fixture
def taller(limpiar):
    """Un supervisor con sesión y una orden de Mercado Público entregada, que la
    base convirtió sola en una cuenta por facturar."""
    with SessionLocal() as db:
        usuario = Usuario(nombre="Super QA", username=f"qa_fin_{rut_de_prueba()}",
                          password_hash="x", rol="SUPERVISOR")
        vehiculo = Vehiculo(cliente=Cliente(rut=rut_de_prueba(), nombre_completo=CLIENTE),
                            patente=patente_de_prueba())
        db.add_all([usuario, vehiculo])
        db.flush()
        orden = Orden(vehiculo=vehiculo, usuario=usuario, kilometraje_ingreso=1,
                      folio_mercado_publico="QA-MP-1", subtotal=100000, impuesto=19000,
                      total_final=119000)
        db.add(orden)
        db.commit()
        cuenta = db.scalar(select(CuentaPorCobrar).where(CuentaPorCobrar.orden_id == orden.id))
        datos = SimpleNamespace(usuario_id=usuario.id, cuenta_id=cuenta.id, orden_id=orden.id)
    _como("SUPERVISOR", datos)
    yield datos
    Sesion.cerrar()


def _como(rol: str, datos) -> None:
    Sesion.iniciar(SimpleNamespace(id=datos.usuario_id, nombre="QA", rol=rol))


@pytest.fixture
def sin_modales(monkeypatch):
    titulos = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: titulos.append(a[1]))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    return titulos


def responder(monkeypatch, dialogo, llenar):
    """El diálogo se cierra aceptado, con lo que `llenar(dialogo)` le ponga."""
    def exec_(self):
        llenar(self)
        return QDialog.Accepted
    monkeypatch.setattr(dialogo, "exec", exec_)


def elegir(widget, cuenta_id: int):
    """Selecciona la fila de esa cuenta y devuelve su fila."""
    for fila in range(widget.tabla.rowCount()):
        if widget.tabla.item(fila, 0).data(Qt.UserRole) == cuenta_id:
            widget.tabla.selectRow(fila)
            return fila
    raise AssertionError(f"la cuenta {cuenta_id} no está en el listado")


def texto(widget, fila: int, columna: str) -> str:
    return widget.tabla.item(fila, ui.COLUMNAS_COBRO.index(columna)).text()


def test_una_orden_de_mercado_publico_se_factura_se_abona_y_se_paga(app, taller, sin_modales, monkeypatch):
    widget = ui.PorCobrarWidget()
    fila = elegir(widget, taller.cuenta_id)
    assert texto(widget, fila, "Estado") == "Por facturar"
    assert texto(widget, fila, "OC") == "QA-MP-1"
    assert widget.tabla.item(fila, ui.COLUMNAS_COBRO.index("Saldo")).toolTip() == \
        "Total con IVA estimado $119.000"
    assert texto(widget, fila, "Neto") == "$100.000"
    assert widget.boton_factura.isEnabled() and not widget.boton_abono.isEnabled()

    responder(monkeypatch, ui.DialogoFactura, lambda d: (
        d.numero.setText(" 4521 "), d.fecha.setDate(d.fecha.date().addDays(-3))))
    widget.registrar_factura()
    assert sin_modales == []

    fila = elegir(widget, taller.cuenta_id)
    assert texto(widget, fila, "Estado") == "Por cobrar"
    assert texto(widget, fila, "Factura") == "4521"
    assert texto(widget, fila, "Saldo") == "$119.000"
    assert widget.boton_abono.isEnabled() and not widget.boton_factura.isEnabled()

    responder(monkeypatch, ui.DialogoAbono, lambda d: d.monto.setValue(19000))
    widget.registrar_abono()
    fila = elegir(widget, taller.cuenta_id)
    assert texto(widget, fila, "Saldo") == "$100.000"
    assert widget.tabla.item(fila, ui.COLUMNAS_COBRO.index("Saldo")).toolTip() == \
        "Total con IVA $119.000 · pagado $19.000"

    responder(monkeypatch, ui.DialogoAbono, lambda d: None)     # propone el saldo entero
    widget.registrar_abono()
    with SessionLocal() as db:
        assert db.get(CuentaPorCobrar, taller.cuenta_id).estado == "PAGADA"
    assert widget.cifras.texto("por_cobrar") is not None
    assert sin_modales == []


def test_el_filtro_de_morosas_y_la_busqueda(app, taller, sin_modales, monkeypatch):
    with SessionLocal() as db:
        cuenta = db.get(CuentaPorCobrar, taller.cuenta_id)
        cuenta.estado = "POR_COBRAR"
        cuenta.numero_factura, cuenta.venta_neto, cuenta.iva = "77", 100000, 19000
        cuenta.fecha_factura = date.today() - timedelta(days=45)
        cuenta.usuario_id = taller.usuario_id
        db.commit()

    widget = ui.PorCobrarWidget()
    fila = elegir(widget, taller.cuenta_id)
    assert texto(widget, fila, "Estado") == "Morosa · 15 d"

    widget.filtro.setCurrentText("Pagadas")
    assert widget.tabla.rowCount() == 0 or all(
        texto(widget, f, "Cliente") != CLIENTE for f in range(widget.tabla.rowCount()))
    widget.filtro.setCurrentText("Morosas")
    widget.busqueda.setText("organismo qa finanzas")       # sin mayúsculas, palabras sueltas
    assert widget.tabla.rowCount() == 1
    widget.busqueda.setText("no existe")
    assert widget.tabla.rowCount() == 0


def test_una_cuenta_anterior_se_ingresa_con_o_sin_costo_y_se_anula(app, taller, sin_modales, monkeypatch):
    widget = ui.PorCobrarWidget()

    def llenar(d):
        d.cliente.setText(MANUAL)
        d.factura.setText("9001")
        d.neto.setValue(200000)
        assert d.total.text() == "$238.000"
    responder(monkeypatch, ui.DialogoCuentaAnterior, llenar)
    widget.ingresar_anterior()
    assert sin_modales == []

    with SessionLocal() as db:
        cuenta = db.scalar(select(CuentaPorCobrar).where(CuentaPorCobrar.cliente_nombre == MANUAL))
        assert (cuenta.estado, cuenta.costo, cuenta.monto) == ("POR_COBRAR", None, 238000)
        cuenta_id = cuenta.id
    fila = elegir(widget, cuenta_id)
    assert texto(widget, fila, "Costo") == "—"           # sin dato, no cero
    assert widget.boton_anular.isEnabled()

    widget.anular()
    with SessionLocal() as db:
        assert db.get(CuentaPorCobrar, cuenta_id).estado == "ANULADA"


def test_el_supervisor_ve_el_costo_pero_no_el_margen(app, taller):
    supervisor = ui.PorCobrarWidget()
    assert supervisor.tabla.isColumnHidden(ui.COLUMNAS_COBRO.index("Margen"))
    assert not supervisor.tabla.isColumnHidden(ui.COLUMNAS_COBRO.index("Costo"))
    assert supervisor.cifras._bloques["margen_mes"].isHidden()

    _como("ADMINISTRADOR", taller)
    dueno = ui.PorCobrarWidget()
    assert not dueno.tabla.isColumnHidden(ui.COLUMNAS_COBRO.index("Margen"))
    assert not dueno.cifras._bloques["margen_mes"].isHidden()
    # Margen = neto − costo. Con la ventana ancha (maximizada) se ven las dos
    # columnas; a 960 px, con las dos, el cliente quedaba en 73 px, así que el
    # costo se apaga y pasa al tooltip del margen.
    costo = ui.COLUMNAS_COBRO.index("Costo")
    dueno.resize(1366, 700)
    dueno._ajustar_columnas()
    assert not dueno.tabla.isColumnHidden(costo)
    dueno.resize(960, 700)
    dueno._ajustar_columnas()
    assert dueno.tabla.isColumnHidden(costo)
    fila = elegir(dueno, taller.cuenta_id)
    assert dueno.tabla.item(fila, ui.COLUMNAS_COBRO.index("Margen")).toolTip() == "Costo $0"

    # El supervisor ve el costo a cualquier ancho.
    _como("SUPERVISOR", taller)
    supervisor = ui.PorCobrarWidget()
    supervisor.resize(960, 700)
    supervisor._ajustar_columnas()
    assert not supervisor.tabla.isColumnHidden(costo)


def test_un_usuario_normal_no_opera_finanzas(app, taller, sin_modales):
    assert permisos.PERMISOS["finanzas"] == {"SUPERVISOR", "ADMINISTRADOR"}
    _como("USUARIO_NORMAL", taller)
    widget = ui.PorCobrarWidget()
    elegir(widget, taller.cuenta_id)
    widget.registrar_factura()
    widget.ingresar_anterior()
    assert sin_modales == ["Acción reservada", "Acción reservada"]


def test_una_factura_de_proveedor_se_ingresa_vence_y_se_paga(app, taller, sin_modales, monkeypatch):
    with SessionLocal() as db:
        proveedor = Proveedor(nombre=PROVEEDOR, plazo_credito_dias=20)
        db.add(proveedor)
        db.commit()
        proveedor_id = proveedor.id

    widget = ui.PorPagarWidget()

    def llenar(d):
        d.proveedor.setCurrentIndex(d.proveedor.findData(proveedor_id))
        assert d.vence.date().toPython() == d.compra.date().toPython() + timedelta(days=20)
        d.numero.setText("F-77")
        d.monto.setValue(300000)
        d.compra.setDate(d.compra.date().addDays(-40))     # ya venció hace 20 días
    responder(monkeypatch, ui.DialogoFacturaProveedor, llenar)
    widget.nueva_factura()
    assert sin_modales == []

    with SessionLocal() as db:
        factura_id = db.scalar(select(FacturaProveedor.id).where(
            FacturaProveedor.proveedor_id == proveedor_id))
    fila = next(f for f in range(widget.tabla.rowCount())
                if widget.tabla.item(f, 0).data(Qt.UserRole) == factura_id)
    widget.tabla.selectRow(fila)
    assert widget.tabla.item(fila, 0).text() == "Vencida"
    assert widget.tabla.item(fila, ui.COLUMNAS_PAGAR.index("Mora")).text() == "20 d"
    assert widget.cifras.texto("vencido") != "$0"

    responder(monkeypatch, ui.DialogoAbono, lambda d: d.monto.setValue(100000))
    widget.registrar_pago()
    responder(monkeypatch, ui.DialogoAbono, lambda d: None)
    widget.tabla.selectRow(next(f for f in range(widget.tabla.rowCount())
                                if widget.tabla.item(f, 0).data(Qt.UserRole) == factura_id))
    widget.registrar_pago()
    with SessionLocal() as db:
        factura = db.get(FacturaProveedor, factura_id)
        assert (factura.estado, factura.pagado) == ("PAGADA", 300000)


def test_un_proveedor_nuevo_se_crea_desde_el_dialogo_de_la_factura(app, taller, sin_modales, monkeypatch):
    dialogo = ui.DialogoFacturaProveedor()

    def llenar(d):
        d.nombre.setText(f"{PROVEEDOR} nuevo")
        d.plazo.setValue(60)
    responder(monkeypatch, ui.DialogoProveedor, llenar)
    dialogo.nuevo_proveedor()
    assert dialogo.proveedor.currentText() == f"{PROVEEDOR} nuevo"
    assert dialogo.vence.date().toPython() == dialogo.compra.date().toPython() + timedelta(days=60)
