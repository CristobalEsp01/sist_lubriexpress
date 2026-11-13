"""Sin base de datos: el IVA se redondea al peso, como en la boleta."""
import pytest

from src.precios import aplicar_descuento, con_iva, iva_de, redondear_decena


def test_el_iva_se_redondea_al_peso():
    assert iva_de(10000) == 1900
    assert iva_de(38700) == 7353       # 7353.0
    assert iva_de(8319.3) == 1581      # 1580.667, no 1580
    assert con_iva(8000) == 9520


def test_ley_de_redondeo_a_la_decena():
    assert redondear_decena(10001) == redondear_decena(10005) == 10000   # 1 a 5 bajan
    assert redondear_decena(10006) == redondear_decena(10009) == 10010   # 6 a 9 suben
    assert redondear_decena(10000) == 10000
    assert redondear_decena(10004.99) == 10000
    assert redondear_decena(10007.15) == 10010


@pytest.mark.parametrize("neto, pct, monto, esperado", [
    (10000, 10, 0, (10, 0, 1000)),
    (10000, 0, 2500, (0, 2500, 2500)),
    (30000, 0, 50000, (0, 30000, 30000)),   # Órdenes guardaba 50.000: más que la orden
    (10000, 150, 0, (100, 0, 10000)),
    (0, 0, 5000, (0, 0, 0)),
])
def test_el_descuento_nunca_supera_el_neto(neto, pct, monto, esperado):
    assert aplicar_descuento(neto, pct, monto) == esperado
