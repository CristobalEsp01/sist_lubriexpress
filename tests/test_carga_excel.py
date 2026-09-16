"""Carga masiva de inventario por plantilla Excel: la validación, el todo o
nada, y que el stock entre por Kardex. Contra PostgreSQL real, dentro de la
transacción del fixture."""
from decimal import Decimal

from conftest import rut_de_prueba
from sqlalchemy import select

from src.carga_excel import COLUMNAS, cargar, clasificar, guardar_plantilla, validar
from src.models import KardexMovimiento, Producto, Usuario
from src.xlsx import escribir_xlsx, leer_xlsx

SUFIJO = rut_de_prueba()


def fila(nombre, costo="1000", venta="2000", stock="5", minimo="", **extra):
    base = dict.fromkeys(COLUMNAS)
    base.update({"Nombre": nombre, "Precio costo": costo, "Precio venta neto": venta,
                 "Stock": stock, "Stock mínimo": minimo})
    base.update(extra)
    return base


def test_la_plantilla_se_escribe_y_se_lee_de_vuelta(tmp_path):
    ruta = tmp_path / "plantilla.xlsx"
    guardar_plantilla(ruta)
    (ejemplo,) = leer_xlsx(ruta)
    assert list(ejemplo) == COLUMNAS
    assert (ejemplo["Nombre"], ejemplo["Stock"]) == ("Aceite 5W30 Mobil 4L", "24")

    # Texto con caracteres que el XML tiene que escapar, y celdas vacías.
    escribir_xlsx(ruta, ["A", "B"], [["<Pérez & Cía>", None], [3.5, "x"]])
    assert leer_xlsx(ruta) == [{"A": "<Pérez & Cía>", "B": None}, {"A": "3.5", "B": "x"}]


def test_una_fila_mala_frena_toda_la_carga():
    limpias, rechazos = validar([
        fila(f"Bueno {SUFIJO}", minimo="2"),
        fila("", ),                                   # sin nombre
        fila(f"Sin costo {SUFIJO}", costo=None),
        fila(f"Fraccion {SUFIJO}", stock="2.5"),
        fila(f"bueno {SUFIJO}"),                      # repetido, distinto solo en mayúsculas
    ])
    assert [l["nombre"] for l in limpias] == [f"Bueno {SUFIJO}"]
    assert limpias[0]["stock_minimo"] == 2
    assert [r.split(":")[0] for r in rechazos] == ["Fila 3", "Fila 4", "Fila 5", "Fila 6"]

    _, faltan = validar([{"Producto": "x"}])
    assert faltan[0].startswith("Faltan columnas obligatorias: Nombre")


def test_el_stock_entra_por_kardex_y_lo_existente_solo_suma(db):
    usuario = Usuario(nombre="QA", username=f"qa_excel_{SUFIJO}", password_hash="x", rol="SUPERVISOR")
    existente = Producto(nombre=f"Filtro {SUFIJO}", precio_costo=100, precio_venta=200,
                         stock_actual=4, stock_minimo=1)
    db.add_all([usuario, existente])
    db.flush()

    limpias, rechazos = validar([
        fila(f"Aceite {SUFIJO}", costo="8319,3", venta="12000", stock="6", minimo="2",
             **{"Marca": "Mobil", "Ubicación": f"Repisa {SUFIJO}"}),
        fila(f"FILTRO {SUFIJO}", costo="999", venta="999", stock="3"),   # existe: precios intactos
        fila(f"Sin stock {SUFIJO}", stock="0"),
    ])
    assert not rechazos
    clasificar(db, limpias)
    assert [l["situacion"] for l in limpias] == ["nuevo", "existente", "nuevo"]

    cuenta = cargar(db, limpias, usuario.id)
    assert cuenta == {"nuevos": 2, "existentes": 1, "unidades": 9}

    aceite = db.scalar(select(Producto).where(Producto.nombre == f"Aceite {SUFIJO}"))
    db.refresh(aceite)
    assert (aceite.stock_actual, aceite.precio_costo, aceite.stock_minimo) == (6, Decimal("8319.30"), 2)
    assert aceite.ubicacion.descripcion == f"Repisa {SUFIJO}"
    db.refresh(existente)
    assert (existente.stock_actual, existente.precio_costo) == (7, 100)
    movimientos = db.scalars(
        select(KardexMovimiento).where(KardexMovimiento.usuario_id == usuario.id)
    ).all()
    assert sorted(m.cantidad_movida for m in movimientos) == [3, 6]
    assert all(m.tipo_movimiento == "ENTRADA" for m in movimientos)
    sin_stock = db.scalar(select(Producto).where(Producto.nombre == f"Sin stock {SUFIJO}"))
    assert sin_stock.stock_actual == 0


def test_el_dialogo_apaga_cargar_si_algo_se_rechaza(app, tmp_path):
    from src.ui.carga_excel import CargaExcelDialog

    ruta = tmp_path / "carga.xlsx"
    escribir_xlsx(ruta, COLUMNAS, [[f"Uno {SUFIJO}", None, None, None, None, 100, 200, 1, 0],
                                   ["", None, None, None, None, 100, 200, 1, 0]])
    dialogo = CargaExcelDialog()
    dialogo.previsualizar(ruta)
    assert dialogo.tabla.rowCount() == 1
    assert dialogo.tabla.item(0, 1).text() == "nuevo"
    assert "Fila 3" in dialogo.rechazos.toPlainText()
    assert not dialogo.boton_cargar.isEnabled()
    dialogo.tabla.selectRow(0)  # elegir una fila es lo que junta los connect

    escribir_xlsx(ruta, COLUMNAS, [[f"Uno {SUFIJO}", None, None, None, None, 100, 200, 1, 0]])
    dialogo.previsualizar(ruta)
    assert dialogo.rechazos.toPlainText() == "" and dialogo.boton_cargar.isEnabled()
