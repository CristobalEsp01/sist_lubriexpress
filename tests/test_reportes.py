"""Reportería contra PostgreSQL real: los totales salen de lo guardado en los
documentos y el rango de fechas incluye el día `hasta` completo."""
from datetime import date, datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel
from sqlalchemy import select

from conftest import patente_de_prueba, rut_de_prueba
from src import reportes
from src.auth import Sesion
from src.models import (
    Cliente, DetalleOrden, DetalleVenta, Mecanico, Orden, Producto, Usuario, Vehiculo, Venta,
)
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
    # Con un solo producto vendido, es el 100 % de lo vendido.
    assert reportes.ventas_por_producto(db, DIA, DIA) == [(producto.nombre, "Mobil", 3, 30000, 100.0)]
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
    widget.filas = [("Aceite 10W40", "Mobil", "Aceite motor", 1, 3, 2)]
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


def test_al_abrir_se_ve_el_resumen_y_la_serie_en_el_tiempo_va_entera(app, monkeypatch):
    """Dos bugs de la pantalla. El resumen se armaba mientras la pestaña se
    mostraba y quedaba oculto hasta cambiar algo. Y el gráfico de ingresos
    cortaba la serie en 12 y la titulaba "Los 12 mayores": con un mes elegido,
    dejaba fuera los días más recientes."""
    from src.ui.reportes import ReportesWidget

    monkeypatch.setattr(Sesion, "rol", "ADMINISTRADOR")
    widget = ReportesWidget()
    widget.show()
    app.processEvents()
    bloques = [widget.resumen.itemAt(i).widget() for i in range(widget.resumen.count())]
    assert [b for b in bloques if b] and all(b.isVisible() for b in bloques if b)

    widget.lista.setCurrentRow(0)                   # Ingresos por período
    widget.filas = [(date(2019, 3, d), 1, 1000 * d, 0, 0, 0, 0, 0, 1000 * d) for d in range(1, 21)]
    widget._dibujar_grafico(widget.definicion())
    barras = widget.grafico.chart().series()[0].barSets()[0]
    assert barras.count() == 20 and barras.at(19) == 20000
    assert widget.grafico.chart().title() == ""


def test_por_mecanico_cuenta_las_ordenes_de_cada_uno(db):
    """Quién trabajó más autos. Las órdenes de antes del mecánico salen como
    'Sin asignar', y una anulada no se trabajó."""
    usuario = Usuario(nombre=f"Mesón {rut_de_prueba()}", username=f"qa_rep_{rut_de_prueba()}",
                      password_hash="x", rol="USUARIO_NORMAL")
    mecanico = Mecanico(nombre=f"QA Mecánico reporte {rut_de_prueba()}")
    vehiculo = Vehiculo(cliente=Cliente(nombre_completo="Cliente mecánico"),
                        patente=patente_de_prueba())
    db.add_all([usuario, mecanico, vehiculo])
    db.flush()
    for mec, total, estado in ((mecanico, 10000, "ENTREGADA"), (mecanico, 5000, "ENTREGADA"),
                               (None, 2000, "ENTREGADA"), (mecanico, 9999, "ANULADA")):
        db.add(Orden(vehiculo=vehiculo, usuario=usuario, mecanico=mec, estado=estado,
                     fecha_creacion=datetime(2019, 3, 10, 12), subtotal=total, total_final=total))
    db.flush()

    assert reportes.por_mecanico(db, DIA, DIA) == [
        (mecanico.nombre, 2, 15000), ("Sin asignar", 1, 2000),
    ]


def test_reabastecimiento_lista_solo_lo_que_tiene_minimo(db):
    """Sin mínimo no hay a qué reponer: con el mínimo en 0 de lo migrado, la
    lista traía 991 productos y decía que faltaban 0 unidades."""
    sin_minimo_antes = reportes.productos_sin_minimo(db)
    bajo = Producto(nombre=f"QA bajo el mínimo {rut_de_prueba()}", precio_costo=1, precio_venta=2,
                    stock_actual=1, stock_minimo=3)
    justo = Producto(nombre=f"QA en el mínimo {rut_de_prueba()}", precio_costo=1, precio_venta=2,
                     stock_actual=3, stock_minimo=3)
    sin_minimo = Producto(nombre=f"QA sin mínimo {rut_de_prueba()}", precio_costo=1, precio_venta=2,
                          stock_actual=0, stock_minimo=0)
    db.add_all([bajo, justo, sin_minimo])
    db.flush()

    nombres = [fila[0] for fila in reportes.reabastecimiento(db)]
    assert bajo.nombre in nombres and justo.nombre in nombres
    assert sin_minimo.nombre not in nombres
    assert nombres.index(bajo.nombre) < nombres.index(justo.nombre)   # lo que más falta, primero
    assert reportes.productos_sin_minimo(db) == sin_minimo_antes + 1


def test_la_pantalla_grafica_solo_lo_que_se_lee(app, monkeypatch):
    """Un gráfico de 12 productos con el nombre cortado en '...' no decía nada
    que la tabla no dijera mejor."""
    from src.ui import reportes as pantalla

    monkeypatch.setattr(Sesion, "rol", "ADMINISTRADOR")
    widget = pantalla.ReportesWidget()

    titulos = [d.titulo for d in widget.definiciones]
    assert titulos == ["Ingresos por período", "Ventas por producto", "Por usuario",
                       "Por mecánico", "Órdenes con descuento", "Reabastecimiento"]
    con_grafico = {d.titulo for d in widget.definiciones if d.grafico}
    assert con_grafico == {"Ingresos por período", "Por usuario", "Por mecánico"}

    # Los ejes en pesos chilenos y con marcas redondas.
    widget.lista.setCurrentRow(0)
    widget.filas = [(DIA, 1, 13005390, 0, 0, 10928899, 2076491, 0, 13005390)]
    widget._dibujar_grafico(widget.definicion())
    chart = widget.grafico.chart()
    eje = next(e for e in chart.axes() if e.orientation() == Qt.Vertical)
    assert chart.localizeNumbers() and eje.labelFormat() == "$%.0f"
    assert eje.max() == 15000000

    # La participación se lee como porcentaje, con coma.
    widget.lista.setCurrentRow(titulos.index("Ventas por producto"))
    assert widget.grafico.isHidden()
    widget.filas = [("Aceite", "Mobil", 3, 30000, 75.0), ("Filtro", "Mann", 1, 10000, 25.0)]
    widget._llenar_tabla(widget.definicion())
    assert widget.tabla.item(0, 4).text() == "75,0 %"

    # Descuentos: el resumen separa los tres tipos, y doble clic abre la orden.
    abiertas = []
    monkeypatch.setattr(pantalla.DialogoDetalleOrden, "__init__",
                        lambda self, orden_id, parent=None: abiertas.append(orden_id))
    monkeypatch.setattr(pantalla.DialogoDetalleOrden, "exec", lambda self: 0)
    widget.lista.setCurrentRow(titulos.index("Órdenes con descuento"))
    widget.filas = [
        (7, DIA, "Ana", "AB1234", "Paloma", "Flyer N° 0042 (10 %)", 1000, 9000),
        (8, DIA, "Luis", "CD5678", "Paloma", "Gremio/Sindicato (15 %)", 1500, 8500),
        (9, DIA, "Eva", "EF9012", "Paloma", "General (monto)", 500, 9500),
        (10, DIA, "Tom", "GH3456", "Paloma", "General (10 %)", 800, 7200),
    ]
    widget._llenar_tabla(widget.definicion())
    widget._llenar_resumen(widget.definicion())
    cifras = [widget.resumen.itemAt(i).widget().findChild(QLabel).text()
              for i in range(widget.resumen.count()) if widget.resumen.itemAt(i).widget()]
    assert cifras == ["$3.800", "4", "2", "1", "1"]   # descontado, órdenes, general, flyer, gremio
    fila = next(f for f in range(widget.tabla.rowCount()) if widget.tabla.item(f, 0).text() == "8")
    widget.tabla.selectRow(fila)
    widget.abrir_orden(widget.tabla.model().index(fila, 0))
    assert abiertas == [8]

    # Reabastecimiento sin gráfico, y dice cuántos productos no tienen mínimo.
    widget.lista.setCurrentRow(titulos.index("Reabastecimiento"))
    assert widget.grafico.isHidden()
    assert "sin mínimo" in widget.ayuda.text()
