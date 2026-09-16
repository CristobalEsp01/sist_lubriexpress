"""El HTML de la orden para el cliente: sin Qt, con lo guardado y nada más."""
from datetime import datetime

from src.documentos import html_de_orden

ORDEN = {
    "numero": 42, "fecha": datetime(2026, 9, 16, 10, 30), "cliente": "Ana <Soto>", "rut": None,
    "telefono": "912345678", "patente": "JFFG56", "vehiculo": "Nissan Np300 2017",
    "kilometraje": 145035, "tecnico": "Alex Núñez Uribe",
    "lineas": [("Aceite 10W40", 3, 12900), ("Cambio de aceite", 1, 15000)],
    "subtotal": 53700, "descuento": 5370, "impuesto": 9183, "total": 57513,
    "pagada": True, "folio": "MP-2026-001", "notas": "Raya en la puerta\nRevisar frenos",
}


def test_el_html_muestra_lo_cobrado_y_escapa_el_texto():
    html = html_de_orden(ORDEN)
    for esperado in ("Orden de Trabajo N° 42", "16-09-2026 10:30", "Ana &lt;Soto&gt;", "912345678",
                     "JFFG56", "145.035 km", "Cambio de aceite", "$38.700", "$53.700",
                     "- $5.370", "$9.183", "$57.513", "Pagada", "MP-2026-001",
                     "Raya en la puerta<br>Revisar frenos"):
        assert esperado in html, esperado

    sin_extras = dict(ORDEN, descuento=0, folio=None, kilometraje=None, lineas=[], notas=None)
    html = html_de_orden(sin_extras)
    assert "Descuento" not in html and "Folio" not in html
    assert "sin registrar" in html and "sin detalle de insumos" in html and "Sin observaciones" in html
