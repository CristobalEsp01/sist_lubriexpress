"""Sin base de datos: el IVA se redondea al peso, como en la boleta."""
from src.precios import con_iva, iva_de


def test_el_iva_se_redondea_al_peso():
    assert iva_de(10000) == 1900
    assert iva_de(38700) == 7353       # 7353.0
    assert iva_de(8319.3) == 1581      # 1580.667, no 1580
    assert con_iva(8000) == 9520
