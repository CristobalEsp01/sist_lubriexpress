"""Importación de las planillas antiguas: lectura, plan, aplicación y deshacer.

Las planillas se arman en la prueba (un xlsx de varias hojas escrito a mano con
zipfile), así que no dependen de los archivos reales del taller.
"""
import zipfile
from datetime import date
from xml.sax.saxutils import escape

import pytest
from conftest import rut_de_prueba
from sqlalchemy import select

from src import importar_planillas as imp
from src.models import CuentaPorCobrar, FacturaProveedor, PagoCobro, PagoProveedor, Proveedor
from src.xlsx import leer_hojas


def serial(d: date) -> int:
    return (d - date(1899, 12, 30)).days


def _letra(i: int) -> str:
    return chr(ord("A") + i)


def hacer_xlsx(ruta, hojas: dict[str, list[list]]):
    """`hojas`: {nombre: filas}; cada fila es una lista de celdas (None = vacía).
    Las fechas se escriben como serial de Excel."""
    def celda(i, j, valor):
        ref = f"{_letra(j)}{i}"
        if valor is None:
            return ""
        if isinstance(valor, date):
            valor = serial(valor)
        if isinstance(valor, (int, float)):
            return f'<c r="{ref}"><v>{valor}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(valor))}</t></is></c>'

    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{n}" sheetId="{k}" r:id="rId{k}"/>' for k, n in enumerate(hojas, 1))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{k}" Type="x" Target="worksheets/sheet{k}.xml"/>'
                             for k in range(1, len(hojas) + 1)) + "</Relationships>")
        for k, filas in enumerate(hojas.values(), 1):
            cuerpo = "".join(
                f'<row r="{i}">' + "".join(celda(i, j, v) for j, v in enumerate(fila)) + "</row>"
                for i, fila in enumerate(filas, 1))
            z.writestr(f"xl/worksheets/sheet{k}.xml",
                       '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                       f"<sheetData>{cuerpo}</sheetData></worksheet>")


COBRAR = ["OC", "CLIENTE", "FECHA", "COSTO", "FACTURA", "FECHA", "VENTA NETO", "MONTO", "FECHA PAGO"]
PAGAR = ["PROVEEDOR", "FACTURA", "FECHA COMPRA", "FECHA CREDITO", "MONTO", "ABONO",
         "FECHA PAGO", "ESTADO", "OBSERVACIONES"]


@pytest.fixture
def sufijo():
    return rut_de_prueba().replace(".", "").replace("-", "")


@pytest.fixture
def planilla_cobrar(tmp_path, sufijo):
    ruta = tmp_path / "cobrar.xlsx"
    f = lambda n: f"9{sufijo}{n}"      # facturas propias de la prueba
    d = date(2026, 3, 1)
    hacer_xlsx(ruta, {"2026": [
        ["TÍTULO"], [], [],
        COBRAR,
        ["OC1", "SEREMI PRUEBA", date(2026, 2, 1), 70000, f(1), d, 100000, 119000, date(2026, 4, 1)],
        ["OC2", "INE PRUEBA", date(2026, 2, 1), 30000, f(2), d, 50000, 59500, None],
        ["OC3", "SIN FACTURA PRUEBA", date(2026, 2, 1), 30000, None, None, 50000, None, None],
        ["OC4", "REPETIDA PRUEBA", date(2026, 2, 1), 30000, f(2), d, 50000, 59500, None],
        [None, None, None, None, None, None, 999999],   # un total suelto
    ]})
    return ruta, f


def test_por_cobrar_lee_lo_util_y_explica_lo_omitido(planilla_cobrar):
    ruta, f = planilla_cobrar
    lectura = imp.leer_por_cobrar(ruta)
    assert [c.factura for c in lectura.items] == [f(1), f(2)]
    primera = lectura.items[0]
    assert (primera.cliente, primera.neto, primera.costo) == ("SEREMI PRUEBA", 100000, 70000)
    assert primera.fecha_factura == date(2026, 3, 1) and primera.fecha_pago == date(2026, 4, 1)
    motivos = imp.resumen_por_motivo(lectura.omitidas)
    assert motivos == {"sin factura": 1, "factura repetida": 1}
    assert lectura.avisos == []


def test_por_cobrar_avisa_si_el_monto_no_calza(tmp_path):
    ruta = tmp_path / "c.xlsx"
    hacer_xlsx(ruta, {"2026": [COBRAR, ["", "X", None, None, "77", date(2026, 3, 1), 100000, 500000, None]]})
    lectura = imp.leer_por_cobrar(ruta)
    assert len(lectura.items) == 1 and len(lectura.avisos) == 1


def test_una_hoja_sin_titulos_se_avisa_no_revienta(tmp_path):
    ruta = tmp_path / "raro.xlsx"
    hacer_xlsx(ruta, {"Notas": [["nada", "de", "interes"]]})
    lectura = imp.leer_por_cobrar(ruta)
    assert lectura.items == [] and "Notas" in lectura.avisos[0]


def test_aplicar_por_cobrar_crea_pagadas_y_pendientes_sin_duplicar(db, planilla_cobrar):
    ruta, f = planilla_cobrar
    plan = imp.planificar_por_cobrar(db, imp.leer_por_cobrar(ruta))
    assert len(plan.nuevas) == 2 and plan.existentes == []
    assert imp.aplicar_por_cobrar(db, plan) == 2

    pagada = db.scalar(select(CuentaPorCobrar).where(CuentaPorCobrar.numero_factura == f(1)))
    pendiente = db.scalar(select(CuentaPorCobrar).where(CuentaPorCobrar.numero_factura == f(2)))
    assert pagada.estado == "PAGADA" and pendiente.estado == "POR_COBRAR"
    assert pagada.monto == 119000 and pagada.costo == 70000
    assert pagada.observaciones.startswith(imp.MARCA)
    pago = db.scalar(select(PagoCobro).where(PagoCobro.cuenta_id == pagada.id))
    assert (pago.monto, pago.fecha_pago) == (119000, date(2026, 4, 1))

    otra_vez = imp.planificar_por_cobrar(db, imp.leer_por_cobrar(ruta))
    assert otra_vez.nuevas == [] and len(otra_vez.existentes) == 2


@pytest.fixture
def planilla_pagar(tmp_path, sufijo):
    ruta = tmp_path / "pagar.xlsx"
    a, b = f"Aceites {sufijo} Ltda. (Castrol)", f"Aceites {sufijo} Ltda."
    compra = date(2026, 1, 10)
    hacer_xlsx(ruta, {
        "2025": [["x"], PAGAR,
                 [a, "F1", compra, date(2026, 2, 10), 100000, 100000, date(2026, 2, 1), "Pagado", None],
                 [b, "F2", compra, date(2026, 2, 10), 200000, 50000, date(2026, 2, 1), "Abono", "cuota 1"],
                 [b, "F3", compra, None, 300000, None, None, None, None],
                 [None, None, None, None, 80000],                              # cuota suelta
                 [b, "NC1", compra, None, 5000, None, None, "Nota de crédito", None],
                 [b, None, compra, None, 5000]],                                # sin factura
        "2026": [PAGAR,
                 [b, "F1", compra, date(2026, 2, 10), 100000, 100000, date(2026, 2, 1), "Pagado", None],   # repetida
                 [b, "F2", compra, date(2026, 2, 10), 999, None, None, None, None]],                       # otro monto
    })
    return ruta, b


def test_por_pagar_unifica_proveedores_y_junta_repetidas(planilla_pagar):
    ruta, nombre = planilla_pagar
    lectura = imp.leer_por_pagar(ruta)
    assert [f.numero for f in lectura.items] == ["F1", "F2", "F3"]
    assert {f.proveedor for f in lectura.items} == {nombre}
    assert lectura.items[0].proveedor_planilla.endswith("(Castrol)")
    assert "Nombre en la planilla" in lectura.items[0].observaciones
    assert lectura.duplicadas == 1
    assert imp.resumen_por_motivo(lectura.omitidas) == {
        "sin proveedor ni factura": 1, "nota de crédito": 1,
        "sin proveedor o sin número de factura": 1, "misma factura con otro monto": 1}
    pagos = {f.numero: f.pagos for f in lectura.items}
    assert pagos["F1"] == ((100000, date(2026, 2, 1)),)
    assert pagos["F2"] == ((50000, date(2026, 2, 1)),)
    assert pagos["F3"] == ()
    assert lectura.items[2].vence == date(2026, 2, 9)          # 30 días desde la compra
    assert any("sin fecha de crédito" in a for a in lectura.avisos)


def test_aplicar_por_pagar_crea_proveedor_facturas_y_pagos(db, planilla_pagar):
    ruta, nombre = planilla_pagar
    plan = imp.planificar_por_pagar(db, imp.leer_por_pagar(ruta))
    assert imp.aplicar_por_pagar(db, plan) == (3, 1)

    proveedor = db.scalar(select(Proveedor).where(Proveedor.nombre == nombre))
    facturas = {f.numero_factura: f for f in db.scalars(
        select(FacturaProveedor).where(FacturaProveedor.proveedor_id == proveedor.id))}
    assert facturas["F1"].estado == "PAGADA"
    assert facturas["F2"].estado == "PENDIENTE" and facturas["F3"].estado == "PENDIENTE"
    assert db.scalar(select(PagoProveedor.monto).where(PagoProveedor.factura_id == facturas["F2"].id)) == 50000

    otra_vez = imp.planificar_por_pagar(db, imp.leer_por_pagar(ruta))
    assert otra_vez.nuevas == [] and len(otra_vez.existentes) == 3
    assert imp.aplicar_por_pagar(db, otra_vez) == (0, 0)


def test_deshacer_saca_lo_importado_y_deja_lo_hecho_a_mano(db, planilla_cobrar, planilla_pagar):
    from src import finanzas

    cobrar, f = planilla_cobrar
    pagar, nombre = planilla_pagar
    imp.aplicar_por_cobrar(db, imp.planificar_por_cobrar(db, imp.leer_por_cobrar(cobrar)))
    imp.aplicar_por_pagar(db, imp.planificar_por_pagar(db, imp.leer_por_pagar(pagar)))
    usuario = imp.usuario_de_importacion(db)
    a_mano = finanzas.crear_cuenta_manual(
        db, cliente_nombre="A MANO", numero_factura=f"M{f(9)}", fecha_factura=date(2026, 1, 1),
        venta_neto=1000, usuario_id=usuario.id)

    hechos = imp.deshacer(db)
    assert hechos["cuentas"] >= 2 and hechos["facturas"] >= 3
    assert hechos["pagos_cobro"] >= 1 and hechos["pagos_proveedor"] >= 2
    assert db.scalar(select(CuentaPorCobrar).where(CuentaPorCobrar.numero_factura == f(1))) is None
    assert db.get(CuentaPorCobrar, a_mano.id) is not None


def test_el_usuario_de_importacion_no_puede_entrar(db):
    usuario = imp.usuario_de_importacion(db)
    assert usuario.activo is False
    assert imp.usuario_de_importacion(db).id == usuario.id


def test_los_nombres_de_proveedor_que_no_se_pueden_juntar_quedan_separados():
    nombres = imp.unificar_proveedores(["Comercial WQM - Temuco", "Wilfredo Quintana Manzur"])
    assert len(set(nombres.values())) == 2


def test_lector_multihoja_devuelve_todas_las_hojas(tmp_path):
    ruta = tmp_path / "m.xlsx"
    hacer_xlsx(ruta, {"A": [["x", "y"]], "B": [[None, "z"]]})
    hojas = leer_hojas(ruta)
    assert list(hojas) == ["A", "B"]
    assert hojas["B"] == [(1, {1: "z"})]
