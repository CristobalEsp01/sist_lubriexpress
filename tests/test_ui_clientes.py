"""Interfaz del mantenedor de Clientes y vehículos, sin pantalla."""
import pytest
from sqlalchemy import select

from conftest import patente_de_prueba, rut_de_prueba
from src.database import SessionLocal
from src.models import Cliente, Vehiculo

RUT_QA = rut_de_prueba()
PATENTE_QA = patente_de_prueba()


@pytest.fixture
def limpiar_cliente():
    yield
    with SessionLocal() as db:
        for v in db.scalars(select(Vehiculo).where(Vehiculo.patente == PATENTE_QA)):
            db.delete(v)
        db.commit()
        for c in db.scalars(select(Cliente).where(Cliente.rut == RUT_QA)):
            db.delete(c)
        db.commit()


def test_el_formulario_rechaza_un_rut_con_dv_malo(app, limpiar_cliente, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from src.ui import FormularioCliente

    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: avisos.append(a[1]))

    form = FormularioCliente()
    form.rut.setText(RUT_QA[:-1] + ("0" if RUT_QA[-1] != "0" else "1"))  # dv alterado
    form.nombre.setText("Cliente QA")
    form.accept()

    assert avisos == ["RUT inválido"]
    assert form.cliente_id is None
    with SessionLocal() as db:
        assert db.scalar(select(Cliente).where(Cliente.rut == RUT_QA)) is None


def test_el_rut_se_guarda_siempre_con_el_mismo_formato(app, limpiar_cliente):
    from src.ui import FormularioCliente

    form = FormularioCliente()
    form.rut.setText(RUT_QA.replace(".", "").replace("-", ""))  # sin puntos ni guión
    form.nombre.setText("Cliente QA")
    form.telefono.setText("+56 9 1234 5678")
    form.accept()

    with SessionLocal() as db:
        cliente = db.get(Cliente, form.cliente_id)
        assert cliente.rut == RUT_QA
        assert cliente.tipo_cliente == "PERSONA"


def test_el_vehiculo_queda_colgado_del_cliente_y_se_lista(app, limpiar_cliente):
    from src.ui import ClientesWidget, FormularioCliente, FormularioVehiculo

    cliente = FormularioCliente()
    cliente.rut.setText(RUT_QA)
    cliente.nombre.setText("Cliente QA")
    cliente.accept()

    vehiculo = FormularioVehiculo(cliente_id=cliente.cliente_id)
    vehiculo.patente.setText(f"  {PATENTE_QA[:2].lower()}-{PATENTE_QA[2:]}  ")  # se normaliza
    vehiculo.marca.setText("Toyota")
    vehiculo.modelo.setText("Hilux")
    vehiculo.anio.setValue(2019)
    vehiculo.accept()

    with SessionLocal() as db:
        v = db.get(Vehiculo, vehiculo.vehiculo_id)
        assert v.patente == PATENTE_QA
        assert v.cliente_id == cliente.cliente_id
        assert v.anio_fabricacion == 2019

    widget = ClientesWidget()
    widget.busqueda.setText(RUT_QA)
    assert widget.tabla.rowCount() == 1
    assert widget.tabla.item(0, 4).text() == "1"  # columna Vehículos

    widget.tabla.selectRow(0)
    assert widget.tabla_vehiculos.rowCount() == 1
    assert widget.tabla_vehiculos.item(0, 0).text() == PATENTE_QA
    assert "Cliente QA" in widget.titulo_vehiculos.text()


def test_no_se_puede_repetir_el_rut(app, limpiar_cliente, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from src.ui import FormularioCliente

    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: avisos.append(a[1]))

    primero = FormularioCliente()
    primero.rut.setText(RUT_QA)
    primero.nombre.setText("Cliente QA")
    primero.accept()
    assert primero.cliente_id is not None

    repetido = FormularioCliente()
    repetido.rut.setText(RUT_QA.replace(".", ""))
    repetido.nombre.setText("Otro QA")
    repetido.accept()

    assert avisos == ["RUT repetido"]
    assert repetido.cliente_id is None
