"""Reportería contra PostgreSQL real: los totales salen de lo guardado en los
documentos y el rango de fechas incluye el día `hasta` completo."""
from datetime import date, datetime

from PySide6.QtCore import Qt

from conftest import patente_de_prueba, rut_de_prueba
from src import reportes
from src.models import Cliente, DetalleOrden, DetalleVenta, Orden, Producto, Usuario, Vehiculo, Venta
from src.xlsx import leer_xlsx

DIA = date(2019, 3, 10)  # antes de los datos migrados: no choca con nada


def test_los_cuatro_reportes_cuadran_con_lo_guardado(db, app, tmp_path):
    usuario = Usuario(nombre=f"Reportero {rut_de_prueba()}", username=f"qa_rep_{rut_de_prueba()}",
                      password_hash="x", rol="SUPERVISOR")
    producto = Producto(nombre=f"Aceite reporte {rut_de_prueba()}", marca="Mobil",
                        precio_costo=1000, precio_venta=10000, stock_actual=10, stock_minimo=20)
    vehiculo = Vehiculo(cliente=Cliente(nombre_completo="Cliente reporte"), patente=patente_de_prueba())
    db.add_all([usuario, producto, vehiculo])
    db.flush()
    venta = Venta(usuario=usuario, fecha_venta=datetime(2019, 3, 10, 23, 30), impuesto=3800, total_final=23800)
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
    assert filas == [(DIA, 1, 23800, 1, 11900, 30000, 5700, 35700)] and not por_mes
    assert reportes.rotulo_de_fecha(DIA, por_mes) == "10-03-2019"
    assert reportes.rotulo_de_fecha(DIA, True) == "03-2019"
    # El día `hasta` entra completo, y un rango largo se agrupa por mes.
    assert reportes.ingresos_por_periodo(db, DIA, date(2019, 3, 11))[0][1][7] == 5950
    assert reportes.ingresos_por_periodo(db, DIA, date(2019, 12, 31))[1] is True
    assert reportes.ventas_por_producto(db, DIA, DIA) == [(producto.nombre, "Mobil", 3, 30000)]
    assert reportes.por_usuario(db, DIA, DIA) == [(usuario.nombre, 1, 23800, 1, 11900, 35700)]
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
        (date(2019, 10, 1), 1, 1000, 0, 0, 840, 160, 1000),
        (date(2019, 9, 2), 2, 5000, 1, 3000, 6723, 1277, 8000),
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
    widget.lista.setCurrentRow(3)            # Reabastecimiento: no usa fechas
    assert not widget.rango.isEnabled()
    assert widget.tabla.columnCount() == len(REPORTES[3].columnas)
    ruta = widget.exportar_a_carpeta(tmp_path)
    assert ruta.name == "reabastecimiento_20190301_20190331.xlsx"
    exportado = leer_xlsx(ruta)
    assert exportado and list(exportado[0]) == reportes.COLUMNAS_REABASTECIMIENTO

    widget.lista.setCurrentRow(0)
    widget.filas = [(date(2019, 3, 10), 1, 23800, 1, 11900, 30000, 5700, 35700)]
    ruta = widget.exportar_a_carpeta(tmp_path)
    assert leer_xlsx(ruta)[0]["Fecha"] == "10-03-2019"   # exportada formateada
