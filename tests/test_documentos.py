"""El HTML de la orden para el cliente: sin Qt, con lo guardado y nada más."""
from datetime import datetime

from src.documentos import html_de_orden

# 1. Agregamos el "ajuste" y redondeamos el total y pagado a 57510
ORDEN = {
    "numero": 42, "fecha": datetime(2026, 9, 16, 10, 30), "cliente": "Ana <Soto>", "rut": None,
    "telefono": "912345678", "patente": "JFFG56", "vehiculo": "Nissan Np300 2017",
    "kilometraje": 145035, "tecnico": "Alex Núñez Uribe",
    "lineas": [("Aceite 10W40", 3, 12900), ("Cambio de aceite", 1, 15000)],
    "subtotal": 53700, "descuento": 5370, "impuesto": 9183, "ajuste": -3, "total": 57510,
    "pagada": True, "pagado": 57510, "folio": "MP-2026-001", "notas": "Raya en la puerta\nRevisar frenos",
}


def test_la_orden_a_medio_pagar_muestra_el_abono_y_el_saldo():
    """Lo que el cliente se lleva en la mano tiene que decirle cuánto debe."""
    html = html_de_orden(dict(ORDEN, pagada=False, pagado=20000))
    # 2. Actualizamos el saldo esperado tras el abono (57510 - 20000 = 37510)
    assert "Abonada $20.000 · saldo $37.510" in html
    assert "- $20.000" in html and "<b>$37.510</b>" in html

    sin_pagar = html_de_orden(dict(ORDEN, pagada=False, pagado=0))
    assert "No pagada" in sin_pagar and "Abonado" not in sin_pagar


def test_el_html_muestra_lo_cobrado_y_escapa_el_texto():
    html = html_de_orden(ORDEN)
    # 3. Agregamos el texto del ajuste ("- $3") y modificamos el total ("$57.510")
    for esperado in ("ORDEN DE TRABAJO", "N° 42", "16-09-2026 10:30", "Ana &lt;Soto&gt;", "912345678",
                     "JFFG56", "145.035 km", "Cambio de aceite", "$38.700", "$53.700",
                     "- $5.370", "$9.183", "- $3", "$57.510", "Pagada", "MP-2026-001",
                     "Raya en la puerta<br>Revisar frenos",
                     "LUBRI-EXPRESS", "Rene Schneider 3631", "www.lubri-express.cl",
                     '<img src="logo"'):
        assert esperado in html, esperado
    assert "Tres Puntos" not in html
    
    assert "Abonado" not in html and "Saldo" not in html

    sin_extras = dict(ORDEN, descuento=0, folio=None, kilometraje=None, lineas=[], notas=None)
    html = html_de_orden(sin_extras)
    assert "Descuento" not in html and "Folio" not in html
    assert "sin registrar" in html and "sin detalle de insumos" in html and "Sin observaciones" in html