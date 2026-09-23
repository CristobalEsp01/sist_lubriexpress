"""La pestaña de Caja, sin pantalla.

Escribe con su propia SessionLocal() en cada operación, así que los datos de
apoyo se crean con commits reales y se limpian al final, como en las otras
pruebas de interfaz.
"""
from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QDialog, QMessageBox
from sqlalchemy import select

from conftest import rut_de_prueba
from src.auth import Sesion
from src.database import SessionLocal
from src.models import MovimientoCaja, Usuario

MOTIVO_INGRESO = "QA efectivo de la mañana"
MOTIVO_GASTO = "QA bencina"


@pytest.fixture
def cajero():
    with SessionLocal() as db:
        usuario = Usuario(nombre="Cajero QA", username=f"qa_cajero_{rut_de_prueba()}",
                          password_hash="hash-de-prueba", rol="USUARIO_NORMAL")
        db.add(usuario)
        db.commit()
        datos = SimpleNamespace(usuario_id=usuario.id)
        Sesion.iniciar(SimpleNamespace(id=usuario.id, nombre=usuario.nombre, rol=usuario.rol))

    yield datos

    Sesion.cerrar()
    with SessionLocal() as db:
        propios = select(MovimientoCaja).where(MovimientoCaja.usuario_id == datos.usuario_id)
        # Las anulaciones apuntan a lo anulado: se borran primero o la FK salta.
        for movimiento in db.scalars(propios.where(MovimientoCaja.anula_id.isnot(None))):
            db.delete(movimiento)
        db.flush()
        for movimiento in db.scalars(propios):
            db.delete(movimiento)
        db.delete(db.get(Usuario, datos.usuario_id))
        db.commit()


def _cifra(widget, clave: str) -> int:
    """La cifra que muestra la pantalla, de vuelta a número.

    Las pruebas comparan diferencias y no totales: la caja suma el día entero y
    la base de desarrollo tiene movimientos de verdad, así que un total exacto
    pasa hoy y falla mañana.
    """
    return int(widget._etiquetas[clave].text().replace("$", "").replace(".", ""))


def _con_dialogo(monkeypatch, monto: int, motivo: str):
    from src.ui.caja import MovimientoDialog

    def responder(self):
        self.monto.setValue(monto)
        self.motivo.setText(motivo)
        return QDialog.Accepted

    monkeypatch.setattr(MovimientoDialog, "exec", responder)


def test_la_caja_del_dia_suma_lo_anotado_a_mano_y_anular_lo_deshace(app, cajero, monkeypatch):
    from src.ui.caja import CajaWidget

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    widget = CajaWidget()
    antes = {clave: _cifra(widget, clave) for clave in ("entradas", "salidas", "balance")}

    _con_dialogo(monkeypatch, 20000, MOTIVO_INGRESO)
    widget.registrar("INGRESO")
    _con_dialogo(monkeypatch, 5000, MOTIVO_GASTO)
    widget.registrar("EGRESO")

    assert _cifra(widget, "entradas") == antes["entradas"] + 20000
    assert _cifra(widget, "salidas") == antes["salidas"] + 5000
    assert _cifra(widget, "balance") == antes["balance"] + 15000

    # Elegir una fila es lo primero que hace cualquiera: es donde se juntan los
    # connect, y sin esto el botón de anular nunca se prueba encendido.
    motivos = [widget.tabla.item(f, 2).text() for f in range(widget.tabla.rowCount())]
    widget.tabla.selectRow(motivos.index(MOTIVO_GASTO))
    assert widget.boton_anular.isEnabled()

    widget.anular()

    assert _cifra(widget, "salidas") == antes["salidas"]
    assert _cifra(widget, "balance") == antes["balance"] + 20000
    # El par anulado sigue en la lista, apagado: la caja es de solo agregado.
    motivos = [widget.tabla.item(f, 2).text() for f in range(widget.tabla.rowCount())]
    assert MOTIVO_GASTO in motivos and f"Anula: {MOTIVO_GASTO}" in motivos
    widget.tabla.selectRow(motivos.index(MOTIVO_GASTO))
    assert not widget.boton_anular.isEnabled()


def test_la_caja_se_guarda_en_pdf(app, cajero, monkeypatch, tmp_path):
    from src.ui import caja as ui_caja

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(ui_caja, "carpeta_de_documentos", lambda sub: tmp_path)

    _con_dialogo(monkeypatch, 3000, MOTIVO_GASTO)
    widget = ui_caja.CajaWidget()
    widget.registrar("EGRESO")
    widget.guardar_pdf()

    archivo = tmp_path / f"caja-{date.today():%Y-%m-%d}.pdf"
    assert archivo.is_file() and archivo.read_bytes()[:4] == b"%PDF"


def test_la_apertura_se_pide_hasta_que_se_registra_y_los_dias_pasados_solo_se_miran(
        app, cajero, monkeypatch):
    """Fabián: en la mañana se cuenta el cajón y se anota. Sin apertura, lo
    que "debe haber" no cuenta el fondo, así que la pantalla la pide."""
    from PySide6.QtCore import QDate

    from src import caja
    from src.ui.caja import CajaWidget

    with SessionLocal() as db:
        habia = caja.tiene_apertura(db, date.today())
    widget = CajaWidget()
    assert widget.aviso_apertura.isVisibleTo(widget) == (not habia)
    assert widget.boton_apertura.isEnabled() == (not habia)
    if habia:
        pytest.skip("hoy ya tiene apertura en la base de desarrollo")

    antes = _cifra(widget, "apertura")
    _con_dialogo(monkeypatch, 40000, "QA apertura")
    widget.registrar("APERTURA")
    assert _cifra(widget, "apertura") == antes + 40000
    assert not widget.aviso_apertura.isVisibleTo(widget)
    assert not widget.boton_apertura.isEnabled()      # una sola por día

    # Un día pasado se mira y se anula, pero no se le anota nada nuevo.
    widget.fecha.setDate(QDate.currentDate().addDays(-1))
    assert not (widget.boton_dinero.isEnabled() or widget.boton_gasto.isEnabled()
                or widget.boton_apertura.isEnabled())
    assert widget.boton_pdf.isEnabled() and not widget.aviso_apertura.isVisibleTo(widget)
