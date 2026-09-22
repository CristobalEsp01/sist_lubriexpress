"""La migración del sistema antiguo, contra PostgreSQL real y con planillas
chicas armadas a mano: lo sucio de las reales, una fila de cada cosa.

Corre dentro de la transacción del fixture `db`, así que no deja residuos.
"""
import zipfile
from decimal import Decimal

import pytest
from conftest import patente_de_prueba, rut_de_prueba
from sqlalchemy import select, update

from scripts.migrar_sistema_antiguo import (
    USUARIO_MIGRACION, PATENTE_ORDEN, Informe, canonizar_categorias, cuadre, fecha_excel,
    migrar,
)
from src.models import KardexMovimiento, Orden, Producto, Servicio, Usuario, Vehiculo
from src.xlsx import leer_xlsx

SUFIJO = rut_de_prueba()  # nombres distintos en cada corrida, como manda conftest


def orden(patente, nombre, apellidos, fecha="46272", kms="145035", estado="Entregado",
          tecnico=None, subtotal="79663.8", impuestos="15136.12", total="94799.92",
          descuento=None, ref="#4171"):
    return {
        "id_gato": ref, "date_created": fecha, "Nombre": nombre, "Apellidos": apellidos,
        "Falla": "cambio aceite", PATENTE_ORDEN: patente, "kms": kms, "Descuento": descuento,
        "Subtotal": subtotal, "Impuestos": impuestos, "Total general": total,
        "Estado": estado, "tecnico": tecnico,
    }


@pytest.fixture
def planillas():
    p1, p2, p3 = patente_de_prueba(), patente_de_prueba(), patente_de_prueba()
    tecnico = f"Técnico Migrado {SUFIJO}"
    return dict(
        clientes=[
            {"Nombre del cliente": f"Juan Pérez {SUFIJO}", "ID": None, "Telefono": "911111111"},
            {"Nombre del cliente": f"JUAN PEREZ {SUFIJO}", "ID": None, "Telefono": "922222222"},  # homónimo
            {"Nombre del cliente": f"Ana Soto {SUFIJO}", "ID": None, "Telefono": None},
        ],
        vehiculos=[
            {"patente": f" {p1[:2].lower()}-{p1[2:]} ", "tipo": "Camioneta", "marca": "Nissan",
             "modelo": "Np300", "año": "2017", "version": "2.3 Diesel", "vin": "SJNFBAJ11JA014460",
             "num_motor": "MR20", "color": None, "transmision": "manual ", "traccion": None},
            {"patente": p2, "tipo": "Sedan", "marca": "Kia", "modelo": "Rio", "año": "2014-2015"},
            {"patente": p3, "marca": "Sin", "modelo": "Órdenes"},           # nadie dice de quién es
            {"patente": "AF164GN", "marca": "Fiat", "modelo": "argentina"},  # patente inválida
            {"patente": p1, "marca": "repetida"},
        ],
        productos=[
            {"Nombre del producto": f"Aceite {SUFIJO}", "Fabricante": "Mobil", "Categoría": "Aceite",
             "Costo": "4599", "Precio_neto": "8319.2999999999993", "stock_actual": "5",
             "Descripción": "Ubicación: M-4C"},
            {"Nombre del producto": f"Filtro {SUFIJO}", "Fabricante": "Mann", "Categoría": "Filtro",
             "Costo": "1000", "Precio_neto": "2000", "stock_actual": "-3",     # stock negativo
             "Descripción": "Mann M7-B original"},
            {"Nombre del producto": f"Sin costo {SUFIJO}", "Fabricante": None, "Categoría": None,
             "Costo": None, "Precio_neto": "2000", "stock_actual": "4"},        # se rechaza
        ],
        servicios=[
            {"Nombre del servicio": f" SS Cambio Aceite {SUFIJO}", "Categoría del servicio": None,
             "Precio": "16806.72"},
        ],
        ordenes=[
            # p1: dos dueños distintos; el más reciente manda. La primera es la
            # que trae técnico y descuento.
            orden(p1, "Ana ", "Soto " + SUFIJO, fecha="46000", tecnico=tecnico, descuento="1000",
                  subtotal="10000", impuestos="1710", total="10710", ref="#1"),
            orden(p1, "Juan", "Pérez " + SUFIJO, fecha="46272", ref="#2"),
            # p2: el nombre no está en clientes -> se crea desde la orden.
            orden(p2, "Pedro", "Nuevo " + SUFIJO, estado=None, ref="#3"),
            orden(p2, "Pedro", "Nuevo " + SUFIJO, kms=None, ref="#4"),            # sin kilometraje
            orden(p2, "Pedro", "Nuevo " + SUFIJO, estado="Cancelado", ref="#5"),  # cancelada
            orden("XXXX", "Sin", "Patente", ref="#6"),
        ],
        _patentes=(p1, p2, p3),
    )


def test_la_migracion_carga_lo_que_cuadra_y_cuenta_lo_que_no(db, planillas):
    p1, p2, p3 = planillas.pop("_patentes")
    # La base de desarrollo puede tener la migración real ya hecha; el guardián
    # la vería y no haría nada. Se le esconde el marcador dentro de la
    # transacción de la prueba, que se revierte entera al terminar.
    db.execute(update(Usuario).where(Usuario.username == USUARIO_MIGRACION)
               .values(username=f"{USUARIO_MIGRACION}_{SUFIJO}"))
    informe = migrar(db, planillas)

    # Usuarios: el técnico y sistema_antiguo, inactivos y sin poder entrar.
    sistema = db.scalar(select(Usuario).where(Usuario.username == USUARIO_MIGRACION))
    tecnico = db.scalar(select(Usuario).where(Usuario.nombre == f"Técnico Migrado {SUFIJO}"))
    assert not sistema.activo and not tecnico.activo
    assert (tecnico.username, tecnico.rol) == ("tecnico.migrado", "USUARIO_NORMAL")

    # Clientes: los homónimos se funden (queda el primer teléfono) y el que
    # solo aparece en una orden se crea.
    juan = db.scalars(select(Vehiculo).where(Vehiculo.patente == p1)).one().cliente
    assert (juan.nombre_completo, juan.telefono) == (f"Juan Pérez {SUFIJO}", "911111111")
    pedro = db.scalars(select(Vehiculo).where(Vehiculo.patente == p2)).one().cliente
    assert (pedro.nombre_completo, pedro.telefono) == (f"Pedro Nuevo {SUFIJO}", None)

    # Vehículos: la patente se normaliza, los extras entran tal cual, el año
    # raro queda vacío, y sin orden que lo vincule a alguien no se carga.
    v1 = db.scalars(select(Vehiculo).where(Vehiculo.patente == p1)).one()
    assert (v1.tipo, v1.version, v1.vin, v1.numero_motor, v1.transmision, v1.anio_fabricacion) == (
        "Camioneta", "2.3 Diesel", "SJNFBAJ11JA014460", "MR20", "manual", 2017
    )
    assert db.scalars(select(Vehiculo).where(Vehiculo.patente == p2)).one().anio_fabricacion is None
    assert db.scalar(select(Vehiculo).where(Vehiculo.patente == p3)) is None

    # Órdenes: cabeceras con las cifras copiadas, el técnico como usuario y el
    # estado mapeado. Cancelada o sin patente: fuera. Sin kilometraje: entra
    # con el campo vacío, que es lo que el historial traía.
    ordenes = {o.notas.split("(")[1].split(")")[0]: o for o in v1.ordenes}
    assert set(ordenes) == {"#1", "#2"}
    con_descuento = ordenes["#1"]
    assert (con_descuento.subtotal, con_descuento.descuento_monto, con_descuento.impuesto,
            con_descuento.total_final) == (10000, 1000, 1710, 10710)
    assert con_descuento.usuario_id == tecnico.id and con_descuento.estado_pago
    assert con_descuento.fecha_creacion == fecha_excel("46000")
    assert ordenes["#2"].usuario_id == sistema.id
    de_p2 = {o.notas.split("(")[1].split(")")[0]: o for o in
             db.scalars(select(Vehiculo).where(Vehiculo.patente == p2)).one().ordenes}
    assert set(de_p2) == {"#3", "#4"}
    assert not de_p2["#3"].estado_pago
    assert de_p2["#4"].kilometraje_ingreso is None

    # Productos: el stock inicial llega por Kardex y cuadra con la planilla;
    # el negativo queda en 0 sin movimiento; sin costo no entra.
    aceite = db.scalar(select(Producto).where(Producto.nombre == f"Aceite {SUFIJO}"))
    db.refresh(aceite)
    assert (aceite.stock_actual, aceite.precio_venta, aceite.precio_costo) == (
        5, Decimal("8319.30"), 4599
    )
    (entrada,) = db.scalars(select(KardexMovimiento).where(KardexMovimiento.producto_id == aceite.id))
    assert (entrada.tipo_movimiento, entrada.cantidad_movida, entrada.stock_resultante,
            entrada.usuario_id) == ("ENTRADA", 5, 5, sistema.id)
    # La ubicación que el sistema viejo escribió en la descripción pasa a su
    # columna. Si era lo único que decía, la descripción queda vacía; si había
    # algo más escrito, vuelve intacta y no se pierde texto.
    assert (aceite.ubicacion.descripcion, aceite.descripcion) == ("M4-C", None)

    filtro = db.scalar(select(Producto).where(Producto.nombre == f"Filtro {SUFIJO}"))
    assert (filtro.ubicacion.descripcion, filtro.descripcion) == ("M7-B", "Mann M7-B original")
    assert filtro.stock_actual == 0
    assert db.query(KardexMovimiento).filter_by(producto_id=filtro.id).count() == 0
    assert db.scalar(select(Producto).where(Producto.nombre == f"Sin costo {SUFIJO}")) is None

    servicio = db.scalar(select(Servicio).where(Servicio.nombre == f"SS Cambio Aceite {SUFIJO}"))
    assert servicio.precio_venta == Decimal("16806.72")

    assert informe.cargados == {
        "usuarios": 2, "clientes": 3, "vehiculos": 2, "ordenes": 4,
        "productos": 2, "kardex (stock inicial)": 1, "servicios": 1, "ubicaciones": 2,
    }
    assert dict(informe.descartes) == {
        ("clientes", "homónimo fundido con otro teléfono (se conservó el primero)"): 1,
        ("clientes", "creado desde una orden (no estaba en la planilla)"): 1,
        ("vehiculos", "patente inválida"): 1,
        ("vehiculos", "patente repetida (se conservó la primera)"): 1,
        ("vehiculos", "sin ninguna orden que diga de quién es"): 1,
        ("vehiculos", "año no reconocible (queda vacío)"): 1,
        ("ordenes", "patente inválida"): 1,
        ("ordenes", "sin kilometraje (queda vacío)"): 1,
        ("ordenes", "cancelada en el sistema antiguo"): 1,
        ("productos", "stock negativo (cargado en 0, revisar)"): 1,
        ("productos", "ubicación leída de la descripción"): 2,
        ("productos", "sin costo (precio_costo es obligatorio)"): 1,
    }
    assert informe.stock_esperado == 5
    cuadre(db, informe.stock_esperado)  # y revienta si el trigger sumara dos veces

    # Idempotente: la segunda corrida no hace nada.
    assert migrar(db, planillas) is None
    assert db.query(Orden).filter_by(vehiculo_id=v1.id).count() == 2
    assert db.query(KardexMovimiento).filter_by(producto_id=aceite.id).count() == 1


def test_el_lector_de_xlsx_entiende_los_tres_tipos_de_celda(tmp_path):
    """Texto compartido, texto en línea y número: lo que traen las planillas."""
    hoja = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c></row>'
        '<row r="2"><c r="A2" t="s"><v>3</v></c><c r="B2"><v>46272</v></c><c r="C2" t="inlineStr"><is><t>en línea</t></is></c></row>'
        '<row r="3"><c r="A3" t="s"><v>3</v></c></row>'
        "</sheetData></worksheet>"
    )
    compartidas = (
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<si><t>Nombre</t></si><si><t>Fecha</t></si><si><t>Nota</t></si><si><t>Pérez</t></si></sst>"
    )
    ruta = tmp_path / "mini.xlsx"
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("xl/sharedStrings.xml", compartidas)
        z.writestr("xl/worksheets/sheet1.xml", hoja)

    assert leer_xlsx(ruta) == [
        {"Nombre": "Pérez", "Fecha": "46272", "Nota": "en línea"},
        {"Nombre": "Pérez", "Fecha": None, "Nota": None},   # celdas vacías no aparecen en el XML
    ]
    assert fecha_excel("46272").date().isoformat() == "2026-09-07"


def test_las_categorias_se_unifican_pero_las_erratas_quedan_avisadas():
    """La planilla real trae 131 escrituras para sesenta y tantas categorías.

    La misma palabra escrita distinto se junta sola. Una errata no: "Aceite
    moto" es aceite de moto, no un "Aceite motor" mal tecleado, y comparar
    letras no sabe la diferencia. Se avisa y lo resuelve quien conoce el mesón.
    """
    informe = Informe()
    mapa = canonizar_categorias(
        ["Filtro aire"] * 3 + ["FILTRO AIRE", "Filtro de Aires", "  filtro aire "]
        + ["Aceite motor"] * 2 + ["Aceite moto"] + ["AAceite motor"]
        + ["Bujía", "Bujía", "Bujias"] + ["REPUESTO", "REPUSTO"] + [None, ""],
        informe, "productos",
    )

    # Mayúsculas, tildes, el "de" del medio y el plural son la misma categoría.
    assert mapa["FILTRO AIRE"] == mapa["Filtro de Aires"] == "Filtro aire"
    assert mapa["Bujias"] == "Bujía"
    # Erratas evidentes con equivalencia explícita comprobada.
    assert mapa["AAceite motor"] == "Aceite motor"
    assert mapa["REPUSTO"] == "REPUESTO"
    # El nombre es la escritura más usada: no se inventa una que nadie escribió.
    assert sorted(set(mapa.values())) == ["Aceite moto", "Aceite motor", "Bujía", "Filtro aire", "REPUESTO"]

    unificadas = informe.detalle[("productos", "categoría unificada (la misma, escrita distinto)")]
    assert "FILTRO AIRE (1) -> Filtro aire" in unificadas
    assert "AAceite motor (1) -> Aceite motor" in unificadas
    assert "REPUSTO (1) -> REPUESTO" in unificadas

    parecidas = informe.detalle[
        ("productos", "categoría parecida a otra (juntarlas es decisión del taller)")
    ]
    assert parecidas == ["Aceite moto (1) ~ ¿Aceite motor (3)?"]
