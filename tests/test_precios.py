"""Sin base de datos: el IVA se redondea al peso, como en la boleta."""
from src.precios import con_iva, iva_de, redondear_decena


def test_el_iva_se_redondea_al_peso():
    assert iva_de(10000) == 1900
    assert iva_de(38700) == 7353       # 7353.0
    assert iva_de(8319.3) == 1581      # 1580.667, no 1580
    assert con_iva(8000) == 9520

def test_ley_de_redondeo_a_la_decena():
    # Casos que bajan al cero anterior (terminaciones 1 a 5)
    assert redondear_decena(10001) == 10000
    assert redondear_decena(10005) == 10000
    
    # Casos que suben a la decena superior (terminaciones 6 a 9)
    assert redondear_decena(10006) == 10010
    assert redondear_decena(10009) == 10010
    
    # Casos terminados en cero quedan igual
    assert redondear_decena(10000) == 10000
    assert redondear_decena(10010) == 10010
    
    # Manejo correcto de decimales o flotantes residuales
    assert redondear_decena(10004.99) == 10000
    assert redondear_decena(10007.15) == 10010