"""Reportería contra PostgreSQL real: los totales salen de lo guardado en los
documentos y el rango de fechas incluye el día `hasta` completo."""
from datetime import date, datetime

from conftest import patente_de_prueba, rut_de_prueba
from src import reportes
from src.models import Cliente, DetalleOrden, DetalleVenta, Orden, Producto, Usuario, Vehiculo, Venta
from src.xlsx import leer_xlsx

DIA = date(2031, 3, 10)  # un día que ningún dato real ocupa


def test_los_cuatro_reportes_cuadran_con_lo_guardado(db, app, tmp_path):
    usuario = Usuario(nombre=f"Reportero {rut_de_prueba()}", username=f"qa_rep_{rut_de_prueba()}",
                      password_hash="x", rol="SUPERVISOR")
    producto = Producto(nombre=f"Aceite reporte {rut_de_prueba()}", marca="Mobil",
                        precio_costo=1000, precio_venta=10000, stock_actual=10, stock_minimo=20)
    vehiculo = Vehiculo(cliente=Cliente(nombre_completo="Cliente reporte"), patente=patente_de_prueba())
    db.add_all([usuario, producto, vehiculo])
    db.flush()
    venta = Venta(usuario=usuario, fecha_venta=datetime(2031, 3, 10, 23, 30), impuesto=3800, total_final=23800)
    orden = Orden(vehiculo=vehiculo, usuario=usuario, fecha_creacion=datetime(2031, 3, 10, 9),
                  kilometraje_ingreso=1, subtotal=10000, impuesto=1900, total_final=11900)
    fuera = Orden(vehiculo=vehiculo, usuario=usuario, fecha_creacion=datetime(2031, 3, 11),
                  kilometraje_ingreso=1, subtotal=5000, impuesto=950, total_final=5950)
    db.add_all([venta, orden, fuera])
    db.flush()
    db.add_all([DetalleVenta(venta=venta, producto=producto, cantidad=2, precio_unitario_cobrado=10000),
                DetalleOrden(orden=orden, producto=producto, cantidad=1, precio_unitario_cobrado=10000)])
    db.flush()

    assert reportes.ingresos_por_periodo(db, DIA, DIA) == [("10-03-2031", 1, 23800, 1, 11900, 30000, 5700, 35700)]
    assert reportes.ingresos_por_periodo(db, DIA, date(2031, 3, 11))[1][7] == 5950   # el día `hasta` entra completo
    assert reportes.ventas_por_producto(db, DIA, DIA) == [(producto.nombre, "Mobil", 3, 30000)]
    assert reportes.por_usuario(db, DIA, DIA) == [(usuario.nombre, 1, 23800, 1, 11900, 35700)]
    db.refresh(producto)
    assert (producto.nombre, "Mobil", "", 7, 20, 13) in reportes.reabastecimiento(db)  # 10 - 3 vendidos

    # La pantalla lee por su propia sesión: solo se prueba que arma, elige una
    # fila y exporta lo que muestra.
    from PySide6.QtCore import QDate
    from src.ui.reportes import ReportesWidget
    widget = ReportesWidget()
    widget.desde.setDate(QDate(2031, 3, 1)); widget.hasta.setDate(QDate(2031, 3, 31))
    for tabla in widget.tablas:
        if tabla.rowCount():
            tabla.selectRow(0)
    ruta = widget.exportar_a_carpeta(3, tmp_path)
    assert ruta.name == "reabastecimiento_20310301_20310331.xlsx"
    exportado = leer_xlsx(ruta)
    assert exportado and list(exportado[0]) == reportes.COLUMNAS_REABASTECIMIENTO
    # Una barra por fila, con la columna que resume el reporte.
    barras = widget.graficos[0].chart().series()[0].barSets()[0]
    assert barras.count() == len(widget.filas[0])
    grafico = ReportesWidget._grafico("Ingresos", "Total", [("10-03-2031", 1, 2, 35700)], 3, True)
    assert grafico.series()[0].barSets()[0].at(0) == 35700
