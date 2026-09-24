"""Reportería contra PostgreSQL real: los totales salen de lo guardado en los
documentos y el rango de fechas incluye el día `hasta` completo."""
from datetime import date, datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel
from sqlalchemy import select

from conftest import patente_de_prueba, rut_de_prueba
from src import reportes
from src.auth import Sesion
from src.models import Cliente, DetalleOrden, DetalleVenta, Orden, Producto, Usuario, Vehiculo, Venta
from src.xlsx import leer_xlsx

DIA = date(2019, 3, 10)  # antes de los datos migrados: no choca con nada


def test_los_cuatro_reportes_cuadran_con_lo_guardado(db, app, tmp_path, monkeypatch):
    monkeypatch.setattr(Sesion, "rol", "ADMINISTRADOR")     # los reportes de plata son suyos
    usuario = Usuario(nombre=f"Reportero {rut_de_prueba()}", username=f"qa_rep_{rut_de_prueba()}",
                      password_hash="x", rol="SUPERVISOR")
    producto = Producto(nombre=f"Aceite reporte {rut_de_prueba()}", marca="Mobil",
                        precio_costo=1000, precio_venta=10000, stock_actual=10, stock_minimo=20)
    vehiculo = Vehiculo(cliente=Cliente(nombre_completo="Cliente reporte"), patente=patente_de_prueba())
    db.add_all([usuario, producto, vehiculo])
    db.flush()
    # 20.000 neto + 3.800 de IVA = 23.800... menos 2 del redondeo a la decena.
    venta = Venta(usuario=usuario, fecha_venta=datetime(2019, 3, 10, 23, 30), impuesto=3800,
                  ajuste_redondeo=-2, total_final=23798)
    orden = Orden(vehiculo=vehiculo, usuario=usuario, fecha_creacion=datetime(2019, 3, 10, 9),
                  kilometraje_ingreso=1, subtotal=10000, impuesto=1900, total_final=11900)
    fuera = Orden(vehiculo=vehiculo, usuario=usuario, fecha_creacion=datetime(2019, 3, 11),
                  kilometraje_ingreso=1, subtotal=5000, impuesto=950, total_final=5950)
    db.add_all([venta, orden, fuera])
    db.flush()
    db.add_all([DetalleVenta(venta=venta, producto=producto, cantidad=2, precio_unitario_cobrado=10000),
                DetalleOrden(orden=orden, producto=producto, cantidad=1, precio_unitario_cobrado=10000)])
    db.flush()

    # La fecha sale como date, no como texto: una columna de fechas ordenada
    # alfabéticamente pone el 01 de octubre antes del 02 de septiembre.
    filas, por_mes = reportes.ingresos_por_periodo(db, DIA, DIA)
    # El ajuste va en su columna y no en el neto: Neto + IVA + Ajuste = Total.
    assert filas == [(DIA, 1, 23798, 1, 11900, 30000, 5700, -2, 35698)] and not por_mes
    assert reportes.rotulo_de_fecha(DIA, por_mes) == "10-03-2019"
    assert reportes.rotulo_de_fecha(DIA, True) == "03-2019"
    # El día `hasta` entra completo, y un rango largo se agrupa por mes.
    assert reportes.ingresos_por_periodo(db, DIA, date(2019, 3, 11))[0][1][8] == 5950
    assert reportes.ingresos_por_periodo(db, DIA, date(2019, 12, 31))[1] is True
    assert reportes.ventas_por_producto(db, DIA, DIA) == [(producto.nombre, "Mobil", 3, 30000)]
    assert reportes.por_usuario(db, DIA, DIA) == [(usuario.nombre, 1, 23798, 1, 11900, 35698)]
    db.refresh(producto)
    assert (producto.nombre, "Mobil", "", 7, 20, 13) in reportes.reabastecimiento(db)  # 10 - 3 vendidos

    # La pantalla lee por su propia sesión: solo se prueba que arma, elige una
    # fila y exporta lo que muestra.
    from PySide6.QtCore import QDate
    from src.ui.reportes import REPORTES, ReportesWidget, rangos

    # Los rangos de siempre: "Este mes" empieza el día 1 y termina hoy.
    por_nombre = {n: (d, h) for n, d, h in rangos(date(2019, 3, 10))}
    assert por_nombre["Este mes"] == (date(2019, 3, 1), date(2019, 3, 10))
    assert por_nombre["Mes pasado"] == (date(2019, 2, 1), date(2019, 2, 28))
    assert por_nombre["Últimos 7 días"][0] == date(2019, 3, 4)

    widget = ReportesWidget()
    widget.rango.setCurrentText("Personalizado")
    assert widget.desde.isEnabled()          # solo el rango libre deja tocarlas
    widget.desde.setDate(QDate(2019, 3, 1)); widget.hasta.setDate(QDate(2019, 3, 31))

    # La pantalla lee con su propia sesión y no ve lo que esta transacción aún
    # no confirmó, así que el orden se prueba con filas puestas a mano: es el
    # bug que se reportó —la columna de fechas ordenada como texto pone el 01 de
    # octubre antes del 02 de septiembre—.
    widget.filas = [
        (date(2019, 10, 1), 1, 1000, 0, 0, 840, 160, 0, 1000),
        (date(2019, 9, 2), 2, 5000, 1, 3000, 6723, 1277, 0, 8000),
    ]
    widget._llenar_tabla(widget.definicion())
    assert [widget.tabla.item(f, 0).text() for f in range(2)] == ["02-09-2019", "01-10-2019"]
    widget.tabla.sortItems(0, Qt.DescendingOrder)
    assert [widget.tabla.item(f, 0).text() for f in range(2)] == ["01-10-2019", "02-09-2019"]
    widget.tabla.selectRow(0)   # elegir una fila es lo que junta los connect

    # El resumen y el gráfico salen de esas mismas filas.
    widget._llenar_resumen(widget.definicion())
    widget._dibujar_grafico(widget.definicion())
    barras = widget.grafico.chart().series()[0].barSets()[0]
    assert barras.count() == 2 and barras.at(0) == 1000

    # Cambiar de reporte cambia las columnas, el resumen y el gráfico.
    titulos = [d.titulo for d in REPORTES]
    widget.lista.setCurrentRow(titulos.index("Reabastecimiento"))   # no usa fechas
    assert not widget.rango.isEnabled()
    assert widget.tabla.columnCount() == len(reportes.COLUMNAS_REABASTECIMIENTO)
    ruta = widget.exportar_a_carpeta(tmp_path)
    assert ruta.name == "reabastecimiento_20190301_20190331.xlsx"
    exportado = leer_xlsx(ruta)
    assert exportado and list(exportado[0]) == reportes.COLUMNAS_REABASTECIMIENTO

    widget.lista.setCurrentRow(0)
    widget.filas = [(date(2019, 3, 10), 1, 23800, 1, 11900, 30000, 5700, 0, 35700)]
    ruta = widget.exportar_a_carpeta(tmp_path)
    assert leer_xlsx(ruta)[0]["Fecha"] == "10-03-2019"   # exportada formateada


def test_el_reporte_de_descuentos_junta_los_tres_tipos_y_quien_ingreso(db, app, monkeypatch):
    """Lo pidió el dueño: qué orden llevó descuento, de qué tipo, cuánto y
    quién la ingresó. Sin estados de pago: no es lo que se pregunta."""
    usuario = Usuario(nombre=f"Mesón {rut_de_prueba()}", username=f"qa_rep_{rut_de_prueba()}",
                      password_hash="x", rol="USUARIO_NORMAL")
    vehiculo = Vehiculo(cliente=Cliente(nombre_completo="Cliente descuento"),
                        patente=patente_de_prueba())
    db.add_all([usuario, vehiculo])
    db.flush()
    usados = set(db.scalars(select(Orden.folio_flyer).where(Orden.folio_flyer.isnot(None))))
    folio = max(set(range(1, 1001)) - usados)

    def orden(**campos):
        nueva = Orden(vehiculo=vehiculo, usuario=usuario, fecha_creacion=datetime(2019, 3, 10, 12),
                      subtotal=10000, total_final=10000, **campos)
        db.add(nueva)
        return nueva

    porcentaje = orden(descuento_porcentaje=10)
    monto = orden(descuento_monto=500)
    flyer = orden(descuento_monto=1000, convenio="FLYER", folio_flyer=folio)
    gremio = orden(descuento_monto=1500, convenio="GREMIO")
    orden()                                         # sin descuento: no va
    orden(descuento_monto=700, estado="ANULADA")    # anulada: no se hizo
    db.flush()

    comunes = (DIA, "Cliente descuento", vehiculo.patente, usuario.nombre)
    assert reportes.descuentos(db, DIA, DIA) == [
        (porcentaje.id, *comunes, "General (10 %)", 1000, 10000),
        (monto.id, *comunes, "General (monto)", 500, 10000),
        (flyer.id, *comunes, f"Flyer N° {folio:04d} (10 %)", 1000, 10000),
        (gremio.id, *comunes, "Gremio/Sindicato (15 %)", 1500, 10000),
    ]

    # Solo el administrador lo ve; los demás, solo la lista de compras.
    from src.ui.reportes import ReportesWidget

    monkeypatch.setattr(Sesion, "rol", "SUPERVISOR")
    widget = ReportesWidget()
    assert [d.titulo for d in widget.definiciones] == ["Reabastecimiento"]
    assert not widget.rango.isEnabled()

    monkeypatch.setattr(Sesion, "rol", "ADMINISTRADOR")
    widget = ReportesWidget()
    widget.lista.setCurrentRow([d.titulo for d in widget.definiciones].index("Órdenes con descuento"))
    assert widget.grafico.isHidden()          # una lista de órdenes no tiene forma que graficar
    widget.filas = [(1, DIA, "Ana", "AB1234", "Paloma", "General (monto)", 500, 9500)]
    widget._llenar_resumen(widget.definicion())
    assert widget.resumen.itemAt(0).widget().findChild(QLabel).text() == "$500"
