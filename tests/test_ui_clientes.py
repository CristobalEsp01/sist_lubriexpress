"""Interfaz del mantenedor de Clientes y vehículos, sin pantalla."""
import pytest
from sqlalchemy import or_, select

from conftest import patente_de_prueba, rut_de_prueba
from src.database import SessionLocal
from src.models import Cliente, Vehiculo

RUT_QA = rut_de_prueba()
PATENTE_QA = patente_de_prueba()
PATENTE_QA2 = patente_de_prueba()
NOMBRE_QA = "Juan Ignacio Pérez Núñez"
SIN_RUT_QA = f"Cliente sin RUT {PATENTE_QA}"  # los clientes sin RUT se limpian por nombre


@pytest.fixture
def limpiar_cliente():
    yield
    with SessionLocal() as db:
        vehiculos = select(Vehiculo).where(Vehiculo.patente.in_([PATENTE_QA, PATENTE_QA2]))
        for v in db.scalars(vehiculos):
            db.delete(v)
        db.commit()
        consulta = select(Cliente).where(
            or_(Cliente.rut == RUT_QA, Cliente.nombre_completo == SIN_RUT_QA)
        )
        for c in db.scalars(consulta):
            db.delete(c)
        db.commit()


@pytest.fixture
def avisos(monkeypatch):
    """Sin esto, un guardado fallido abre un modal de verdad: bajo
    QT_QPA_PLATFORM=offscreen sigue bloqueando y la suite queda colgada."""
    from PySide6.QtWidgets import QMessageBox

    recogidos = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: recogidos.append(a[1]))
    return recogidos


def test_el_rut_se_valida_segun_el_tipo_de_cliente(app, limpiar_cliente, avisos):
    from src.ui import FormularioCliente

    malo = FormularioCliente()
    malo.rut.setText(RUT_QA[:-1] + ("0" if RUT_QA[-1] != "0" else "1"))  # dv alterado
    malo.nombre.setText(NOMBRE_QA)
    malo.accept()
    assert avisos == ["RUT inválido"]
    assert malo.cliente_id is None

    empresa = FormularioCliente()
    empresa.nombre.setText(SIN_RUT_QA)
    empresa.tipo.setCurrentText("EMPRESA")
    empresa.accept()
    assert avisos == ["RUT inválido", "Falta el RUT"]
    assert empresa.cliente_id is None
    assert empresa.etiqueta_rut.text() == "RUT *"  # el asterisco aparece con el tipo

    # Una persona sí puede quedar sin RUT, y guardado como NULL: con cadena
    # vacía, dos clientes sin RUT chocarían contra el UNIQUE.
    persona = FormularioCliente()
    persona.nombre.setText(SIN_RUT_QA)
    persona.accept()
    assert avisos == ["RUT inválido", "Falta el RUT"]  # ninguno nuevo
    with SessionLocal() as db:
        assert db.get(Cliente, persona.cliente_id).rut is None


def test_el_rut_se_guarda_con_formato_unico_y_no_se_repite(app, limpiar_cliente, avisos):
    from src.ui import FormularioCliente

    primero = FormularioCliente()
    primero.rut.setText(RUT_QA.replace(".", "").replace("-", ""))  # sin puntos ni guión
    primero.nombre.setText(NOMBRE_QA)
    primero.telefono.setText("+56 9 1234 5678")
    primero.accept()

    with SessionLocal() as db:
        cliente = db.get(Cliente, primero.cliente_id)
        assert cliente.rut == RUT_QA  # normalizado al guardar
        assert cliente.tipo_cliente == "PERSONA"

    repetido = FormularioCliente()
    repetido.rut.setText(RUT_QA.replace(".", ""))
    repetido.nombre.setText("Otro QA")
    repetido.accept()

    assert avisos == ["RUT repetido"]
    assert repetido.cliente_id is None


def test_el_vehiculo_cuelga_del_cliente_y_los_botones_siguen_la_seleccion(app, limpiar_cliente):
    from src.ui import ClientesWidget, FormularioCliente, FormularioVehiculo

    cliente = FormularioCliente()
    cliente.rut.setText(RUT_QA)
    cliente.nombre.setText(NOMBRE_QA)
    cliente.accept()

    vehiculo = FormularioVehiculo(cliente_id=cliente.cliente_id)
    vehiculo.patente.setText(f"  {PATENTE_QA[:2].lower()}-{PATENTE_QA[2:]}  ")  # se normaliza
    vehiculo.marca.setText("Toyota")
    vehiculo.anio.setValue(2019)
    vehiculo.accept()

    with SessionLocal() as db:
        v = db.get(Vehiculo, vehiculo.vehiculo_id)
        assert (v.patente, v.cliente_id, v.anio_fabricacion) == (
            PATENTE_QA, cliente.cliente_id, 2019
        )

    widget = ClientesWidget()
    widget.busqueda.setText(RUT_QA)
    assert widget.tabla.rowCount() == 1
    assert widget.tabla.item(0, 4).text() == "1"  # columna Vehículos
    # Sin fila elegida los botones se apagan, en vez de dejarse apretar para
    # responder con un cartel.
    assert not widget.boton_editar.isEnabled()
    assert not widget.boton_editar_vehiculo.isEnabled()

    widget.tabla.selectRow(0)
    assert widget.boton_editar.isEnabled()
    assert widget.tabla_vehiculos.rowCount() == 1
    assert widget.tabla_vehiculos.item(0, 0).text() == PATENTE_QA
    assert NOMBRE_QA in widget.titulo_vehiculos.text()

    widget.tabla_vehiculos.selectRow(0)
    assert widget.boton_editar_vehiculo.isEnabled()


@pytest.mark.parametrize("tecleado, encuentra", [
    (PATENTE_QA, True),                                 # patente tal cual
    (PATENTE_QA.lower(), True),                         # en minúscula
    (f"{PATENTE_QA[:2]}-{PATENTE_QA[2:]}", True),       # con guión
    (RUT_QA, True),                                     # RUT formateado
    (RUT_QA.replace(".", "").replace("-", ""), True),   # RUT pelado
    ("perez", True),                                    # sin tilde
    ("PÉREZ", True),                                    # con tilde y en mayúscula
    ("nunez", True),                                    # la ñ tampoco se teclea
    ("juan perez", True),                               # dos palabras, otra en medio
    ("perez juan", True),                               # y en cualquier orden
    ("perez volkswagen", False),                        # una palabra que no está
])
def test_la_busqueda_encuentra_al_cliente_como_sea_que_lo_tecleen(
    app, limpiar_cliente, tecleado, encuentra
):
    """En el mesón nadie tipea el RUT con puntos, la patente con guión ni las
    tildes, y el cliente que vuelve seguido solo se acuerda de la patente."""
    from src.ui import ClientesWidget, FormularioCliente, FormularioVehiculo

    cliente = FormularioCliente()
    cliente.rut.setText(RUT_QA)
    cliente.nombre.setText(NOMBRE_QA)
    cliente.accept()
    for patente in (PATENTE_QA, PATENTE_QA2):
        vehiculo = FormularioVehiculo(cliente_id=cliente.cliente_id)
        vehiculo.patente.setText(patente)
        vehiculo.accept()

    widget = ClientesWidget()
    widget.busqueda.setText(tecleado)
    ruts = {widget.tabla.item(f, 0).text(): f for f in range(widget.tabla.rowCount())}

    assert (RUT_QA in ruts) is encuentra, f"buscando {tecleado!r}"
    if encuentra:
        # Buscar por UNA patente no puede esconder los otros autos del cliente:
        # eso pasaría si el filtro fuera por el join en vez de un EXISTS.
        assert widget.tabla.item(ruts[RUT_QA], 4).text() == "2"
